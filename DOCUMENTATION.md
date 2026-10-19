# Repository documentation

Last updated: 2026-10-19.

## Current implementation status

This repository currently contains planning and documentation only. There is no executable application, installed dependency set, API, database, frontend, or test suite. All application behavior in `IMPLEMENTATION_PLAN.md` is proposed.

## Complete existing project file inventory

| File | Purpose | How it connects |
| --- | --- | --- |
| `README.md` | Project introduction, status, intended workflow, document links, and mandatory documentation/GitHub instructions for future contributors and AI models. | Entry point directing readers to the plan and this inventory. |
| `IMPLEMENTATION_PLAN.md` | Detailed product, architecture, workflow, matching, renaming, transfer/recovery, security, API, storage, module/function, testing, and delivery plan. | Specification for future implementation; its proposed file list must not be mistaken for existing code. |
| `DOCUMENTATION.md` | This file: authoritative inventory and status of existing project files, functions, and features, plus the documentation update contract. | Must evolve with every implementation change. |

Git's internal `.git/` files are repository metadata, not application files or maintained project source. Generated dependencies, caches, and runtime data must be described by category and generation/storage policy when introduced, rather than cataloguing individual generated files.

## Complete existing function and method inventory

There are no functions or methods in the current repository. Proposed function names appear only in implementation-plan section 8. Document every actual function and method, including private helpers, event handlers, validators, fixtures, and tests, as it is added.

For each actual function/method record:

| Field | Required content |
| --- | --- |
| Identity | File path, symbol name, and signature. |
| Responsibility | What it does and why it exists. |
| Inputs | Types, defaults, constraints, and assumptions. |
| Outputs | Return values/types and relevant state changes. |
| Errors | Exceptions or error outcomes and caller handling. |
| Side effects | Files read/written/moved, database changes, network/UI effects, and concurrency behavior. |
| Relationships | Principal callers and dependencies; place in the overall flow. |
| Verification | Relevant test names or documented manual checks and limitations. |

Document class responsibilities and state in addition to individual methods. Keep source docstrings consistent with this reference. Small related functions may share a table, but every symbol must be identifiable.

## Feature inventory

| Feature | Status | Specification |
| --- | --- | --- |
| Python backend with local browser UI | Planned | Plan sections 1, 6, 8 |
| Source folder browsing and validated path entry | Planned | Sections 1-2, 6 |
| Destination folders with comma-separated extension rules | Planned | Sections 2-3 |
| Persisted rule editing, enabling, and deletion | Planned | Sections 2, 7 |
| Case-insensitive and compound-extension matching | Planned | Section 3 |
| Optional recursion and hidden-file inclusion | Planned | Section 3 |
| Preview before explicit Sort | Planned | Sections 2, 5 |
| File movement and optional template renaming | Planned | Sections 4-5 |
| Keep-both and skip collision policies | Planned | Section 4 |
| Progress, cancellation, and per-file results | Planned | Sections 2, 5-6 |
| Job history and interrupted-operation recovery | Planned | Sections 5, 7 |
| Local request protection and filesystem boundaries | Planned | Section 6 |
| Automated tests and CI | Planned | Sections 9-10 |
| Detailed implementation specification | Available | `IMPLEMENTATION_PLAN.md` |
| Documentation maintenance and GitHub instructions | Available | `README.md` and this document |

## How the planned application fits together

The local browser UI sends validated selections to the Python API. Rule services normalize extensions; filesystem services validate roots and enumerate eligible files. The planner combines rules, file fingerprints, and naming policies into a persisted preview. A confirmed preview becomes a journaled job. A single worker moves each file through safe transfer phases and records results in SQLite. The UI polls those results and presents completion, partial failure, or cancellation. Startup recovery examines interrupted records before allowing ambiguous operations to proceed.

This describes intended architecture only. Replace or extend it with actual startup flow, module interactions, concrete state transitions, storage locations, configuration, setup commands, and error handling as those exist.

## Required maintenance workflow

1. Inspect the current repository and read the README before changing it.
2. Update this inventory whenever a project file is added, modified in responsibility, moved, or removed. Include configuration, tests, workflows, static assets, and scripts.
3. Add or update every affected function/method entry using the contract above. Remove stale names and links when code is deleted or renamed.
4. Update the feature inventory with implemented/partial/planned status, usage details, defaults, edge cases, limitations, and verification evidence.
5. Keep architecture, API contracts, data schema, and setup instructions consistent with the final code. Explain deliberate deviations from the plan.
6. Run checks appropriate to the change. Before a meaningful commit, compare the project file list and function inventory against the documentation. Future automated inventory checks should detect missing files and symbols without pretending to verify prose accuracy.
7. Commit code and documentation together, then synchronize the configured GitHub branch. Record any blocker honestly in the delivery response.

## Current validation and limitations

The initial change can be checked for documentation completeness and valid local Markdown links. Runtime tests do not apply because application code does not yet exist. No claims about filesystem safety or performance have been verified by implementation tests. No GitHub remote was configured when the repository was inspected.
