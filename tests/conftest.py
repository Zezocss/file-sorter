"""Isolated test directories, rules, and an authenticated in-process HTTP client."""

from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from file_sorter.app import create_app


@pytest.fixture
def folders(tmp_path):
    """Create disposable sortable and private-state trees; never use personal folders."""
    root = tmp_path / "files"
    source = root / "inbox"
    source.mkdir(parents=True)
    return root, source, root / "sorted", tmp_path / "state"


def rule(destination: Path, extensions: str = "jpg, png", **overrides) -> dict:
    """Build a complete rule payload for focused tests."""
    return {"id": "images", "label": "Images", "destination": str(destination),
            "extensions": extensions, "enabled": True, "template": "", **overrides}


@pytest.fixture
def client(folders):
    """Open the app lifespan and bootstrap a same-origin browser session."""
    root, _, _, state = folders
    app = create_app([root], state)
    with TestClient(app, base_url="http://127.0.0.1:8765") as browser:
        session = browser.get("/api/session").json()
        browser.headers.update({"Origin": "http://127.0.0.1:8765", "X-CSRF-Token": session["csrf"]})
        yield browser


def wait_for(client, kind: str, key: str) -> dict:
    """Poll a test resource with a bounded deadline and fail on stuck workers."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/{kind}/{key}")
        assert response.status_code == 200, response.text
        result = response.json()
        if result["state"] not in {"queued", "running", "scanning"}:
            return result
        time.sleep(0.01)
    raise AssertionError("Worker did not finish before the deadline")
