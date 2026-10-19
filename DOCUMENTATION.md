# Repository documentation

Last updated: 2026-10-19. Application version: 0.1.0.

## Current implementation

File Sorter is a working local Python application with a same-origin HTML/CSS/JavaScript interface. It is designed for one user and one service instance on Windows. Python performs all file operations; the browser never uploads file contents. Start it with explicit permitted roots using the commands in README.md.

## Features and usage

| Feature | Implemented behavior | Verification |
| --- | --- | --- |
| Local web application | FastAPI serves the UI on loopback; CLI accepts repeated --root plus --state-dir and --port. | API tests, wheel build, browser smoke test |
| Folder selection | Browse permitted roots and their immediate subfolders, or paste absolute paths. Destination folders may be created during execution. | API boundary tests and browser folder-selection test |
| Extension rules | Add/edit/remove/disable named destination rules. Normalize commas, optional leading dots, whitespace and case. Reject empty or duplicate enabled mappings. Save in SQLite with revision checks. | test_rules.py; browser save/reload |
| Extension matching | Longest dot-delimited suffix wins, including tar.gz; bare dotfiles are extensionless. Unknown file types stay put. | test_longest_match_and_dotfiles; test_workflow |
| Scan options | Recursive and hidden inclusion are opt-in. Dotfiles and Windows hidden attributes count as hidden. Exclude destination/state subtrees, reparse points, symbolic links, and operation temporary files. | planner/path tests; link tests may require platform privileges |
| Preview | Background snapshot planning, deterministic relative-path order, read-only file trees, counts/bytes, planned folder creation, 100-row UI pages, page-local filtering. | planner tests, 10,000-file test, browser assertions |
| Renaming | Optional {stem}, {date}, {counter}; date frozen using local system date; per-rule counters start at 1; preserve matched suffix spelling. | naming tests and Unicode move test |
| Collisions | Keep both appends a numeric suffix before the complete extension; Skip leaves the source untouched. Existing targets are never replaced. | collision allocation, publication-race and move tests |
| Stale protection | Fifteen-minute expiry, rule revision checks, UI invalidation on edits, and file identity/size/time checks at execution. A newly occupied target fails without changing the previewed name. | stale-preview, changed-source, and browser invalidation tests |
| Sorting | One job worker, one scan worker, fixed action snapshots, journal transitions, same-volume Windows handle rename, verified cross-volume copying. | API workflow and mover tests |
| Progress and stopping | Poll job status; show counts and each result. Cancel finishes the in-flight operation then stops. Never represents partial failure as clean completion. | cancellation/concurrency tests and browser results |
| History and recovery | Persist job/action records. On startup mark abandoned jobs interrupted and annotate uncertain operations with observed source/target/temp existence. Never automatically replay or delete uncertain data. | recovery test across transfer phases |
| Browser protections | Exact Host and Origin checks, same-origin HttpOnly session cookie, CSRF header for changes, no permissive CORS, no-store caching, CSP and framing protection. | API security tests |
| Documentation | File/symbol reference generated from actual source, checked in CI; hand-written behavioral contracts remain mandatory. | tools/document_inventory.py --check |

Deferred: automatic undo, watchers, scheduling, content classification, duplicate-content detection, remote access, multiple users, and an installer. These are not exposed as working features.

## Startup and architecture

1. `__main__.main` parses CLI arguments and calls `app.create_app`. Settings validate existing absolute permitted roots and reject linked ancestors. The default state location is `%LOCALAPPDATA%/FileSorter`, or `~/.local/share/FileSorter` on non-Windows systems.
2. The application lifespan acquires `service.lock` using the operating system. It opens SQLite, creates the service, and reconciles interrupted records before accepting requests. Lock scope is one state directory; use the same directory for every launch of your instance.
3. The browser bootstraps its local session and loads saved rules. User changes invalidate previews. Saving rules checks a revision so a stale browser cannot silently replace another tab's edits.
4. Preview requests freeze options and the current rule revision, then scan in a separate executor. The planner enumerates files, matches rules, renders names, reserves targets, fingerprints sources, and persists metadata plus action rows. Planning errors are reported without modifying source/destination trees.
5. Sort submits a preview identifier and idempotency key. Under the service lock, the backend rejects stale previews and concurrent jobs, or returns the already-existing job for duplicate submissions. It persists the operation snapshot before queueing the worker.
6. The worker revalidates paths and file fingerprints for every executable action. It journals transfer phases, performs the move, then records final results. The UI polls and pages through those records. Configuration changes do not mutate an already-confirmed job.
7. Shutdown requests cancellation at safe boundaries, joins both executors, closes SQLite, and releases the process lock. A hard shutdown leaves journal evidence for the next startup.

## Module contracts and error handling

All paths are absolute. `Problem` is the expected domain exception: code, user-facing message, HTTP status, optional field. API handlers serialize it in an `error` envelope with a retryable flag for conflicts. Pydantic input errors become 422 field errors. Filesystem exceptions become 422 request failures or per-operation error results. Unexpected worker failures mark the job interrupted. The browser displays failures as text and highlights associated fields where available.

