"""Small durable SQLite journal; JSON records remain separate from paginated actions."""

import json
import sqlite3
from threading import RLock
from pathlib import Path


class Store:
    """Serialize database access across the scan and execution workers."""

    def __init__(self, path: Path):
        """Create schema version one and a single cross-thread connection."""
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise RuntimeError("Unsupported database schema version.")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS items(owner TEXT, idx INTEGER, data TEXT, PRIMARY KEY(owner,idx));
            PRAGMA user_version=1;
        """)
        if self.get("config", "rules") is None:
            self.put("config", "rules", {"revision": 0, "rules": []})

    def get(self, kind: str, key: str) -> dict | None:
        """Read a detached JSON record or return None for an unknown key."""
        with self.lock:
            row = self.db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, kind: str, key: str, value: dict) -> None:
        """Durably insert or replace one metadata record."""
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (kind, key, json.dumps(value)))

    def records(self, kind: str) -> list[dict]:
        """List metadata records newest-first for history and recovery."""
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid DESC", (kind,))]

    def set_items(self, owner: str, items: list[dict]) -> None:
        """Persist an entire initial action snapshot atomically."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM items WHERE owner=?", (owner,))
            self.db.executemany("INSERT INTO items VALUES (?,?,?)", ((owner, i, json.dumps(item)) for i, item in enumerate(items)))

    def item(self, owner: str, index: int, value: dict) -> None:
        """Persist a single operation transition before or after filesystem mutation."""
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?)", (owner, index, json.dumps(value)))

    def items(self, owner: str, offset: int = 0, limit: int = 100) -> list[dict]:
        """Read a bounded page of actions; limit=-1 is reserved for internal workers."""
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM items WHERE owner=? ORDER BY idx LIMIT ? OFFSET ?", (owner, limit, offset))]

    def close(self) -> None:
        """Close the database after all workers stop."""
        self.db.close()
