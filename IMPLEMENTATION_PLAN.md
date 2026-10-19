# File Sorter implementation plan

Status: implemented initial release. This document retains the original design below; the current implementation, verification evidence, and exact file/function inventory are in `DOCUMENTATION.md`.

## Implementation decisions and remaining release gates

The Python/FastAPI service, SQLite journal, same-origin web interface, rule editor, directory browser, asynchronous preview, collision handling, template renaming, Windows file moves, cancellation, history, and conservative interruption recovery are implemented. The API and security middleware are kept together in `app.py`; scanning lives in `planner.py`; these small modules replace the proposed separate `api.py`, `security.py`, and `scanner.py` files. JSON metadata records plus separate action rows implement the planned storage model.

Windows same-volume moves use `SetFileInformationByHandle` with a no-replace rename while the source is held against concurrent writing/deletion. Cross-volume copying uses a locked source, verified temporary output, no-clobber publication, and deletion of the exact source handle. Non-Windows transfers conservatively retain the original and report that outcome instead of claiming a safe destructive move without mandatory locking.

Recovery annotates uncertain operations and preserves all associated files for review; automatic cleanup/replay is intentionally omitted. Folder roots are supplied on every CLI launch, not modified through the browser. Rename dates use the computer's local date. Paths over 240 characters are rejected conservatively.

The Windows test suite and browser smoke workflow have been run locally. GitHub Actions verified standard-Python installation and all Windows/Linux Python 3.11/3.12 test jobs, plus a fresh-install Windows Chromium workflow, for implementation commit `3a33672`. A real second-volume test is available but requires a second disposable volume; network/cloud filesystem validation remains outside the verified release scope. See `DOCUMENTATION.md` for evidence and limitations.

## 1. Product scope and deployment

Build a single-user, local application. Python performs all filesystem operations; a web interface lets the user choose folders, maintain extension rules, preview actions, and start sorting. Target Windows first, with filesystem abstractions that allow later macOS/Linux support.

Use FastAPI with typed request validation, a plain HTML/CSS/JavaScript frontend served by the same process, and SQLite for rules, previews, and job history. This modest interface does not initially need a frontend framework or Node build pipeline. Select and pin supported dependency versions during implementation, rather than assuming versions in this plan.

Run one service process and one execution worker. Bind only to loopback. A remotely hosted backend could only operate on its own accessible filesystem; it would require a different deployment and security design to manage a user's computer.

Browser folder handles are not a general way to supply a Python service with an absolute local path. Implement a backend-backed directory browser limited to configured permitted roots, plus a validated absolute-path text field. The initial local setup explicitly establishes permitted roots; a web request cannot expand them arbitrarily. Source and destination folders may be on different permitted drives.

## 2. User experience

The main screen has four areas:

1. **Source:** folder path, Browse button, and Include subfolders checkbox (off by default).
2. **Rules:** editable rows with label, destination folder, comma-separated extensions, enabled toggle, and optional rename template. Buttons add, save, and delete rules.
3. **Preview:** source, matched rule, destination filename, and action/reason for each file; filter by move, skip, or error; show counts and total bytes.
4. **Results:** Sort button, progress, Cancel button, completion summary, and per-file outcomes. Past jobs remain accessible.

Example rules, with paths chosen by the user:

| Label | Extensions field | Destination |
| --- | --- | --- |
| Images | `jpg, jpeg, png, gif, webp` | `D:\Sorted\Images` |
| Documents | `pdf, docx, txt, odt` | `D:\Sorted\Documents` |
| Archives | `zip, 7z, tar.gz` | `D:\Sorted\Archives` |

Changing the source, rules, or options invalidates the current preview. Sort is enabled only for a valid preview containing executable actions. Preview and Sort are separate explicit actions. Missing destination directories are listed as planned creations and created only during execution.

Provide keyboard access, associated field labels, visible focus, inline validation, a live progress status, and useful empty/error states. Never display a completed-success message if any file failed.

## 3. Extension matching and rule validation

