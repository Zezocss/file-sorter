"""Read-only snapshots, stable names, scan exclusions, and expiration."""

import pytest
from file_sorter.models import Problem
from file_sorter.planner import build_preview, validate_preview
from file_sorter.rules import validate_rules
from conftest import rule


def test_preview_is_read_only_and_excludes_destinations(folders):
    """Recursive previews ignore output trees and hidden files without creating destinations."""
    root, source, target, state = folders
    (source / "photo.JPG").write_bytes(b"image")
    (source / ".secret.jpg").write_bytes(b"hidden")
    (source / "readme").write_text("keep")
    nested = source / "organized"
    nested.mkdir()
    (nested / "old.jpg").write_text("already sorted")
    rules = validate_rules([rule(target), rule(nested, "pdf", id="pdf")], (root,), state)
    options = {"source": str(source), "recursive": True, "include_hidden": False, "collision": "keep_both"}
    preview, actions = build_preview(options, {"revision": 1, "rules": rules}, (root,), state)
    assert preview["counts"]["move"] == 1
    assert not target.exists()
    assert (source / "photo.JPG").read_bytes() == b"image"
    assert not any(a["source"].endswith("old.jpg") for a in actions)
    assert len(actions) == 4
    validate_preview(preview, 1)
    with pytest.raises(Problem):
        validate_preview(preview, 2)
    preview["expires"] = 0
    with pytest.raises(Problem):
        validate_preview(preview, 1)


def test_recursive_counter_order(folders):
    """Stable relative-path sorting allocates template counters reproducibly."""
    root, source, target, state = folders
    (source / "z.jpg").write_bytes(b"z")
    (source / "a").mkdir()
    (source / "a" / "b.jpg").write_bytes(b"b")
    rules = validate_rules([rule(target, template="{counter}")], (root,), state)
    _, actions = build_preview({"source": str(source), "recursive": True, "include_hidden": False, "collision": "keep_both"}, {"revision": 1, "rules": rules}, (root,), state)
    assert actions[0]["destination"].endswith("1.jpg")
    assert actions[1]["destination"].endswith("2.jpg")


def test_large_preview(folders):
    """Plan 10,000 files without mutation and report measured timing rather than an SLA."""
    import time
    root, source, target, state = folders
    for index in range(10000):
        (source / f"file-{index:05}.jpg").touch()
    rules = validate_rules([rule(target)], (root,), state)
    start = time.perf_counter()
    preview, actions = build_preview({"source": str(source), "recursive": False, "include_hidden": False, "collision": "keep_both"}, {"revision": 1, "rules": rules}, (root,), state)
    elapsed = time.perf_counter() - start
    print(f"10,000-file preview: {elapsed:.2f}s")
    assert preview["counts"]["move"] == len(actions) == 10000
    assert not target.exists()
