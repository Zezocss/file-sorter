# File Sorter

A planned local application with a Python backend and web interface for moving and renaming files according to user-defined extension rules.

**Status: planning only.** There is no application code or runnable server yet.

## Intended workflow

1. Select a source folder.
2. Add rules containing a destination folder and comma-separated extensions, such as `jpg, jpeg, png`.
3. Review a preview of proposed file moves and optional renames.
4. Click **Sort** and view progress and individual results.

The Python service will run on the computer containing the files. The browser interface will be served locally by that service.

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

## Setup and GitHub status

Setup and launch commands will be added when the application exists. At the time of this planning change, the repository has no configured remote. GitHub synchronization requires a GitHub repository URL and suitable access.