- Split input on commas, trim whitespace, remove one optional leading dot, normalize case, and deduplicate. ` JPG, .jpeg, png ` becomes `jpg`, `jpeg`, `png`.
- Reject empty entries, all-empty input, wildcards, path separators, whitespace inside extensions, and trailing dots. Accept compound extensions such as `tar.gz`.
- Match filename endings case-insensitively with a dot boundary. Choose the longest matching extension, so `tar.gz` wins over `gz`.
- Reject the same normalized extension in multiple enabled rules. Multiple rules may use the same destination if their extension sets differ.
- Leave unmatched files and files without an extension in place. A dotfile such as `.env` is extensionless; `.config.json` may match `json` if hidden-file processing is enabled.
- Skip hidden files by default, with an explicit option to include them. Document Windows hidden-attribute handling as well as dotfile handling.
- Never move directories as files. Skip symbolic links, Windows junctions/reparse points, and non-regular files; do not traverse linked directories.
- Recursive scans exclude configured destination subtrees, app state, and temporary operation files. Reject destinations equal to the source or ancestors of it; allow descendants only with that exclusion in place.
- A file already in its intended destination is a no-op. Resolve and check canonical paths, not raw string prefixes.

## 4. Renaming and name collisions

Keep original names by default. Offer an optional rule-level filename-stem template with `{stem}`, `{date}`, and `{counter}` tokens. Append the matched extension automatically, preserving its original spelling and compound suffix. Freeze the local job date and counters at preview time. Sort source relative paths deterministically to allocate counters starting at 1 per rule.

Example: `{date}_{stem}_{counter}` maps `holiday.JPG` to `2026-10-19_holiday_1.JPG` for that preview. Reject unknown tokens, path separators, empty names, Windows reserved names, trailing spaces/dots, and unsupported name/path lengths. Renaming must never let a filename escape the selected destination.

Offer collision policies **Keep both** (default) and **Skip**. Keep both adds ` (1)`, ` (2)`, etc. before the complete matched suffix. Plan collisions against existing files and other preview actions. No overwrite mode in the first release.

At execution, a newly occupied destination is skipped with a stale-preview result; do not silently substitute an unreviewed filename. An existence check alone is insufficient: final creation must enforce no-clobber semantics even if an unrelated process creates the target concurrently.

## 5. Execution and recovery

1. Validate roots, rules, source, and destination parents; scan a fixed snapshot rather than repeatedly scanning while moving files.
2. Store a preview with rule revision, option digest, source file identity/stat information, planned target names, and an expiry (proposed: 15 minutes).
3. Sort submits the preview ID and an idempotency key. Reject stale or changed configuration; repeated submission returns the existing job.
4. Persist each file's pending operation before filesystem mutation. Revalidate source identity, size, modification time, path containment, and destination immediately before execution. Skip changed files and require a new preview for them.
5. On the same volume, use a platform-tested move/rename primitive that refuses to replace an existing target. Do not assume all platform rename implementations have the same overwrite behavior.
6. Across volumes, copy to an exclusively created temporary file in the destination directory, flush and verify size plus a content digest, recheck the source, publish without overwriting, and only then remove the original. On any uncertainty retain the original. A source deletion failure is a distinct copied-but-source-retained outcome.
7. Persist each transition and result. Preserve timestamps where supported; report metadata limitations. Handle denied access, locked files, disappearing drives, low disk space, and cloud placeholders as explicit errors.
8. Execute sequentially in a worker so the UI stays responsive. Permit one active job across the service; a process lock prevents accidental second-instance execution.
9. Cancel stops before the next operation; let an in-flight transfer reach a safe boundary. Completed moves remain completed. Cancellation is not undo.
10. On restart, reconcile nonterminal operations against the journal and actual files. Mark uncertain operations as requiring review; do not automatically delete files or repeat ambiguous moves. Clean up only temporary files positively owned by the recorded operation.

Record source/destination, timestamps, rule ID, byte count, state, and structured error for each operation. A multi-file sort is not an atomic transaction; the UI must communicate partial completion. Full undo is deferred because reverse moves can encounter newly created files and changed content.

Concurrent writers cannot be made safe by a preview alone. Use source identity checks and platform file-access safeguards where available; if mutation during transfer cannot be excluded or detected reliably, preserve the source and report the limitation. Test this boundary explicitly before claiming reliable cross-volume moves.

## 6. Local API and security

Serve UI and API from one origin. Validate Host and Origin, disable permissive CORS, and use a locally bootstrapped session with CSRF protection for mutations. Do not place secrets in frontend source or logs. Enforce root containment and link/reparse checks server-side on browsing, previewing, and execution; frontend validation is only a convenience.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Report readiness without exposing private paths. |
| `GET /api/folders?path=...` | List immediate directories within permitted roots. |
| `GET /api/rules` | Load saved rules and revision. |
| `PUT /api/rules` | Validate and save complete rules with expected revision. |
| `POST /api/previews` | Start snapshot planning; return preview ID/status. |
| `GET /api/previews/{id}` | Return status, counts, and paginated actions. |
| `POST /api/jobs` | Start a job from a ready preview and idempotency key. |
| `GET /api/jobs` | Paginated history. |
| `GET /api/jobs/{id}` | Status, progress, and paginated operation results. |
| `POST /api/jobs/{id}/cancel` | Request cancellation at a safe boundary. |

