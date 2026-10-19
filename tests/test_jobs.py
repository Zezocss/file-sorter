"""Job cancellation, serialization, and journal recovery across service restarts."""

import threading
from file_sorter import jobs
from file_sorter.jobs import Service
from file_sorter.storage import Store
from conftest import rule, wait_for


def test_cancellation_and_concurrent_submission(client, folders, monkeypatch):
    """Cancellation lets the current operation finish and prevents the next operation."""
    _, source, target, _ = folders
    for name in ["a.jpg", "b.jpg"]:
        (source / name).write_bytes(name.encode())
    client.put("/api/rules", json={"revision": 0, "rules": [rule(target)]})
    first = client.post("/api/previews", json={"source": str(source)}).json()
    wait_for(client, "previews", first["id"])
    second = client.post("/api/previews", json={"source": str(source)}).json()
    wait_for(client, "previews", second["id"])
    entered, release = threading.Event(), threading.Event()
    original = jobs.move_file_safely

    def paused_move(*args):
        """Hold the first transfer at a deterministic boundary for concurrent requests."""
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(jobs, "move_file_safely", paused_move)
    job = client.post("/api/jobs", json={"preview_id": first["id"], "idempotency_key": "first"}).json()
    try:
        assert entered.wait(10)
        assert client.post("/api/jobs", json={"preview_id": second["id"], "idempotency_key": "second"}).status_code == 409
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    finally:
        release.set()
    result = wait_for(client, "jobs", job["id"])
    assert result["state"] == "cancelled"
    assert result["processed"] == 1
    assert (source / "b.jpg").exists()


def test_recovery_never_replays(folders):
    """All ambiguous transfer phases are retained for inspection rather than automatically retried."""
    root, source, target, state = folders
    state.mkdir()
    store = Store(state / "sorter.db")
    original = source / "a.jpg"
    original.write_bytes(b"original")
    phases = ["preparing", "moving", "copying", "publishing", "published"]
    store.put("job", "abandoned", {"id": "abandoned", "state": "running"})
    store.set_items("abandoned", [{"source": str(original), "destination": str(target / "a.jpg"), "phase": phase} for phase in phases])
    service = Service(store, (root,), state)
    try:
        assert store.get("job", "abandoned")["state"] == "interrupted"
        assert all(item["phase"] == "needs_review" for item in store.items("abandoned"))
        assert original.read_bytes() == b"original"
        assert not target.exists()
    finally:
        service.close()
        store.close()
