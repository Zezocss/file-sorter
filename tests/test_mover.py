"""Real transfer and failure injection tests that assert original data survives failures."""

import errno
import os
from pathlib import Path
import pytest
from file_sorter import mover
from file_sorter.models import Problem
from file_sorter.paths import fingerprint_file


def action_for(source: Path, target: Path) -> dict:
    """Create a preview-equivalent fingerprinted action for one disposable file."""
    return {"source": str(source), "destination": str(target), "fingerprint": fingerprint_file(source)}


def test_real_move_and_no_clobber(folders):
    """Move a real file and preserve a racing target without altering either payload."""
    root, source, destination, state = folders
    original = source / "photo.JPG"
    original.write_bytes(b"original content")
    target = destination / "photo.JPG"
    action = action_for(original, target)
    phases = []
    outcome = mover.move_file_safely(action, (root,), state, lambda phase, **kw: phases.append(phase))
    assert target.read_bytes() == b"original content"
    assert outcome == ("moved" if os.name == "nt" else "copied_source_retained")
    assert original.exists() == (os.name != "nt")
    other = source / "other.JPG"
    other.write_bytes(b"other")
    with pytest.raises(Problem):
        mover.move_file_safely(action_for(other, target), (root,), state, lambda *a, **kw: None)
    assert other.read_bytes() == b"other"
    assert target.read_bytes() == b"original content"


def test_changed_source(folders):
    """Reject a modified source before creating output folders."""
    root, source, target, state = folders
    original = source / "a.jpg"
    original.write_text("before")
    action = action_for(original, target / original.name)
    original.write_text("after with different size")
    with pytest.raises(Problem, match="changed"):
        mover.move_file_safely(action, (root,), state, lambda *a, **kw: None)
    assert not target.exists()


def test_cross_volume_copy_protocol(folders):
    """Exercise verified copying and exact-handle deletion using real files on one volume."""
    _, source, destination, _ = folders
    destination.mkdir()
    original = source / "a.bin"
    original.write_bytes(b"test payload" * 100000)
    expected = original.read_bytes()
    phases = []
    result = mover.copy_verify_publish(original, destination / original.name, fingerprint_file(original),
                                      lambda phase, **kw: phases.append(phase), lambda: None)
    assert (destination / original.name).read_bytes() == expected
    assert result == ("moved" if os.name == "nt" else "copied_source_retained")
    assert original.exists() == (os.name != "nt")
    assert phases == ["copying", "publishing", "published"]


def test_publish_race_retains_source(folders, monkeypatch):
    """A target created immediately before publication is never overwritten."""
    _, source, destination, _ = folders
    destination.mkdir()
    original, target = source / "a.bin", destination / "a.bin"
    original.write_bytes(b"original")
    publish = mover.publish_no_clobber

    def racing_publish(temp, final):
        """Inject an unrelated file immediately before the real no-clobber primitive."""
        final.write_bytes(b"unrelated")
        publish(temp, final)

    monkeypatch.setattr(mover, "publish_no_clobber", racing_publish)
    with pytest.raises(OSError):
        mover.copy_verify_publish(original, target, fingerprint_file(original), lambda *a, **kw: None, lambda: None)
    assert target.read_bytes() == b"unrelated"
    assert original.read_bytes() == b"original"
    assert not list(destination.glob(".file-sorter-*"))


def test_disk_full_retains_original(folders, monkeypatch):
    """A flush failure before publication leaves the source intact and cleans owned temp data."""
    _, source, destination, _ = folders
    destination.mkdir()
    original = source / "a.bin"
    original.write_bytes(b"original")

    def disk_full(fd):
        """Inject ENOSPC at the copy's durability boundary."""
        raise OSError(errno.ENOSPC, "Disk full")

    monkeypatch.setattr(mover.os, "fsync", disk_full)
    with pytest.raises(OSError):
        mover.copy_verify_publish(original, destination / original.name, fingerprint_file(original), lambda *a, **kw: None, lambda: None)
    assert original.read_bytes() == b"original"
    assert list(destination.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Mandatory sharing lock is Windows-specific")
def test_locked_source(folders):
    """An incompatible existing reader prevents movement without corrupting the file."""
    root, source, destination, state = folders
    original = source / "a.bin"
    original.write_bytes(b"data")
    action = action_for(original, destination / original.name)
    with original.open("rb"):
        with pytest.raises(OSError):
            mover.move_file_safely(action, (root,), state, lambda *a, **kw: None)
    assert original.read_bytes() == b"data"


@pytest.mark.skipif(os.name != "nt", reason="Exact-handle deletion is Windows-specific")
def test_delete_failure_reports_retained_source(folders, monkeypatch):
    """If original removal fails after publication, both verified copies are retained explicitly."""
    _, source, destination, _ = folders
    destination.mkdir()
    original = source / "a.bin"
    original.write_bytes(b"retain both")

    def denied(stream):
        """Simulate denied deletion after a successfully verified copy."""
        raise PermissionError("Deletion denied")

    monkeypatch.setattr(mover, "delete_locked_source", denied)
    result = mover.copy_verify_publish(original, destination / original.name, fingerprint_file(original), lambda *a, **kw: None, lambda: None)
    assert result == "copied_source_retained"
    assert original.read_bytes() == (destination / original.name).read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle rename")
def test_unicode_handle_rename(folders):
    """Non-BMP Unicode destination names use the correct UTF-16 buffer size."""
    root, source, destination, state = folders
    original = source / "photo.jpg"
    original.write_bytes(b"unicode")
    target = destination / "holiday-🌴.jpg"
    assert mover.move_file_safely(action_for(original, target), (root,), state, lambda *a, **kw: None) == "moved"
    assert target.read_bytes() == b"unicode"


def test_verification_failure_never_publishes(folders, monkeypatch):
    """A corrupted verification digest prevents both publication and source deletion."""
    _, source, destination, _ = folders
    destination.mkdir()
    original = source / "a.bin"
    original.write_bytes(b"original")
    monkeypatch.setattr(mover.hashlib, "file_digest", lambda *a: mover.hashlib.sha256(b"wrong"))
    with pytest.raises(OSError, match="verification"):
        mover.copy_verify_publish(original, destination / original.name, fingerprint_file(original), lambda *a, **kw: None, lambda: None)
    assert original.read_bytes() == b"original"
    assert list(destination.iterdir()) == []


@pytest.mark.skipif(not os.environ.get("FILE_SORTER_SECOND_VOLUME"), reason="Set FILE_SORTER_SECOND_VOLUME to a disposable directory on a second volume")
def test_actual_second_volume(folders):
    """Validate the actual OS cross-volume fallback when a second test volume is provided."""
    import tempfile
    root, source, _, state = folders
    second = Path(os.environ["FILE_SORTER_SECOND_VOLUME"]).resolve()
    assert second.stat().st_dev != source.stat().st_dev, "A genuinely different volume is required"
    with tempfile.TemporaryDirectory(prefix="file-sorter-test-", dir=second) as folder:
        original = source / "cross.bin"
        original.write_bytes(b"across volumes")
        target = Path(folder) / original.name
        result = mover.move_file_safely(action_for(original, target), (root, second), state, lambda *a, **kw: None)
        assert target.read_bytes() == b"across volumes"
        assert result == ("moved" if os.name == "nt" else "copied_source_retained")