Large scans also run outside the request handler. Poll preview/job status at a modest interval and stop when terminal. Use consistent errors containing code, message, field when relevant, and retryability. Use 422 for invalid input, 403 for disallowed paths, 404 for unknown resources, and 409 for revision conflicts, stale previews, or active-job conflicts.

## 7. Data model and storage

Store a versioned SQLite database in the user's application-data directory, outside source/destination trees and outside Git. Use transactions for rule updates and operation-state changes; database transactions cannot make filesystem moves atomic.

| Record | Principal fields |
| --- | --- |
| Rule | ID, label, destination, normalized extensions, enabled, rename template |
| Configuration | schema version, revision, permitted roots, preferences |
| Preview | ID, source, options, revision, created/expiry times, state, counts |
| Preview action | source fingerprint, matched rule, target, action, reason |
| Job | ID, preview ID, idempotency key, state, timestamps, counters, cancel flag |
| Operation | ID, job ID, source, destination, temporary path, phase, digest, error |

Job states: queued, running, completed, completed_with_errors, cancelled, interrupted. Preview states: scanning, ready, failed, expired. Preserve recovery-critical records; introduce documented history retention later. Never silently prune unfinished operation records.

## 8. Proposed repository and function responsibilities

Everything in this section is a future implementation target, not an existing file or function. Actual signatures and all additional helpers must be documented when created.

| Planned file | Responsibility and initial functions/classes |
| --- | --- |
| `pyproject.toml` | Dependencies, project entry point, test and lint settings. |
| Dependency lock file | Reproducible versions, generated using the chosen package workflow. |
| `.gitignore` | Exclude environments, caches, runtime databases, logs, and build outputs. |
| `src/file_sorter/__init__.py` | Package metadata; no operational side effects. |
| `src/file_sorter/__main__.py` | `main()` parses local startup options and starts the service. |
| `src/file_sorter/app.py` | `create_app()` builds API/static routes; `lifespan()` initializes storage, worker, and recovery. |
| `src/file_sorter/models.py` | Typed rule, preview, job, operation, options, and error models; model validators. |
| `src/file_sorter/settings.py` | `load_settings()` and `validate_roots()` resolve local state and permitted roots. |
| `src/file_sorter/security.py` | `validate_request_origin()` and `verify_csrf()` protect local requests. |
| `src/file_sorter/paths.py` | `resolve_allowed_path()`, `list_directories()`, `is_link_or_reparse_point()`, and `validate_destination()` enforce filesystem boundaries. |
| `src/file_sorter/rules.py` | `parse_extensions()`, `validate_rules()`, and `match_rule()` normalize and match rules. |
| `src/file_sorter/scanner.py` | `scan_files()` yields eligible files; `fingerprint_file()` records change-detection information. |
| `src/file_sorter/naming.py` | `render_filename()` validates templates; `allocate_destination()` plans conflict-safe names. |
| `src/file_sorter/planner.py` | `build_preview()` creates immutable actions; `validate_preview()` checks revision and expiry. |
| `src/file_sorter/mover.py` | `move_file_safely()`, `copy_verify_publish()`, and `publish_no_clobber()` implement transfer boundaries. |
| `src/file_sorter/jobs.py` | `start_job()`, `run_job()`, `cancel_job()`, and `recover_interrupted_jobs()` manage execution. |
| `src/file_sorter/storage.py` | `initialize_database()`, `save_rules()`, `load_rules()`, `save_preview()`, `create_job()`, `record_operation()`, and query helpers persist state. |
| `src/file_sorter/api.py` | Route handler for each endpoint in section 6; delegates business logic to services. |
| `src/file_sorter/static/index.html` | Accessible source, rule editor, preview, progress, and history markup. |
| `src/file_sorter/static/styles.css` | Responsive layout, validation, focus, and status styling. |
| `src/file_sorter/static/api.js` | `requestJson()` handles requests, session protection, and structured errors. |
| `src/file_sorter/static/app.js` | `initialize()`, `browseFolder()`, `saveRules()`, `requestPreview()`, `startSort()`, `pollStatus()`, `cancelSort()`, and render/event helpers manage UI state. |
| `tests/conftest.py` | Temporary directory, database, and service fixtures. |
| `tests/test_rules.py` | Extension normalization, ambiguity, and longest-match tests. |
| `tests/test_paths.py` | Containment, linked directories, and invalid destination tests. |
| `tests/test_naming.py` | Templates, reserved names, and collision tests. |
| `tests/test_planner.py` | Deterministic preview, exclusion, and staleness tests. |
| `tests/test_mover.py` | No-clobber transfers, source retention, and fault-injection tests. |
| `tests/test_jobs.py` | Idempotency, cancellation, journal recovery, and concurrency tests. |
| `tests/test_api.py` | Endpoint contracts, session protection, and validation tests. |
| `tests/e2e/` | Browser workflow tests; inventory each actual file when added. |
| `.github/workflows/ci.yml` | Run applicable checks and Windows filesystem integration tests. |

