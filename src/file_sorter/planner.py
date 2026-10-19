"""Read-only scans and immutable, deterministic file-movement previews."""

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from .models import Problem
from .naming import allocate_destination, render_filename
from .paths import fingerprint_file, hidden, is_link_or_reparse_point, resolve_allowed_path, validate_destination, within
from .rules import match_rule


def scan_files(source: Path, recursive: bool, include_hidden: bool, excluded: list[Path]):
    """Yield (path, skip reason) in stable order; never traverse excluded or linked trees."""
    pending = [source]
    while pending:
        folder = pending.pop()
        try:
            children = sorted(folder.iterdir(), key=lambda p: (p.name.casefold(), p.name))
        except OSError as exc:
            yield folder, f"Cannot read directory: {exc}"
            continue
        directories = []
        for child in children:
            try:
                if is_link_or_reparse_point(child):
                    yield child, "Linked/reparse paths are excluded"
                elif any(within(child, item) for item in excluded):
                    yield child, "Destination or application state subtree excluded"
                elif child.name.startswith(".file-sorter-"):
                    yield child, "Operation temporary file excluded"
                elif not include_hidden and hidden(child):
                    yield child, "Hidden item excluded"
                elif child.is_dir():
                    if recursive:
                        directories.append(child)
                    else:
                        yield child, "Subfolder excluded (recursion is off)"
                elif child.is_file():
                    yield child, None
                else:
                    yield child, "Non-regular file excluded"
            except OSError as exc:
                yield child, f"Cannot inspect item: {exc}"
        pending.extend(reversed(directories))


def build_preview(options: dict, config: dict, roots: tuple[Path, ...], state: Path, preview_id: str | None = None) -> tuple[dict, list[dict]]:
    """Build a snapshot without changing file trees; collect per-file failures as actions."""
    source = resolve_allowed_path(options["source"], roots, state)
    if not source.is_dir():
        raise Problem("source_missing", "Choose an existing source directory.", field="source")
    rules = [rule for rule in config["rules"] if rule["enabled"]]
    if not rules:
        raise Problem("no_rules", "Save at least one enabled rule before previewing.")
    destinations = []
    for rule in rules:
        destination = resolve_allowed_path(rule["destination"], roots, state)
        validate_destination(destination, source)
        destinations.append(destination)
    actions, reserved, counters = [], set(), Counter()
    date = datetime.now().date().isoformat()
    # Global relative-path ordering gives stable template counters across directories.
    entries = sorted(scan_files(source, options["recursive"], options["include_hidden"], [*destinations, state]),
                     key=lambda entry: (str(entry[0].relative_to(source)).casefold(), str(entry[0])))
    for path, reason in entries:
        action = {"source": str(path), "destination": None, "rule": None, "rule_id": None,
                  "action": "error" if reason and reason.startswith("Cannot ") else "skip",
                  "reason": reason or "No matching extension", "bytes": 0, "phase": "planned"}
        if reason is None:
            try:
                resolve_allowed_path(path, roots, state)
                fingerprint = fingerprint_file(path)
                action.update(fingerprint=fingerprint, bytes=fingerprint[2])
                match = match_rule(path.name, rules)
                if match:
                    rule, extension = match
                    counters[rule["id"]] += 1
                    filename = render_filename(path.name, extension, rule["template"], date, counters[rule["id"]])
                    target = allocate_destination(Path(rule["destination"]), filename, extension, reserved, options["collision"])
                    action.update(rule=rule["label"], rule_id=rule["id"])
                    if target:
                        action.update(destination=str(target), action="move", reason="Ready to move",
                                      create_directory=not target.parent.exists())
                    else:
                        action["reason"] = "Destination exists (skip policy)"
            except (OSError, Problem) as exc:
                action.update(action="error", reason=str(exc))
        actions.append(action)
    counts = dict(Counter(item["action"] for item in actions))
    preview = {"id": preview_id or uuid4().hex, "state": "ready", "source": str(source),
               "options": options, "options_digest": hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest(),
               "revision": config["revision"], "date": date, "created": time.time(), "expires": time.time() + 900,
               "total": len(actions), "counts": counts, "bytes": sum(a["bytes"] for a in actions if a["action"] == "move")}
    return preview, actions


def validate_preview(preview: dict, revision: int) -> None:
    """Reject expired, unfinished, configuration-stale, or empty plans before execution."""
    if preview["state"] != "ready" or preview["expires"] < time.time() or preview["revision"] != revision:
        raise Problem("stale_preview", "Create a new preview; this one has expired or changed.", 409)
    if not preview["counts"].get("move"):
        raise Problem("nothing_to_move", "This preview has no executable moves.", 409)
