# File Sorter

A local application with a Python backend and web interface for moving and renaming files according to user-defined extension rules.

**Status: working initial release, Windows first.** Includes saved rules, folder browsing, read-only previews, optional renaming, safe collision handling, progress, cancellation, and persistent job history.

## Workflow

1. Select a source folder.
2. Add rules containing a destination folder and comma-separated extensions, such as `jpg, jpeg, png`.
3. Review a preview of proposed file moves and optional renames.
4. Click **Sort** and view progress and individual results.

The Python service will run on the computer containing the files. The browser interface will be served locally by that service.

## Install and run

Install Python 3.11 or newer. From this repository in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m file_sorter --root "C:\Users\YourName\Downloads" --root "D:\Sorted"
```

Replace the example paths with existing folders you want the application to access. Repeat `--root` for additional folders. If your Python installation provides `python` instead of `py`, use `python -m venv .venv`. Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. Stop the server with Ctrl+C. No Node installation or frontend build is required to use the application.

`--port 8766` changes the port. `--state-dir "C:\Path\To\PrivateState"` changes storage; the default is `%LOCALAPPDATA%\FileSorter` on Windows and `~/.local/share/FileSorter` elsewhere. Keep that directory private and outside sortable data. Rules and job journals persist there in SQLite, not in the repository. Use one state directory for your application instance.

Browse only shows folders inside the roots supplied at startup. Paste an absolute destination path to create a new subfolder during sorting. Add comma-separated extensions such as `jpg, jpeg, png` or `zip, tar.gz`. Use optional stem templates such as `{date}_{stem}_{counter}`; the original extension is appended automatically.

## Behavior and limits

- No overwrite mode. Keep both adds a number; Skip leaves collisions in place. Newly occupied targets or changed sources require a new preview.
- Recursion and hidden-file processing are off by default. Destination subtrees, application state, linked paths, and operation temporary files are excluded.
- Previews expire after 15 minutes. Changing rules or source/options requires a new preview. Cancel stops after the current file; it does not undo completed moves.
- Windows uses no-replace, handle-based renames and mandatory sharing locks. Cross-volume copies are content-verified before the original is deleted. Cross-volume metadata preservation is best effort; ACLs and alternate streams are not guaranteed.
- On non-Windows systems, verified copies retain the source because equivalent mandatory locking is not implemented. Results explicitly report `copied_source_retained`; this is not reported as a completed move.
- Interrupted operations require manual inspection in history. Do not blindly repeat a sort when both source and destination exist. There is no automatic undo or crash replay.
- Filenames follow Windows restrictions and destination paths are conservatively limited to 240 characters. Use trusted local directories; hostile concurrent directory replacement, network shares, and cloud-provider behavior are outside the tested safety boundary.
- Windows/Linux CI and a fresh-install browser test pass. A real second-volume transfer test still requires a second disposable volume; exact verification evidence is in [DOCUMENTATION.md](DOCUMENTATION.md).

## Development checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/document_inventory.py
.\.venv\Scripts\python.exe tools/document_inventory.py --check
```

The inventory tool documents every project file and Python/JavaScript symbol; update the hand-written behavioral documentation too. Tests use disposable directories. Set `FILE_SORTER_SECOND_VOLUME` to a disposable directory on a genuinely different volume to enable the otherwise-skipped cross-volume integration test.

Optional browser tests (Node.js and Microsoft Edge required):

```powershell
npm ci
$env:PYTHON = "$PWD\.venv\Scripts\python.exe"
npm run test:e2e
```

The browser test starts its own server on port 8877 and uses only `.test-artifacts/` fixtures. Set `FILE_SORTER_TEST_PORT` to change that port, or `BROWSER_CHANNEL=chrome` to use installed Chrome. Screenshots and test data stay ignored by Git.

## Project documents

- [Implementation plan](IMPLEMENTATION_PLAN.md): architecture, behavior, proposed modules and functions, API design, delivery stages, and acceptance criteria.
- [Repository documentation](DOCUMENTATION.md): authoritative inventory of existing files, implemented functions and features, and documentation maintenance requirements.

## Mandatory instructions for future AI models and contributors

- **ALWAYS keep `DOCUMENTATION.md` up to date with every repository change.** Document every added, changed, moved, or removed project file; every function and method, including private helpers and test functions; every feature; and how the pieces work together.
- Update documentation in the same meaningful commit as the corresponding implementation. Clearly distinguish planned behavior from implemented behavior. Update this README when setup, usage, or project status changes.
- **ALWAYS keep GitHub up to date with every change.** Make focused, meaningful commits when a coherent change is complete and its applicable checks pass. Push those commits to the configured GitHub remote and working branch, following repository branch and review rules.
- Check the working tree first. Preserve unrelated user changes. Never commit credentials, local file inventories, personal paths in runtime data, databases, or generated artifacts. Do not force-push or rewrite shared history without explicit authorization.
- If a remote, authentication, permission, or network limitation prevents committing or pushing, report the exact blocker and what remains local. Never claim that GitHub is synchronized without verifying the push.
- Read these documents before implementation. Keep the plan aligned with deliberate design changes and record important decisions in the documentation.

## GitHub

Repository: [Zezocss/file-sorter](https://github.com/Zezocss/file-sorter). The configured remote is `origin`; the current main working branch is `master`. CI runs Python tests and documentation checks on Windows and Linux.