- `models.py`: request schemas reject unknown fields and bound collection/text lengths. Model validation has no filesystem side effects. `Rule`, `RulesInput`, `PreviewInput`, and `JobInput` are consumed by API route handlers.
- `settings.py` and `paths.py`: validate CLI roots, private state exclusion, linked ancestors, file type, and source/destination relationships. Read stat/directory information; only `ProcessLock.acquire` creates its state directory and lockfile. Path checks throw `Problem`/`OSError`; invalid startup configuration throws `ValueError`. Tests live in test_paths.py.
- `rules.py` and `naming.py`: deterministic normalization/matching/template rendering. Rule validation reads destination metadata; allocation reads existence and mutates only an in-memory reservation set. They never create output files. Errors are `Problem` field failures. Used by the service and planner; verified by rule/naming tests.
- `planner.py`: reads a filesystem snapshot and produces `(preview metadata, actions)`. It catches individual file errors, records skipped reasons, and reports scan-directory failures as errors. It never mutates source/destination trees. The service persists the result. `validate_preview` reads timestamps/revisions and raises 409 when a plan is no longer usable. Tested by planner and API tests.
- `mover.py`: performs the only application content transfers. Its `record(phase, **details)` callback must durably persist transitions, and its internal validation callback rechecks boundaries/fingerprints. It returns `moved` or `copied_source_retained`; filesystem/domain errors propagate to the job worker. Owned temporary files may be removed on failed copy; published targets are never removed as cleanup. Tests inject collisions, changed sources, flush failures, deletion failures, and corrupt verification digests.
- `storage.py`: one SQLite connection guarded by an RLock. Every metadata/operation write commits before returning. Reads return detached JSON objects. SQL uses parameterized statements. Database exceptions propagate rather than pretending a journal write succeeded. The service owns lifecycle and ordering.
- `jobs.py`: owns a coordination RLock and separate single-thread executors for planning and sorting. Methods exposed to routes submit/query work; workers persist asynchronous results. Configuration writes, scan submission, and job submission serialize through the coordination lock. Cancellation is a separate durable record to avoid racing job-counter updates. Tests exercise idempotency, conflict handling, cancellation, and recovery.
- `app.py`: owns server session secrets, middleware, route handlers, and lifecycle. API responses contain metadata/paths only, never file content. HTTP handlers delegate domain operations and bound page sizes. Static assets are packaged with the Python module. Tested through TestClient and an actual browser/server.
- `static/api.js`: fetch transport returns parsed JSON, or throws an Error with optional field metadata. Credentials are same-origin; the CSRF token stays in memory.
- `static/app.js`: owns DOM state, preview generation, polling/expiry timers, pages, dirty rule state, and folder dialog selection. Named functions are indexed below; inline event callbacks call those functions through the error-display wrapper. DOM updates use textContent/createElement rather than interpolating filenames into HTML. All filesystem changes go through the Sort API.
- `tests/`: fixtures use disposable temporary folders. Test callbacks inject narrowly scoped behavior (e.g. ENOSPC or paused transfers) and assert source/target contents. Platform-dependent tests skip explicitly when their prerequisites are absent. No test is authorized to touch personal file collections.
- `tools/document_inventory.py`: reads project files through Git's tracked/unignored inventory, parses Python AST and JavaScript function declarations/callback lines, and writes only the generated part of this document. `--check` reads only and fails if the generated inventory differs. It validates completeness, not the truth of behavioral prose.

## Transfer protocol and platform boundaries

Windows opens the source with GENERIC_READ + DELETE, FILE_SHARE_READ only. This denies concurrent writers/deleters and fails conservatively when an incompatible handle is already open. A same-volume move renames the exact handle with FILE_RENAME_INFO and ReplaceIfExists false. Unicode target buffers use UTF-16 lengths. No existence-check-then-overwrite rename is used.

For a cross-volume fallback, journal a unique temporary pathname in the destination folder before creating it exclusively. Stream bytes from the locked source, flush/fsync, and compare SHA-256 and byte length with the copied output. Recheck source identity and target availability, copy supported stat metadata, journal publication intent, publish with a no-replace primitive, and journal publication. Mark the exact source handle for deletion only after successful publication. Closing the handle completes deletion. Failure to delete returns `copied_source_retained` and leaves both files available.

Non-Windows systems use the verified copy path even on a single volume and retain the original; no equivalent mandatory source locking is claimed. POSIX temporary publication uses an exclusive hard link and unlinks the owned temporary pathname. Filesystems without required primitives fail conservatively. Cross-volume ACLs, alternate data streams, and all platform-specific metadata are not guaranteed to survive copying.

This protects against ordinary filename collisions and concurrent file writers under the stated Windows sharing semantics. It does not claim protection against malicious processes replacing parent directories between checks, failing storage hardware, or every network/cloud filesystem implementation. Link/reparse ancestors are checked repeatedly, but this is not a capability-based filesystem sandbox against hostile local users. Use trusted local folders. The portable destination-path limit is 240 characters; Windows forbidden characters/reserved basenames and 255 UTF-16-unit component limits are checked before moves.

## Journal, schema, and recovery

SQLite schema version 1 uses WAL mode and FULL synchronous writes:

| Table/record | Contents and ownership |
| --- | --- |
| `records(kind, id, data)` | Primary key `(kind,id)`; JSON metadata, independent of potentially large action lists. |
| `items(owner, idx, data)` | Primary key `(owner,idx)`; ordered JSON preview actions or job operations; SQL LIMIT/OFFSET pagination. |
| `config/rules` | Revision and normalized mappings, including token lists. |
| `preview/<id>` | Source/options/digest/revision, date, created/expiry times, state, counts, bytes, total; failed scans carry error text. |
| `job/<id>` | Preview ID, idempotency key, timestamps, state, totals/counters, cancellation summary and optional error. |
| `cancel/<job id>` | Cancellation request time, separate from worker-owned progress records. |
| Action/operation | Source/target, fingerprint `[device,inode,size,mtime_ns,ctime_ns]`, rule identifiers, planned action/reason, bytes, phase, optional temporary path/digest/error/recovery evidence. |

