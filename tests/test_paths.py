"""Filesystem boundaries and operating-system instance ownership."""

import os
import subprocess
import pytest
from file_sorter.models import Problem
from file_sorter.paths import resolve_allowed_path, validate_destination
from file_sorter.settings import ProcessLock


def test_path_boundaries(folders):
    """Reject relative, sibling-prefix, private-state, and ancestor-destination paths."""
    root, source, target, state = folders
    assert resolve_allowed_path(target, (root,), state) == target
    for forbidden in ["relative", root.parent / "files-other", state, source / ".." / ".."]:
        with pytest.raises(Problem):
            resolve_allowed_path(forbidden, (root,), state)
    for destination in [source, root]:
        with pytest.raises(Problem):
            validate_destination(destination, source)


def test_process_lock(folders):
    """A second instance cannot own the same state directory until the first closes."""
    state = folders[3]
    first, second = ProcessLock(state / "lock"), ProcessLock(state / "lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_linked_ancestor_rejected(folders):
    """Linked roots cannot be used to escape canonical containment."""
    root, source, _, state = folders
    link = root / "linked"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links requires Windows developer mode or privileges")
    with pytest.raises(Problem, match="links"):
        resolve_allowed_path(link / "nested", (root,), state)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_rejected(folders):
    """A Windows directory junction is recognized as a reparse point."""
    root, source, _, state = folders
    link = root / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(source)], capture_output=True)
    if result.returncode:
        pytest.skip("Junction creation is unavailable")
    try:
        with pytest.raises(Problem):
            resolve_allowed_path(link, (root,), state)
    finally:
        link.rmdir()
