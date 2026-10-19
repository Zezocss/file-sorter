"""Public API contracts, same-origin protection, and end-to-end sorting."""

import os
from conftest import rule, wait_for


def test_workflow(client, folders):
    """Save custom rules, preview without changes, execute once, and inspect persisted results."""
    _, source, destination, _ = folders
    (source / "photo.JPG").write_bytes(b"image")
    (source / "report.pdf").write_bytes(b"pdf")
    (source / "archive.tar.gz").write_bytes(b"archive")
    (source / "keep.txt").write_bytes(b"keep")
    rules = [rule(destination, "jpg, pdf, tar.gz")]
    response = client.put("/api/rules", json={"revision": 0, "rules": rules})
    assert response.status_code == 200, response.text
    preview = client.post("/api/previews", json={"source": str(source)}).json()
    preview = wait_for(client, "previews", preview["id"])
    assert preview["state"] == "ready", preview
    assert preview["counts"] == {"move": 3, "skip": 1}
    assert not destination.exists()
    body = {"preview_id": preview["id"], "idempotency_key": "repeat-safe"}
    job = client.post("/api/jobs", json=body).json()
    repeated = client.post("/api/jobs", json=body).json()
    assert job["id"] == repeated["id"]
    result = wait_for(client, "jobs", job["id"])
    assert result["state"] == ("completed" if os.name == "nt" else "completed_with_errors"), result
    assert result["moved" if os.name == "nt" else "retained"] == 3, result
    assert (destination / "archive.tar.gz").read_bytes() == b"archive"
    assert (source / "keep.txt").exists()
    assert client.get("/api/jobs").json()["total"] == 1
    assert len(client.get(f"/api/jobs/{job['id']}?limit=1&offset=1").json()["items"]) == 1


def test_security_and_errors(client, folders):
    """Reject DNS rebinding, cross-site calls, missing CSRF, invalid paths, and unknown resources."""
    root, _, _, _ = folders
    assert client.get("/api/rules", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/previews", json={"source": str(root)}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert client.get("/api/folders", params={"path": str(root.parent)}).status_code == 403
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs?limit=0").status_code == 422
    assert client.get("/api/folders", params={"path": str(root) + "\x00"}).status_code == 422
    assert client.get("/").status_code == 200
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_revision_and_stale_preview(client, folders):
    """Changed rules cannot accidentally execute a previously reviewed preview."""
    _, source, destination, _ = folders
    (source / "a.jpg").write_bytes(b"a")
    payload = {"revision": 0, "rules": [rule(destination)]}
    assert client.put("/api/rules", json=payload).status_code == 200
    assert client.put("/api/rules", json=payload).status_code == 409
    preview = client.post("/api/previews", json={"source": str(source)}).json()
    wait_for(client, "previews", preview["id"])
    payload["revision"] = 1
    assert client.put("/api/rules", json=payload).status_code == 200
    response = client.post("/api/jobs", json={"preview_id": preview["id"], "idempotency_key": "stale"})
    assert response.status_code == 409
    assert not destination.exists()


def test_scan_does_not_block_requests(client, folders, monkeypatch):
    """A paused background scan leaves health and configuration requests responsive."""
    import threading
    from file_sorter import jobs
    _, source, destination, _ = folders
    client.put("/api/rules", json={"revision": 0, "rules": [rule(destination)]})
    entered, release = threading.Event(), threading.Event()
    original = jobs.build_preview

    def paused_scan(*args):
        """Hold a scan independently of the request-handling thread."""
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(jobs, "build_preview", paused_scan)
    response = client.post("/api/previews", json={"source": str(source)})
    try:
        assert response.status_code == 202
        assert entered.wait(10)
        assert client.get("/api/health").json() == {"status": "ready"}
        assert client.get("/api/rules").status_code == 200
        assert client.post("/api/previews", json={"source": str(source)}).status_code == 409
    finally:
        release.set()
    assert wait_for(client, "previews", response.json()["id"])["state"] == "ready"
