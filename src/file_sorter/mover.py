"""No-clobber file transfer primitives with durable phase callbacks."""

from contextlib import contextmanager
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import shutil
from uuid import uuid4

from .models import Problem
from .paths import fingerprint_file, resolve_allowed_path


def publish_no_clobber(source: Path, target: Path) -> None:
    """Publish without replacement: Windows rename, or POSIX hard link then unlink."""
    if os.name == "nt":
        os.rename(source, target)  # Windows refuses an existing destination.
    else:
        os.link(source, target, follow_symlinks=False)
        source.unlink()


@contextmanager
def locked_reader(source: Path):
    """On Windows hold read+delete access excluding writers/deleters; POSIX is read-only."""
    if os.name != "nt":
        with source.open("rb") as stream:
            yield stream
        return
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # GENERIC_READ | DELETE; FILE_SHARE_READ only; OPEN_EXISTING.
    handle = kernel.CreateFileW(str(source), 0x80010000, 1, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


def delete_locked_source(stream) -> None:
    """Mark the exact open Windows source for deletion on close; never unlink by path."""
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    disposition = ctypes.c_ubyte(1)
    if not kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(stream.fileno()), 4, ctypes.byref(disposition), 1):
        raise ctypes.WinError(ctypes.get_last_error())


def rename_locked_source(stream, target: Path) -> None:
    """Rename the exact Windows handle without replacement while writers remain excluded."""
    import msvcrt
    from ctypes import wintypes

    class RenameInfo(ctypes.Structure):
        """Variable-length Windows FILE_RENAME_INFO buffer with an absolute target name."""
        _fields_ = [("ReplaceIfExists", wintypes.BOOLEAN), ("RootDirectory", wintypes.HANDLE),
                    ("FileNameLength", wintypes.DWORD), ("FileName", ctypes.c_wchar * (len(str(target).encode("utf-16-le")) // 2 + 1))]

    info = RenameInfo()
    info.ReplaceIfExists = False
    info.FileName = str(target)
    info.FileNameLength = len(str(target).encode("utf-16-le"))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    if not kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(stream.fileno()), 3, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())


def copy_verify_publish(source: Path, target: Path, fingerprint: list[int], record, validate) -> str:
    """Copy across volumes, verify content, publish exclusively, then safely remove source."""
    temporary = target.parent / f".file-sorter-{uuid4().hex}.tmp"
    record("copying", temporary=str(temporary))
    published = False
    try:
        with locked_reader(source) as original:
            if fingerprint_file(source) != fingerprint:
                raise Problem("source_changed", "Source changed since preview.", 409)
            digest = hashlib.sha256()
            with temporary.open("xb") as output:
                while block := original.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            with temporary.open("rb") as check:
                actual = hashlib.file_digest(check, "sha256").hexdigest()
            if temporary.stat().st_size != fingerprint[2] or actual != digest.hexdigest():
                raise OSError("Copy verification failed; original retained.")
            if fingerprint_file(source) != fingerprint:
                raise Problem("source_changed", "Source changed during copy; original retained.", 409)
            shutil.copystat(source, temporary, follow_symlinks=False)
            validate()
            record("publishing", digest=actual)
            publish_no_clobber(temporary, target)
            published = True
            record("published", digest=actual)
            if os.name != "nt":
                # Without a mandatory lock, a concurrent writer cannot be excluded.
                return "copied_source_retained"
            try:
                delete_locked_source(original)
            except OSError:
                return "copied_source_retained"
        return "moved"
    finally:
        # The temporary path is unique to this operation; a published target is never removed.
        if not published and temporary.exists():
            temporary.unlink()


def move_file_safely(action: dict, roots: tuple, state: Path, record) -> str:
    """Revalidate a preview action, transfer without overwrites, and report final outcome."""
    source = resolve_allowed_path(action["source"], roots, state)
    target = resolve_allowed_path(action["destination"], roots, state)

    def validate():
        """Recheck source/destination boundaries and preview fingerprint at transfer boundaries."""
        resolve_allowed_path(source, roots, state)
        resolve_allowed_path(target, roots, state)
        if fingerprint_file(source) != action["fingerprint"]:
            raise Problem("source_changed", "Source changed since preview; create a new preview.", 409)
        if target.exists() or target.is_symlink():
            raise Problem("target_changed", "Destination appeared since preview; create a new preview.", 409)

    validate()
    record("preparing")
    target.parent.mkdir(parents=True, exist_ok=True)
    validate()
    record("moving")
    if os.name != "nt":
        return copy_verify_publish(source, target, action["fingerprint"], record, validate)
    try:
        with locked_reader(source) as stream:
            validate()
            rename_locked_source(stream, target)
        return "moved"
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise
    return copy_verify_publish(source, target, action["fingerprint"], record, validate)
