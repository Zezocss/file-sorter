"""Canonical path boundaries and directory navigation."""

import os
import stat
from pathlib import Path
from .models import Problem


def is_link_or_reparse_point(path: Path) -> bool:
    """Inspect a path without following it; missing paths are not links."""
    try:
        info = path.lstat()
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def within(path: Path, parent: Path) -> bool:
    """Compare canonical path components, respecting platform path case semantics."""
    return path == parent or parent in path.parents


def resolve_allowed_path(raw: str | Path, roots: tuple[Path, ...], state: Path) -> Path:
    """Validate absolute paths, all existing ancestors, containment, and state exclusion."""
    if any(ord(character) < 32 for character in str(raw)):
        raise Problem("invalid_path", "Paths cannot contain control characters.", field="path")
    path = Path(raw)
    if not path.is_absolute():
        raise Problem("absolute_path_required", "Enter an absolute folder path.", field="path")
    # Reject links before resolve() can erase their presence.
    for part in (path, *path.parents):
        if is_link_or_reparse_point(part):
            raise Problem("linked_path", "Symbolic links and reparse points are not allowed.", 403, "path")
    path = path.resolve()
    if not any(within(path, root) for root in roots) or within(path, state):
        raise Problem("path_not_allowed", "This path is outside the permitted folders.", 403, "path")
    return path


def validate_destination(destination: Path, source: Path) -> None:
    """Reject a source itself, its ancestors, and existing non-directory destinations."""
    if within(source, destination):
        raise Problem("invalid_destination", "A destination cannot be the source or its ancestor.", field="destination")
    if destination.exists() and not destination.is_dir():
        raise Problem("invalid_destination", "The destination is not a directory.", field="destination")


def list_directories(path: Path) -> list[dict]:
    """List immediate regular directories; callers enforce root boundaries on results."""
    result = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
        if not is_link_or_reparse_point(child) and child.is_dir():
            result.append({"name": child.name, "path": str(child)})
    return result


def hidden(path: Path) -> bool:
    """Recognize dot names and the Windows hidden attribute without traversing links."""
    return path.name.startswith(".") or bool(getattr(path.lstat(), "st_file_attributes", 0) & 2)


def fingerprint_file(path: Path) -> list[int]:
    """Read regular-file identity, size and nanosecond timestamps for stale detection."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or is_link_or_reparse_point(path):
        raise Problem("not_regular", "Only regular, non-linked files can be moved.")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
