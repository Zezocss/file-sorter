"""Portable filename validation and deterministic collision allocation."""

import re
import string
from pathlib import Path
from .models import Problem


def validate_name(name: str) -> str:
    """Return a safe filename or raise a field error, including Windows restrictions."""
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (not name or name.endswith((".", " ")) or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.split(".")[0].upper() in reserved or len(name.encode("utf-16-le")) // 2 > 255):
        raise Problem("invalid_filename", "The rename template produces an unsupported filename.", field="template")
    return name


def render_filename(name: str, extension: str, template: str, date: str, counter: int) -> str:
    """Render an optional stem template, retaining the exact matched suffix spelling."""
    suffix = name[-len(extension)-1:]
    stem = name[:-len(suffix)]
    try:
        for _, token, spec, conversion in string.Formatter().parse(template):
            if token is not None and (token not in {"stem", "date", "counter"} or spec or conversion):
                raise ValueError("Unsupported template token")
        output = template.format(stem=stem, date=date, counter=counter) if template else stem
    except (ValueError, KeyError, IndexError) as exc:
        raise Problem("invalid_template", "Use only {stem}, {date}, and {counter} without formatting modifiers.", field="template") from exc
    validate_name(output)
    return validate_name(output + suffix)


def allocate_destination(folder: Path, name: str, extension: str, reserved: set[str], policy: str) -> Path | None:
    """Reserve a deterministic free target; skip collisions when requested."""
    target, number = folder / name, 0
    suffix = name[-len(extension)-1:]
    stem = name[:-len(suffix)]
    while target.exists() or target.is_symlink() or str(target).casefold() in reserved:
        if policy == "skip":
            return None
        number += 1
        target = folder / validate_name(f"{stem} ({number}){suffix}")
    if len(str(target)) > 240:
        raise Problem("path_too_long", "The destination exceeds the application's portable 240-character path limit.")
    reserved.add(str(target).casefold())
    return target