Preview states: scanning, ready, failed; expired is calculated on read. Job states: queued, running, completed, completed_with_errors, cancelled, interrupted. Operation phases include planned, preparing, moving, copying, publishing, published, moved, skipped, error, copied_source_retained, and needs_review.

Recovery marks queued/running/interrupted jobs interrupted and labels nonterminal transfer phases needs_review with observed path existence. Completed outcomes remain recorded; pending planned actions are not replayed. Recovery does not infer that a target is correct solely because it exists. It does not remove temporary files or original files. Inspect relevant paths and verify content manually before deciding what to retain. History has no automatic retention/pruning yet; private paths in the database must not be committed or shared by default. SQLite transactions do not make filesystem operations atomic.

## API reference

All routes are served from the same loopback origin. Session bootstrap is required before other private API calls. Mutations require the exact Origin and X-CSRF-Token plus the HttpOnly session cookie. Errors use `{"error":{"code":...,"message":...,"field":...,"retryable":...}}`.

| Method/path | Request | Response / side effect |
| --- | --- | --- |
| GET `/api/health` | None | Readiness only. |
| GET `/api/session` | Same-origin request | CSRF token, permitted roots; sets SameSite=Strict HttpOnly cookie. |
| GET `/api/folders` | Optional absolute `path` | Current path, allowed parent, immediate directories; no path means roots. |
| GET `/api/rules` | Session | Rule collection and revision. |
| PUT `/api/rules` | `{revision,rules}` | Validated persisted collection; 409 for stale revision. |
| POST `/api/previews` | `{source,recursive=false,include_hidden=false,collision="keep_both"}` | 202 scanning record; asynchronous read-only filesystem planning. |
| GET `/api/previews/{id}` | offset=0, limit=100 (maximum 500) | Preview metadata and paginated items. |
| POST `/api/jobs` | `{preview_id,idempotency_key}` | 202 new or deduplicated job; 409 when stale/busy. |
| GET `/api/jobs` | offset=0, limit=20 (maximum 100) | Total and paginated job metadata. |
| GET `/api/jobs/{id}` | offset=0, limit=100 (maximum 500) | Progress and paginated operation results. |
| POST `/api/jobs/{id}/cancel` | Empty body accepted | Request acknowledged; no undo of completed files. |

Other statuses: 403 for forbidden roots/origins/session/CSRF, 404 for missing resources, and 422 for invalid fields or request-level filesystem failures. Job operations contain per-file errors so one ordinary failure does not conceal other results. Session secrets reset on server restart; reload the page to obtain a fresh session.

## Validation and outstanding release checks

The expanded Windows run passed 41 tests with three explicit environment skips. The subsequent targeted API/path regression run passed 6 tests with 2 environment skips, including the newly added background-scan responsiveness test (42 distinct passing tests overall). The 10,000-file read-only preview took 44.56 seconds in this workspace (59.38 seconds for the full run, including fixture setup). The real Edge browser smoke test passed folder browsing, rule persistence, preview/invalidation, sorting, content integrity, history, and responsive layout with no JavaScript errors. A Python wheel was built, installed into an isolated directory, and verified to include the packaged frontend and working CLI help. One upstream Starlette deprecation warning concerns its httpx test adapter; it does not indicate an application test failure.

