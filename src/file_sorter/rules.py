"""Extension parsing, rule validation, and longest-suffix matching."""

import re
from .models import Problem
from .naming import render_filename
from .paths import resolve_allowed_path


def parse_extensions(value: str) -> list[str]:
    """Normalize comma-separated extensions, rejecting empty or malformed tokens."""
    result = []
    for raw in value.split(","):
        token = raw.strip().removeprefix(".").casefold()
        if not re.fullmatch(r"[\w+-]+(?:\.[\w+-]+)*", token):
            raise Problem("invalid_extension", "Use comma-separated extensions such as jpg, png, tar.gz; empty entries are invalid.", field="extensions")
        if token not in result:
            result.append(token)
    return result


def validate_rules(rules: list[dict], roots: tuple, state) -> list[dict]:
    """Normalize mappings and reject duplicate IDs/extensions and unsafe destinations."""
    seen, ids, output = set(), set(), []
    for rule in rules:
        if rule["id"] in ids:
            raise Problem("duplicate_rule", "Rule identifiers must be unique.")
        ids.add(rule["id"])
        extensions = parse_extensions(rule["extensions"])
        destination = resolve_allowed_path(rule["destination"], roots, state)
        if destination.exists() and not destination.is_dir():
            raise Problem("invalid_destination", "Choose a directory for the destination.", field="destination")
        render_filename("example.txt", "txt", rule["template"], "2000-01-01", 1)
        if rule["enabled"]:
            if seen.intersection(extensions):
                raise Problem("duplicate_extension", "An extension can belong to only one enabled rule.", field="extensions")
            seen.update(extensions)
        output.append({**rule, "destination": str(destination), "extensions": ", ".join(extensions), "tokens": extensions})
    return output


def match_rule(name: str, rules: list[dict]) -> tuple[dict, str] | None:
    """Choose the longest enabled extension with a nonempty filename stem."""
    matches = [(rule, ext) for rule in rules if rule["enabled"] for ext in rule["tokens"]
               if name.casefold().endswith("." + ext) and len(name) > len(ext) + 1]
    return max(matches, key=lambda item: len(item[1])) if matches else None
