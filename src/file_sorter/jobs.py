"""Single-worker job coordination, asynchronous planning, and conservative recovery."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock
import time
from uuid import uuid4

from .models import Problem
from .mover import move_file_safely
from .planner import build_preview, validate_preview
from .rules import validate_rules


class Service:
    """Coordinate configuration and work while the Store journals every operation."""

    def __init__(self, store, roots: tuple[Path, ...], state: Path):
        """Start serial executors and mark abandoned records for review before new work."""
        self.store, self.roots, self.state = store, roots, state
        self.lock = RLock()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sort")
        self.scanner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.recover_interrupted_jobs()

    def require(self, kind: str, key: str) -> dict:
        """Read an existing resource or raise a structured 404."""
        value = self.store.get(kind, key)
        if value is None:
            raise Problem("not_found", "The requested resource does not exist.", 404)
        return value

    def save_rules(self, request: dict) -> dict:
        """Revision-check and persist normalized rules under the service coordination lock."""
        with self.lock:
            current = self.store.get("config", "rules")
            if current["revision"] != request["revision"]:
                raise Problem("revision_conflict", "Rules changed in another tab; reload them before saving.", 409)
            rules = validate_rules(request["rules"], self.roots, self.state)
            config = {"revision": current["revision"] + 1, "rules": rules}
            self.store.put("config", "rules", config)
            return config

    def preview(self, options: dict) -> dict:
        """Queue a persisted scan snapshot without blocking the HTTP request."""
        with self.lock:
            if any(p["state"] == "scanning" for p in self.store.records("preview")):
                raise Problem("scan_busy", "A preview is already being built.", 409)
            key = uuid4().hex
            pending = {"id": key, "state": "scanning", "created": time.time(), "total": 0}
            self.store.put("preview", key, pending)
            config = self.store.get("config", "rules")
            self.scanner.submit(self.build, key, options, config)
            return pending

    def build(self, key: str, options: dict, config: dict) -> None:
        """Persist ready preview actions or a public scan failure from the worker."""
        try:
            preview, actions = build_preview(options, config, self.roots, self.state, key)
            self.store.set_items(key, actions)
            self.store.put("preview", key, preview)
        except Exception as exc:
            self.store.put("preview", key, {"id": key, "state": "failed", "total": 0, "error": str(exc)})

    def start_job(self, preview_id: str, idempotency_key: str) -> dict:
        """Deduplicate submissions and allow only one nonterminal job at a time."""
        with self.lock:
            jobs = self.store.records("job")
            for job in jobs:
                if job["idempotency_key"] == idempotency_key:
                    if job["preview_id"] != preview_id:
                        raise Problem("idempotency_conflict", "This submission key belongs to another preview.", 409)
                    return job
                if job["preview_id"] == preview_id:
                    return job
            if any(job["state"] in {"queued", "running"} for job in jobs):
                raise Problem("job_busy", "Another sort is running.", 409)
            preview = self.require("preview", preview_id)
            validate_preview(preview, self.store.get("config", "rules")["revision"])
            job = {"id": uuid4().hex, "preview_id": preview_id, "idempotency_key": idempotency_key,
                   "state": "queued", "created": time.time(), "total": preview["total"], "processed": 0,
                   "moved": 0, "skipped": 0, "errors": 0, "retained": 0, "cancel": False}
            self.store.set_items(job["id"], self.store.items(preview_id, limit=-1))
            self.store.put("job", job["id"], job)
            self.worker.submit(self.run_job, job["id"])
            return job

    def run_job(self, key: str) -> None:
        """Execute journaled actions sequentially, stopping cancellation at a file boundary."""
        job = self.require("job", key)
        job["state"] = "running"
        self.store.put("job", key, job)
        try:
            for index, action in enumerate(self.store.items(key, limit=-1)):
                if self.store.get("cancel", key):
                    job["state"] = "cancelled"
                    break
                if action["action"] != "move":
                    action["phase"] = "error" if action["action"] == "error" else "skipped"
                    job["errors" if action["action"] == "error" else "skipped"] += 1
                else:
                    def record(phase, **details):
                        """Durably journal this operation before its next transfer phase."""
                        action.update(phase=phase, updated=time.time(), **details)
                        self.store.item(key, index, action)
                    try:
                        outcome = move_file_safely(action, self.roots, self.state, record)
                        action.update(phase=outcome, reason="Moved" if outcome == "moved" else "Copy verified; source retained. Review before removing either file.")
                        job["moved" if outcome == "moved" else "retained"] += 1
                    except (OSError, Problem) as exc:
                        action.update(phase="error", reason=str(exc), error={"code": getattr(exc, "code", "filesystem_error"), "message": str(exc)})
                        job["errors"] += 1
                job["processed"] += 1
                self.store.item(key, index, action)
                self.store.put("job", key, job)
            else:
                job["state"] = "completed_with_errors" if job["errors"] or job["retained"] else "completed"
        except Exception as exc:
            job.update(state="interrupted", error=f"Worker stopped; review journal before retrying: {exc}")
        job["finished"] = time.time()
        job["cancel"] = bool(self.store.get("cancel", key))
        self.store.put("job", key, job)

    def cancel_job(self, key: str) -> dict:
        """Persist a cancellation request without racing worker progress updates."""
        job = self.require("job", key)
        if job["state"] in {"queued", "running"}:
            self.store.put("cancel", key, {"requested": time.time()})
        return {"id": key, "requested": job["state"] in {"queued", "running"}}

    def recover_interrupted_jobs(self) -> None:
        """Annotate abandoned operations from filesystem evidence; never replay or delete them."""
        for preview in self.store.records("preview"):
            if preview["state"] == "scanning":
                preview.update(state="failed", error="Scan interrupted by shutdown; create a new preview.")
                self.store.put("preview", preview["id"], preview)
        for job in self.store.records("job"):
            if job["state"] not in {"queued", "running", "interrupted"}:
                continue
            job.update(state="interrupted", finished=time.time(), error="Interrupted job. Review operation paths; no moves were automatically retried.")
            for index, action in enumerate(self.store.items(job["id"], limit=-1)):
                if action["phase"] not in {"moved", "skipped", "error", "copied_source_retained", "planned"}:
                    action.update(phase="needs_review", reason="Interrupted operation; inspect source, destination, and temporary file.",
                                  recovery={name: Path(action[name]).exists() if action.get(name) else False for name in ("source", "destination", "temporary")})
                    self.store.item(job["id"], index, action)
            self.store.put("job", job["id"], job)

    def close(self) -> None:
        """Request safe stop, wait for workers, and let the application close storage."""
        for job in self.store.records("job"):
            if job["state"] in {"queued", "running"}:
                self.cancel_job(job["id"])
        self.scanner.shutdown(wait=True)
        self.worker.shutdown(wait=True)
