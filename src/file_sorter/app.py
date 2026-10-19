"""Local-only FastAPI application, session protection, and endpoint contracts."""

from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import time

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .jobs import Service
from .models import JobInput, PreviewInput, Problem, RulesInput
from .paths import list_directories, resolve_allowed_path, within
from .settings import ProcessLock, validate_roots
from .storage import Store


def create_app(roots: list[str | Path], state_directory: Path, port: int = 8765) -> FastAPI:
    """Construct a loopback-only application; lifespan owns lock, database, and workers."""
    state = state_directory.resolve()
    permitted = validate_roots(roots, state)
    static = Path(__file__).parent / "static"
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @asynccontextmanager
    async def lifespan(app):
        """Acquire state ownership, initialize services, then close them in reverse order."""
        process_lock = ProcessLock(state / "service.lock")
        process_lock.acquire()
        store = service = None
        try:
            store = Store(state / "sorter.db")
            service = Service(store, permitted, state)
            app.state.service = service
            yield
        finally:
            if service:
                service.close()
            if store:
                store.close()
            process_lock.release()

    app = FastAPI(title="File Sorter", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security(request: Request, call_next):
        """Enforce Host/origin/session/CSRF checks and deny cross-site resource requests."""
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if host not in hosts or (origin and origin != f"http://{host}") or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": Problem("forbidden_origin", "Request origin is not permitted.", 403).payload()}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/session", "/api/health"}:
            if not secrets.compare_digest(request.cookies.get("sorter_session", ""), session):
                return JSONResponse({"error": Problem("session_required", "Reload the application to establish a session.", 403).payload()}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if origin != f"http://{host}" or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
                return JSONResponse({"error": Problem("csrf_failed", "Reload the application before making changes.", 403).payload()}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        """Serialize expected domain failures using the shared error envelope."""
        return JSONResponse({"error": exc.payload()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        """Convert typed request failures to concise field errors without echoing inputs."""
        error = exc.errors()[0]
        return JSONResponse({"error": Problem("invalid_input", error["msg"], field=".".join(map(str, error["loc"]))).payload()}, status_code=422)

    @app.exception_handler(OSError)
    async def filesystem_handler(request, exc):
        """Return expected filesystem-access failures without exposing a traceback."""
        return JSONResponse({"error": Problem("filesystem_error", str(exc), 422).payload()}, status_code=422)

    @app.get("/")
    def index():
        """Serve the application shell without embedded private data or session secrets."""
        return FileResponse(static / "index.html")

    @app.get("/api/health")
    def health():
        """Report readiness without filesystem details."""
        return {"status": "ready"}

    @app.get("/api/session")
    def bootstrap():
        """Bootstrap same-origin browser credentials in an HttpOnly cookie and JSON token."""
        response = JSONResponse({"csrf": csrf, "roots": [str(root) for root in permitted]})
        response.set_cookie("sorter_session", session, httponly=True, samesite="strict")
        return response

    @app.get("/api/folders")
    def folders(path: str | None = None):
        """Browse only approved immediate directories, returning a bounded parent link."""
        if path is None:
            return {"path": None, "parent": None, "directories": [{"name": str(root), "path": str(root)} for root in permitted]}
        folder = resolve_allowed_path(path, permitted, state)
        if not folder.is_dir():
            raise Problem("folder_missing", "That folder does not exist.", 404)
        directories = [item for item in list_directories(folder) if not within(Path(item["path"]), state)]
        parent = str(folder.parent) if any(within(folder.parent, root) for root in permitted) else None
        return {"path": str(folder), "parent": parent, "directories": directories}

    @app.get("/api/rules")
    def get_rules():
        """Return saved rules with their concurrency revision."""
        return app.state.service.store.get("config", "rules")

    @app.put("/api/rules")
    def put_rules(body: RulesInput):
        """Validate and save the submitted rule set atomically."""
        return app.state.service.save_rules(body.model_dump())

    @app.post("/api/previews", status_code=202)
    def post_preview(body: PreviewInput):
        """Queue read-only planning and return its scan identifier."""
        return app.state.service.preview(body.model_dump())

    @app.get("/api/previews/{key}")
    def get_preview(key: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        """Return preview status and one page of planned actions."""
        service = app.state.service
        preview = service.require("preview", key)
        if preview["state"] == "ready" and preview["expires"] < time.time():
            preview["state"] = "expired"
        return {**preview, "items": service.store.items(key, offset, limit)}

    @app.post("/api/jobs", status_code=202)
    def post_job(body: JobInput):
        """Confirm an immutable preview and return a deduplicated job."""
        return app.state.service.start_job(body.preview_id, body.idempotency_key)

    @app.get("/api/jobs")
    def get_jobs(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        """List paginated persisted job summaries newest first."""
        jobs = app.state.service.store.records("job")
        return {"total": len(jobs), "items": jobs[offset:offset+limit]}

    @app.get("/api/jobs/{key}")
    def get_job(key: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        """Read job progress and one page of journaled operations."""
        service = app.state.service
        return {**service.require("job", key), "items": service.store.items(key, offset, limit)}

    @app.post("/api/jobs/{key}/cancel")
    def cancel_job(key: str):
        """Request stop at the next safe file boundary; completed moves stay completed."""
        return app.state.service.cancel_job(key)

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