## 9. Delivery stages and completion gates

1. **Foundation:** create package, locked dependencies, local server, static UI shell, state database, permitted roots, and security boundary. Gate: service starts on loopback; disallowed paths and cross-origin mutations are rejected.
2. **Rules and browsing:** build folder browser, rule persistence, extension parsing, and rule editor. Gate: multiple custom destinations survive restart; invalid/duplicate mappings produce field errors.
3. **Preview and naming:** implement scanner, exclusions, templates, and deterministic plans. Gate: preview does not mutate source or destination trees; test fixtures predict exact actions and names.
4. **Safe execution:** implement journaled transfer, no-clobber operations, job worker, and polling. Gate: successful files arrive intact; collision/error cases preserve data; repeat Sort does not execute twice.
5. **Resilience and usability:** add cancellation, startup recovery, history, accessibility, and large-list pagination. Gate: injected crashes at each transfer phase reconcile conservatively; UI communicates partial results accurately.
6. **Release preparation:** test installation on a clean Windows environment, add real setup commands, complete documentation inventory, run CI, and push meaningful commits. Gate: documented workflow works from fresh checkout and remote branch is verified current.

Each stage ends with its code, relevant tests, and updated documentation in one or more coherent commits. Do not defer documentation to the final stage.

## 10. Test strategy and acceptance criteria

Use isolated temporary fixtures only; never test moves against personal folders. Unit-test parsing and planning, integration-test actual filesystem operations and APIs, and browser-test the complete workflow. Include Windows-specific path/case, reserved-name, locked-file, and junction cases. Cross-volume behavior needs a real two-volume integration test in addition to simulated failures; label skipped environmental tests accurately.

Required scenarios:

- `photo.JPG`, `report.pdf`, and `archive.tar.gz` reach their configured destinations using comma-separated rules.
- Unmatched, extensionless, hidden-by-default, and linked files remain untouched and have understandable reasons.
- Existing destination files are never replaced; simultaneous target creation also cannot clobber data.
- Optional templates preserve extensions, allocate stable counters, and reject unsafe names.
- Recursive scans never re-ingest destination subtrees; default scans leave subfolders untouched.
- Preview leaves file trees unchanged; edited rules, expired previews, and modified sources cannot execute stale actions.
- Interrupted copying, publishing, and source deletion do not cause silent data loss or duplicate blind retries.
- Permission failures and insufficient disk space produce per-file failures while preserving recoverable originals.
- Repeated submissions, multiple browser tabs, and accidental second service instances cannot start conflicting execution.
- Large fixtures (proposed 10,000 files) keep the UI responsive; record measured timings before setting performance guarantees.
- Every tracked project file and every actual function/method has a documentation entry; every feature has status and verification evidence.

## 11. Deferred features

Folder watchers, scheduled sorting, full undo, content-based classification, duplicate-content detection, remote access, multi-user support, installer packaging, and a frontend framework are outside the initial release. Add them only as separately specified work.

## 12. Technical references

- [FastAPI documentation](https://fastapi.tiangolo.com/): Python API framework and typed request models.
- [Python shutil documentation](https://docs.python.org/3/library/shutil.html): standard transfer behavior and metadata limitations; direct `shutil.move()` alone does not implement this plan's recovery/no-clobber contract.
- [Browser directory picker documentation](https://developer.mozilla.org/en-US/docs/Web/API/Window/showDirectoryPicker): browser directory-handle API and availability constraints, informing the backend-backed browsing design.
