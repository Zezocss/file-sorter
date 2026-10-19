"""Explicit local root configuration and an operating-system process lock."""

import os
from pathlib import Path
from .paths import is_link_or_reparse_point


def default_state_directory() -> Path:
    """Choose per-user application storage outside the repository by default."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "FileSorter"


def validate_roots(roots: list[str | Path], state: Path) -> tuple[Path, ...]:
    """Require existing absolute directories without linked ancestors or state overlap."""
    result = []
    for raw in roots:
        path = Path(raw)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError(f"Permitted root must be an existing absolute directory: {path}")
        if any(is_link_or_reparse_point(part) for part in (path, *path.parents)):
            raise ValueError("Permitted roots must not contain linked ancestors.")
        if path.resolve() == state.resolve() or state.resolve() in path.resolve().parents:
            raise ValueError("Application state cannot be a permitted root.")
        result.append(path.resolve())
    if not result:
        raise ValueError("Provide at least one --root folder.")
    return tuple(dict.fromkeys(result))


class ProcessLock:
    """Hold an OS lock for one service using a particular state directory."""

    def __init__(self, path: Path):
        """Remember the lockfile path without acquiring it yet."""
        self.path, self.file = path, None

    def acquire(self) -> None:
        """Acquire an exclusive nonblocking lock; fail if another instance owns it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("Another File Sorter instance is using this state directory.") from exc

    def release(self) -> None:
        """Close the owned handle, releasing its lock without deleting the lockfile."""
        if self.file:
            self.file.close()
            self.file = None