[GitHub Actions run 39292688373](https://github.com/Zezocss/file-sorter/actions/runs/39292688373) passed all five jobs for implementation commit `3a33672`: Windows and Ubuntu with Python 3.11 and 3.12, plus a fresh-package-install Chromium browser workflow on Windows. These jobs verify standard-Python installation, tests, documentation inventory, and JavaScript syntax independently of the bundled local runtime.

A real second-volume test exists but requires FILE_SORTER_SECOND_VOLUME. Symbolic-link/junction tests require OS capabilities. CI runner installation is verified; arbitrary end-user machine configurations and network/cloud filesystems are not. There is no promised performance SLA and no automatic recovery replay.

## Documentation and contribution contract

ALWAYS update this document when adding, changing, moving, or removing a file, function, method, callback, or feature. Update the README for user-visible setup/usage changes. Keep planned/deferred limitations explicit. Every source function has a docstring or entry below; module contracts describe shared callers, errors, side effects and verification. Review behavioral descriptions manually, then regenerate the inventory and run `--check`. Commit implementation, tests, and docs together in coherent commits and keep GitHub current, respecting existing user work and never claiming a push succeeded without verification.

Generated dependencies, caches, build outputs, screenshots, and test fixtures are ignored artifacts. Their generation policies are documented in README.md; they are not individually inventoried. `.git/` contains Git internals, not maintained application source.

<!-- GENERATED INVENTORY -->

## Complete project file inventory

| File | Responsibility |
| --- | --- |
| `.github/workflows/ci.yml` | Runs Python tests, documentation inventory checks, and JavaScript syntax checks on Windows and Linux. |
| `.gitignore` | Excludes private runtime data, local dependencies, caches, and build artifacts. |
| `DOCUMENTATION.md` | Architecture, features, API/storage contracts, verification, and generated complete file/symbol inventory. |
| `IMPLEMENTATION_PLAN.md` | Original design, implementation status, accepted changes, and remaining release gates. |
| `README.md` | Installation, launch, usage, limitations, and mandatory AI/contributor maintenance instructions. |
| `package-lock.json` | Exact optional browser-test dependency graph generated by npm. |
| `package.json` | Optional Playwright browser-test dependency and npm test:e2e command; no frontend build required. |
| `pyproject.toml` | Python package metadata, dependency bounds, console entry point, packaged static assets, and pytest settings. |
| `requirements.lock` | Pinned application and test dependencies for repeatable installation. |
| `src/file_sorter/__init__.py` | Local File Sorter package; importing it performs no filesystem operations. |
| `src/file_sorter/__main__.py` | Command-line entry point for explicit local folder access. |
| `src/file_sorter/app.py` | Local-only FastAPI application, session protection, and endpoint contracts. |
| `src/file_sorter/jobs.py` | Single-worker job coordination, asynchronous planning, and conservative recovery. |
| `src/file_sorter/models.py` | Validated API inputs and structured application errors. |
| `src/file_sorter/mover.py` | No-clobber file transfer primitives with durable phase callbacks. |
| `src/file_sorter/naming.py` | Portable filename validation and deterministic collision allocation. |
| `src/file_sorter/paths.py` | Canonical path boundaries and directory navigation. |
| `src/file_sorter/planner.py` | Read-only scans and immutable, deterministic file-movement previews. |
| `src/file_sorter/rules.py` | Extension parsing, rule validation, and longest-suffix matching. |
| `src/file_sorter/settings.py` | Explicit local root configuration and an operating-system process lock. |
| `src/file_sorter/static/api.js` | Same-origin JSON transport with a memory-only CSRF token and structured errors. |
| `src/file_sorter/static/app.js` | DOM construction, rule editing, preview invalidation, folder browsing, pagination, polling, and job history. |
| `src/file_sorter/static/index.html` | Accessible page shell: source, rule editor, review/results, history, and folder-selection dialog. |
| `src/file_sorter/static/styles.css` | Responsive green/cream visual design, control states, tables, dialog, and mobile layout. |
| `src/file_sorter/storage.py` | Small durable SQLite journal; JSON records remain separate from paginated actions. |
| `tests/conftest.py` | Isolated test directories, rules, and an authenticated in-process HTTP client. |
| `tests/e2e/workflow.mjs` | Real Chromium smoke test: configure rules, preview, sort, and assert the resulting UI and file contents. |
| `tests/test_api.py` | Public API contracts, same-origin protection, and end-to-end sorting. |
| `tests/test_jobs.py` | Job cancellation, serialization, and journal recovery across service restarts. |
| `tests/test_mover.py` | Real transfer and failure injection tests that assert original data survives failures. |
| `tests/test_naming.py` | Template and collision correctness, including portable Windows restrictions. |
| `tests/test_paths.py` | Filesystem boundaries and operating-system instance ownership. |
| `tests/test_planner.py` | Read-only snapshots, stable names, scan exclusions, and expiration. |
| `tests/test_rules.py` | Rule input normalization and extension specificity. |
| `tools/document_inventory.py` | Generate or check the repository file/function reference inside DOCUMENTATION.md. |

## Complete function, method, class, and callback inventory

Signatures identify inputs/defaults and annotated returns. Descriptions explain behavior and side effects; the module contracts above define shared error handling, callers, concurrency, and verification. Nested functions use qualified names. Anonymous callbacks include their source expressions. This section is generated from source and checked in CI; semantic documentation still requires human/AI review.

### `src/file_sorter/__main__.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `main` | `() -> None` | Parse permitted roots/state/port and start one loopback-bound service process. |

### `src/file_sorter/app.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `create_app` | `(roots: list[str \| Path], state_directory: Path, port: int=8765) -> FastAPI` | Construct a loopback-only application; lifespan owns lock, database, and workers. |
| `create_app.lifespan` | `(app)` | Acquire state ownership, initialize services, then close them in reverse order. |
| `create_app.security` | `(request: Request, call_next)` | Enforce Host/origin/session/CSRF checks and deny cross-site resource requests. |
| `create_app.problem_handler` | `(request, exc)` | Serialize expected domain failures using the shared error envelope. |
| `create_app.validation_handler` | `(request, exc)` | Convert typed request failures to concise field errors without echoing inputs. |
| `create_app.filesystem_handler` | `(request, exc)` | Return expected filesystem-access failures without exposing a traceback. |
| `create_app.index` | `()` | Serve the application shell without embedded private data or session secrets. |
| `create_app.health` | `()` | Report readiness without filesystem details. |
| `create_app.bootstrap` | `()` | Bootstrap same-origin browser credentials in an HttpOnly cookie and JSON token. |
| `create_app.folders` | `(path: str \| None=None)` | Browse only approved immediate directories, returning a bounded parent link. |
| `create_app.get_rules` | `()` | Return saved rules with their concurrency revision. |
| `create_app.put_rules` | `(body: RulesInput)` | Validate and save the submitted rule set atomically. |
| `create_app.post_preview` | `(body: PreviewInput)` | Queue read-only planning and return its scan identifier. |
| `create_app.get_preview` | `(key: str, offset: int=Query(0, ge=0), limit: int=Query(100, ge=1, le=500))` | Return preview status and one page of planned actions. |
| `create_app.post_job` | `(body: JobInput)` | Confirm an immutable preview and return a deduplicated job. |
| `create_app.get_jobs` | `(offset: int=Query(0, ge=0), limit: int=Query(20, ge=1, le=100))` | List paginated persisted job summaries newest first. |
| `create_app.get_job` | `(key: str, offset: int=Query(0, ge=0), limit: int=Query(100, ge=1, le=500))` | Read job progress and one page of journaled operations. |
| `create_app.cancel_job` | `(key: str)` | Request stop at the next safe file boundary; completed moves stay completed. |

### `src/file_sorter/jobs.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `Service` | `class` | Coordinate configuration and work while the Store journals every operation. |
| `Service.__init__` | `(self, store, roots: tuple[Path, ...], state: Path)` | Start serial executors and mark abandoned records for review before new work. |
| `Service.require` | `(self, kind: str, key: str) -> dict` | Read an existing resource or raise a structured 404. |
| `Service.save_rules` | `(self, request: dict) -> dict` | Revision-check and persist normalized rules under the service coordination lock. |
| `Service.preview` | `(self, options: dict) -> dict` | Queue a persisted scan snapshot without blocking the HTTP request. |
| `Service.build` | `(self, key: str, options: dict, config: dict) -> None` | Persist ready preview actions or a public scan failure from the worker. |
| `Service.start_job` | `(self, preview_id: str, idempotency_key: str) -> dict` | Deduplicate submissions and allow only one nonterminal job at a time. |
| `Service.run_job` | `(self, key: str) -> None` | Execute journaled actions sequentially, stopping cancellation at a file boundary. |
| `Service.run_job.record` | `(phase, **details)` | Durably journal this operation before its next transfer phase. |
| `Service.cancel_job` | `(self, key: str) -> dict` | Persist a cancellation request without racing worker progress updates. |
| `Service.recover_interrupted_jobs` | `(self) -> None` | Annotate abandoned operations from filesystem evidence; never replay or delete them. |
| `Service.close` | `(self) -> None` | Request safe stop, wait for workers, and let the application close storage. |

### `src/file_sorter/models.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `Problem` | `class` | Expected service failure serialized by the API without a traceback. |
| `Problem.__init__` | `(self, code: str, message: str, status: int=422, field: str \| None=None)` | Store the public error code, message, HTTP status, and optional field. |
| `Problem.payload` | `(self) -> dict` | Return the stable API error envelope; conflicts may be retried after refresh. |
| `Input` | `class` | Reject unknown fields instead of silently ignoring misspelled options. |
| `Rule` | `class` | A destination mapping with optional filename-stem template. |
| `RulesInput` | `class` | Revision-checked replacement of the saved rule collection. |
| `PreviewInput` | `class` | Source and scan options frozen into a preview. |
| `JobInput` | `class` | A confirmed preview and a retry-safe submission identifier. |

### `src/file_sorter/mover.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `publish_no_clobber` | `(source: Path, target: Path) -> None` | Publish without replacement: Windows rename, or POSIX hard link then unlink. |
| `locked_reader` | `(source: Path)` | On Windows hold read+delete access excluding writers/deleters; POSIX is read-only. |
| `delete_locked_source` | `(stream) -> None` | Mark the exact open Windows source for deletion on close; never unlink by path. |
| `rename_locked_source` | `(stream, target: Path) -> None` | Rename the exact Windows handle without replacement while writers remain excluded. |
| `rename_locked_source.RenameInfo` | `class` | Variable-length Windows FILE_RENAME_INFO buffer with an absolute target name. |
| `copy_verify_publish` | `(source: Path, target: Path, fingerprint: list[int], record, validate) -> str` | Copy across volumes, verify content, publish exclusively, then safely remove source. |
| `move_file_safely` | `(action: dict, roots: tuple, state: Path, record) -> str` | Revalidate a preview action, transfer without overwrites, and report final outcome. |
| `move_file_safely.validate` | `()` | Recheck source/destination boundaries and preview fingerprint at transfer boundaries. |

### `src/file_sorter/naming.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `validate_name` | `(name: str) -> str` | Return a safe filename or raise a field error, including Windows restrictions. |
| `render_filename` | `(name: str, extension: str, template: str, date: str, counter: int) -> str` | Render an optional stem template, retaining the exact matched suffix spelling. |
| `allocate_destination` | `(folder: Path, name: str, extension: str, reserved: set[str], policy: str) -> Path \| None` | Reserve a deterministic free target; skip collisions when requested. |

### `src/file_sorter/paths.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `is_link_or_reparse_point` | `(path: Path) -> bool` | Inspect a path without following it; missing paths are not links. |
| `within` | `(path: Path, parent: Path) -> bool` | Compare canonical path components, respecting platform path case semantics. |
| `resolve_allowed_path` | `(raw: str \| Path, roots: tuple[Path, ...], state: Path) -> Path` | Validate absolute paths, all existing ancestors, containment, and state exclusion. |
| `validate_destination` | `(destination: Path, source: Path) -> None` | Reject a source itself, its ancestors, and existing non-directory destinations. |
| `list_directories` | `(path: Path) -> list[dict]` | List immediate regular directories; callers enforce root boundaries on results. |
| `list_directories.lambda@51` | `(p)` | Inline key/callback expression: p.name.casefold() |
| `hidden` | `(path: Path) -> bool` | Recognize dot names and the Windows hidden attribute without traversing links. |
| `fingerprint_file` | `(path: Path) -> list[int]` | Read regular-file identity, size and nanosecond timestamps for stale detection. |

### `src/file_sorter/planner.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `scan_files` | `(source: Path, recursive: bool, include_hidden: bool, excluded: list[Path])` | Yield (path, skip reason) in stable order; never traverse excluded or linked trees. |
| `scan_files.lambda@23` | `(p)` | Inline key/callback expression: (p.name.casefold(), p.name) |
| `build_preview` | `(options: dict, config: dict, roots: tuple[Path, ...], state: Path, preview_id: str \| None=None) -> tuple[dict, list[dict]]` | Build a snapshot without changing file trees; collect per-file failures as actions. |
| `build_preview.lambda@69` | `(entry)` | Inline key/callback expression: (str(entry[0].relative_to(source)).casefold(), str(entry[0])) |
| `validate_preview` | `(preview: dict, revision: int) -> None` | Reject expired, unfinished, configuration-stale, or empty plans before execution. |

### `src/file_sorter/rules.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `parse_extensions` | `(value: str) -> list[str]` | Normalize comma-separated extensions, rejecting empty or malformed tokens. |
| `validate_rules` | `(rules: list[dict], roots: tuple, state) -> list[dict]` | Normalize mappings and reject duplicate IDs/extensions and unsafe destinations. |
| `match_rule` | `(name: str, rules: list[dict]) -> tuple[dict, str] \| None` | Choose the longest enabled extension with a nonempty filename stem. |
| `match_rule.lambda@45` | `(item)` | Inline key/callback expression: len(item[1]) |

### `src/file_sorter/settings.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `default_state_directory` | `() -> Path` | Choose per-user application storage outside the repository by default. |
| `validate_roots` | `(roots: list[str \| Path], state: Path) -> tuple[Path, ...]` | Require existing absolute directories without linked ancestors or state overlap. |
| `ProcessLock` | `class` | Hold an OS lock for one service using a particular state directory. |
| `ProcessLock.__init__` | `(self, path: Path)` | Remember the lockfile path without acquiring it yet. |
| `ProcessLock.acquire` | `(self) -> None` | Acquire an exclusive nonblocking lock; fail if another instance owns it. |
| `ProcessLock.release` | `(self) -> None` | Close the owned handle, releasing its lock without deleting the lockfile. |

### `src/file_sorter/static/api.js`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `requestJson` | `(path, method = "GET", body)` | Send JSON with session/CSRF credentials; return parsed data or throw a readable HTTP error. |
| `bootstrapSession` | `()` | Fetch bootstrap data, establish the cookie, and retain the CSRF token in module memory. |

### `src/file_sorter/static/app.js`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `notify` | `(message, error = false)` | Render success/error text into the live status region without interpreting HTML. |
| `attempt` | `(action)` | Await an event action and route rejected promises to the status region. |
| `invalidate` | `()` | Invalidate preview and expiry timer after edits; disable Sort and reset preview counters. |
| `changedRules` | `()` | Mark rules dirty, invalidate preview, and update the enabled-rule count. |
| `element` | `(tag, className, text)` | Create a DOM node with optional class/text; used by all dynamic rendering. |
| `field` | `(label, input)` | Wrap an input with an explicitly associated label. |
| `addRule` | `(rule = {})` | Build one editable rule row and register its input/remove/browse callbacks. |
| `collectRules` | `()` | Read current editable rows into API rule payloads without modifying files. |
| `saveRules` | `()` | Persist revision-checked rules; update saved state and invalidate previous preview. |
| `browseFolder` | `(target)` | Remember the receiving input and open the permitted-roots directory dialog. |
| `loadFolder` | `(path)` | Fetch one directory listing and render navigation; propagate permission/read errors. |
| `formatBytes` | `(bytes)` | Format nonnegative byte counts into human-readable binary units. |
| `requestPreview` | `()` | Save dirty rules, submit source/options, and start generation-guarded polling. |
| `renderItems` | `()` | Render a filtered page of source/target/status rows and update pagination controls. |
| `pollStatus` | `(ticket)` | Fetch a preview/job page, update progress, schedule polling, and invalidate expired previews. |
| `startSort` | `()` | Submit the reviewed preview with an idempotency key and switch to job results. |
| `loadHistory` | `()` | Render a page of persistent job summaries and register detail-navigation callbacks. |
| `initialize` | `()` | Bootstrap credentials, load saved rules/history, wire controls, and resume active-job viewing. |
| `callback@4` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: const $ = (id) => document.getElementById(id); |
| `callback@17` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: document.querySelectorAll(".field-error").forEach(node => node.remove()); |
| `callback@18` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: document.querySelectorAll('[aria-invalid="true"]').forEach(node => node.removeAttribute("aria-invalid")); |
| `callback@75` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: remove.addEventListener("click", () => {row.remove(); changedRules();}); |
| `callback@87` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: browse.addEventListener("click", () => attempt(() => browseFolder(destination))); |
| `callback@102` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: return [...document.querySelectorAll(".rule")].map(row => ({id: row.dataset.id, |
| `callback@132` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: button.addEventListener("click", () => attempt(() => loadFolder(item.path))); |
| `callback@165` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: const filtered = pageItems.filter(item => $("filter").value === "all" \|\| item.action === $("filter").value \|\| (item.phase === "error" && $("filter").value === "error")); |
| `callback@207` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: previewTimer = setTimeout(() => {invalidate(); notify("Preview expired. Create a new preview before sorting.");}, Math.max(0, data.expires * 1000 - Date.now())); |
| `callback@221` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: if (running) pollTimer = setTimeout(() => attempt(() => pollStatus(ticket)), 700); |
| `callback@243` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: button.addEventListener("click", () => attempt(async () => {offset = 0; view = {kind: "jobs", id: job.id}; await pollStatus(generation); $("review-title").scrollIntoView({block: "center"});})); |
| `callback@257` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("rule-count").textContent = config.rules.filter(rule => rule.enabled).length; |
| `callback@260` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("browse-source").addEventListener("click", () => attempt(() => browseFolder($("source")))); |
| `callback@261` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("add-rule").addEventListener("click", () => {addRule(); changedRules();}); |
| `callback@262` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("save-rules").addEventListener("click", () => attempt(saveRules)); |
| `callback@263` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("preview").addEventListener("click", () => attempt(requestPreview)); |
| `callback@264` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("sort").addEventListener("click", () => attempt(startSort)); |
| `callback@266` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("cancel").addEventListener("click", () => attempt(async () => {await requestJson('/api/jobs/${view.id}/cancel', "POST", {}); notify("Stop requested. The current file will finish safely.");})); |
| `callback@267` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("previous").addEventListener("click", () => attempt(async () => {offset = Math.max(0, offset-pageSize); await pollStatus(generation);})); |
| `callback@268` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("next").addEventListener("click", () => attempt(async () => {offset += pageSize; await pollStatus(generation);})); |
| `callback@269` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("folder-roots").addEventListener("click", () => attempt(() => loadFolder(null))); |
| `callback@270` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("folder-up").addEventListener("click", () => attempt(() => loadFolder(folderParent))); |
| `callback@271` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("folder-select").addEventListener("click", () => {folderTarget.value = folder; folderTarget.dispatchEvent(new Event("input", {bubbles: true})); $("folder-dialog").close();}); |
| `callback@272` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("refresh-history").addEventListener("click", () => attempt(loadHistory)); |
| `callback@273` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("history-previous").addEventListener("click", () => attempt(async () => {historyOffset = Math.max(0, historyOffset-10); await loadHistory();})); |
| `callback@274` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: $("history-next").addEventListener("click", () => attempt(async () => {historyOffset += 10; await loadHistory();})); |

### `src/file_sorter/storage.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `Store` | `class` | Serialize database access across the scan and execution workers. |
| `Store.__init__` | `(self, path: Path)` | Create schema version one and a single cross-thread connection. |
| `Store.get` | `(self, kind: str, key: str) -> dict \| None` | Read a detached JSON record or return None for an unknown key. |
| `Store.put` | `(self, kind: str, key: str, value: dict) -> None` | Durably insert or replace one metadata record. |
| `Store.records` | `(self, kind: str) -> list[dict]` | List metadata records newest-first for history and recovery. |
| `Store.set_items` | `(self, owner: str, items: list[dict]) -> None` | Persist an entire initial action snapshot atomically. |
| `Store.item` | `(self, owner: str, index: int, value: dict) -> None` | Persist a single operation transition before or after filesystem mutation. |
| `Store.items` | `(self, owner: str, offset: int=0, limit: int=100) -> list[dict]` | Read a bounded page of actions; limit=-1 is reserved for internal workers. |
| `Store.close` | `(self) -> None` | Close the database after all workers stop. |

### `tests/conftest.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `folders` | `(tmp_path)` | Create disposable sortable and private-state trees; never use personal folders. |
| `rule` | `(destination: Path, extensions: str='jpg, png', **overrides) -> dict` | Build a complete rule payload for focused tests. |
| `client` | `(folders)` | Open the app lifespan and bootstrap a same-origin browser session. |
| `wait_for` | `(client, kind: str, key: str) -> dict` | Poll a test resource with a bounded deadline and fail on stuck workers. |

### `tests/e2e/workflow.mjs`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `callback@21` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: server.stderr.on("data", chunk => {serverLog += chunk;}); |
| `callback@22` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: server.on("error", error => {serverLog += error.message;}); |
| `callback@26` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: await new Promise(resolve => setTimeout(resolve, 100)); |
| `callback@31` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: page.on("pageerror", error => errors.push(error.message)); |
| `callback@57` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: await page.waitForFunction(() => !document.getElementById("sort").disabled); |
| `callback@66` | `inline` | Event, mapping, filtering, or test callback in its enclosing workflow: assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true); |

### `tests/test_api.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `test_workflow` | `(client, folders)` | Save custom rules, preview without changes, execute once, and inspect persisted results. |
| `test_security_and_errors` | `(client, folders)` | Reject DNS rebinding, cross-site calls, missing CSRF, invalid paths, and unknown resources. |
| `test_revision_and_stale_preview` | `(client, folders)` | Changed rules cannot accidentally execute a previously reviewed preview. |
| `test_scan_does_not_block_requests` | `(client, folders, monkeypatch)` | A paused background scan leaves health and configuration requests responsive. |
| `test_scan_does_not_block_requests.paused_scan` | `(*args)` | Hold a scan independently of the request-handling thread. |

### `tests/test_jobs.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `test_cancellation_and_concurrent_submission` | `(client, folders, monkeypatch)` | Cancellation lets the current operation finish and prevents the next operation. |
| `test_cancellation_and_concurrent_submission.paused_move` | `(*args)` | Hold the first transfer at a deterministic boundary for concurrent requests. |
| `test_recovery_never_replays` | `(folders)` | All ambiguous transfer phases are retained for inspection rather than automatically retried. |

### `tests/test_mover.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `action_for` | `(source: Path, target: Path) -> dict` | Create a preview-equivalent fingerprinted action for one disposable file. |
| `test_real_move_and_no_clobber` | `(folders)` | Move a real file and preserve a racing target without altering either payload. |
| `test_real_move_and_no_clobber.lambda@25` | `(phase, **kw)` | Inline key/callback expression: phases.append(phase) |
| `test_real_move_and_no_clobber.lambda@32` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_changed_source` | `(folders)` | Reject a modified source before creating output folders. |
| `test_changed_source.lambda@45` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_cross_volume_copy_protocol` | `(folders)` | Exercise verified copying and exact-handle deletion using real files on one volume. |
| `test_cross_volume_copy_protocol.lambda@58` | `(phase, **kw)` | Inline key/callback expression: phases.append(phase) |
| `test_cross_volume_copy_protocol.lambda@58` | `()` | Inline key/callback expression: None |
| `test_publish_race_retains_source` | `(folders, monkeypatch)` | A target created immediately before publication is never overwritten. |
| `test_publish_race_retains_source.racing_publish` | `(temp, final)` | Inject an unrelated file immediately before the real no-clobber primitive. |
| `test_publish_race_retains_source.lambda@80` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_publish_race_retains_source.lambda@80` | `()` | Inline key/callback expression: None |
| `test_disk_full_retains_original` | `(folders, monkeypatch)` | A flush failure before publication leaves the source intact and cleans owned temp data. |
| `test_disk_full_retains_original.disk_full` | `(fd)` | Inject ENOSPC at the copy's durability boundary. |
| `test_disk_full_retains_original.lambda@99` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_disk_full_retains_original.lambda@99` | `()` | Inline key/callback expression: None |
| `test_locked_source` | `(folders)` | An incompatible existing reader prevents movement without corrupting the file. |
| `test_locked_source.lambda@113` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_delete_failure_reports_retained_source` | `(folders, monkeypatch)` | If original removal fails after publication, both verified copies are retained explicitly. |
| `test_delete_failure_reports_retained_source.denied` | `(stream)` | Simulate denied deletion after a successfully verified copy. |
| `test_delete_failure_reports_retained_source.lambda@130` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_delete_failure_reports_retained_source.lambda@130` | `()` | Inline key/callback expression: None |
| `test_unicode_handle_rename` | `(folders)` | Non-BMP Unicode destination names use the correct UTF-16 buffer size. |
| `test_unicode_handle_rename.lambda@142` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_verification_failure_never_publishes` | `(folders, monkeypatch)` | A corrupted verification digest prevents both publication and source deletion. |
| `test_verification_failure_never_publishes.lambda@152` | `(*a)` | Inline key/callback expression: mover.hashlib.sha256(b'wrong') |
| `test_verification_failure_never_publishes.lambda@154` | `(*a, **kw)` | Inline key/callback expression: None |
| `test_verification_failure_never_publishes.lambda@154` | `()` | Inline key/callback expression: None |
| `test_actual_second_volume` | `(folders)` | Validate the actual OS cross-volume fallback when a second test volume is provided. |
| `test_actual_second_volume.lambda@170` | `(*a, **kw)` | Inline key/callback expression: None |

### `tests/test_naming.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `test_template_keeps_compound_suffix` | `()` | Renaming changes only the stem and preserves the compound extension's spelling. |
| `test_template_validation` | `(template)` | Unsafe templates fail, while an empty template intentionally preserves names. |
| `test_collision_reservations` | `(tmp_path)` | Existing files and earlier planned names are reserved before execution. |

### `tests/test_paths.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `test_path_boundaries` | `(folders)` | Reject relative, sibling-prefix, private-state, and ancestor-destination paths. |
| `test_process_lock` | `(folders)` | A second instance cannot own the same state directory until the first closes. |
| `test_linked_ancestor_rejected` | `(folders)` | Linked roots cannot be used to escape canonical containment. |
| `test_junction_rejected` | `(folders)` | A Windows directory junction is recognized as a reparse point. |

### `tests/test_planner.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `test_preview_is_read_only_and_excludes_destinations` | `(folders)` | Recursive previews ignore output trees and hidden files without creating destinations. |
| `test_recursive_counter_order` | `(folders)` | Stable relative-path sorting allocates template counters reproducibly. |
| `test_large_preview` | `(folders)` | Plan 10,000 files without mutation and report measured timing rather than an SLA. |

### `tests/test_rules.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `test_normalization` | `()` | Optional dots, whitespace, case, and repeated entries normalize consistently. |
| `test_invalid_extensions` | `(value)` | Malformed extension lists produce actionable validation errors. |
| `test_longest_match_and_dotfiles` | `(folders)` | Compound suffixes win; a bare dotfile is not its own extension. |
| `test_conflicting_rules` | `(folders)` | An extension cannot belong to multiple enabled rules but disabled rules are allowed. |

### `tools/document_inventory.py`

| Symbol | Signature | Behavior |
| --- | --- | --- |
| `project_files` | `() -> list[str]` | List tracked and unignored project files via Git; omit deleted paths and duplicates. |
| `escape` | `(value: str) -> str` | Escape table separators and newlines in generated reference text. |
| `python_symbols` | `(tree, prefix: str='')` | Yield nested class/function signatures, docstrings, and inline callback expressions. |
| `inventory` | `() -> str` | Build Markdown documenting every current project file and Python/JavaScript symbol. |
| `main` | `() -> None` | Update the generated reference, or fail --check when files/symbols have drifted. |
