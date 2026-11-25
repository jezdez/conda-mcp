"""Safe, bounded file primitives for local client state."""

from __future__ import annotations

import errno
import json
import os
import secrets
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from conda.common.compat import on_win

if on_win:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _OPEN_ALWAYS = 4
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_TYPE_DISK = 0x0001

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    _kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    _kernel32.GetFileType.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build an unambiguous JSON object or reject duplicate keys."""
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON key")
    return result


def _constant(value: str) -> None:
    """Reject nonfinite values, which are not JSON."""
    raise ValueError(f"invalid JSON constant: {value}")


def _redirected(info: os.stat_result) -> bool:
    """Return whether a directory entry is a link or Windows reparse point."""
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def read_bytes(
    path: Path, *, limit: int = 1_048_576, missing_ok: bool = False
) -> bytes | None:
    """Read one bounded regular file without following redirected components."""
    if limit < 0:
        raise ValueError("size limit must be non-negative")
    if on_win:
        return _read_windows(path, limit, missing_ok)
    try:
        parent, name, bindings = _open_parent(path)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    try:
        _check_bindings(bindings)
        return _read_descriptor(parent, name, limit, missing_ok)
    finally:
        os.close(parent)


def load_json(raw: bytes) -> dict[str, object]:
    """Decode one strict UTF-8 JSON object without exposing input contents."""
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
        )
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid UTF-8 JSON.") from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object.")
    return value


def atomic_write(
    path: Path, data: bytes, expected: bytes | None, *, limit: int = 1_048_576
) -> None:
    """Atomically replace a file when its current bytes still equal expected."""
    if len(data) > limit or expected is not None and len(expected) > limit:
        raise ValueError("File exceeds size limit.")
    if on_win:
        _atomic_write_windows(path, data, expected, limit)
        return
    parent, name, bindings = _open_parent(path)
    try:
        _atomic_write_descriptor(parent, name, data, expected, limit, bindings)
    finally:
        os.close(parent)


@contextmanager
def open_lock(path: Path) -> Generator[BinaryIO]:
    """Open a private binary regular lock file without replacing its inode."""
    parents: list[int] = []
    if on_win:
        try:
            parents = _open_windows_parents(path, create=True)
            descriptor = _windows_fd(path, _GENERIC_READ | _GENERIC_WRITE, _OPEN_ALWAYS)
        except BaseException:
            _close_windows(parents)
            raise
    else:
        parent, name, bindings = _create_parents(path)
        try:
            _check_bindings(bindings)
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                0o600,
                dir_fd=parent,
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ValueError("Unsafe redirected path.") from exc
            raise
        finally:
            os.close(parent)
    try:
        if on_win:
            info = _windows_info(msvcrt.get_osfhandle(descriptor))
            if info.nNumberOfLinks != 1:
                raise ValueError("Unsafe lock file.")
        if not on_win:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Unsafe lock file.")
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r+b", closefd=True) as stream:
            yield stream
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if on_win:
            _close_windows(parents)


def _open_parent(path: Path) -> tuple[int, str, list[tuple[Path, os.stat_result]]]:
    """Anchor every existing POSIX parent and retain pathname identities."""
    if on_win:
        raise RuntimeError("POSIX descriptor operations are unavailable on Windows.")
    if ".." in path.parts or not path.is_absolute() or len(path.parts) < 2:
        raise ValueError("Unsafe path traversal.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    bindings: list[tuple[Path, os.stat_result]] = [
        (Path(path.anchor), os.fstat(descriptor))
    ]
    current = Path(path.anchor)
    try:
        for part in path.parts[1:-1]:
            current /= part
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            bindings.append((current, os.fstat(descriptor)))
        return descriptor, path.name, bindings
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError("Unsafe redirected path.") from exc
        raise


def _check_bindings(bindings: list[tuple[Path, os.stat_result]]) -> None:
    """Reject an ancestor renamed or redirected after it was anchored."""
    for path, anchored in bindings:
        try:
            current = os.lstat(path)
        except OSError as exc:
            raise ValueError("File changed during the operation.") from exc
        if _redirected(current) or (current.st_dev, current.st_ino) != (
            anchored.st_dev,
            anchored.st_ino,
        ):
            raise ValueError("File changed during the operation.")


def _create_parents(path: Path) -> tuple[int, str, list[tuple[Path, os.stat_result]]]:
    """Create POSIX parents relative to verified directory descriptors."""
    if on_win:
        raise RuntimeError("POSIX descriptor operations are unavailable on Windows.")
    if ".." in path.parts or not path.is_absolute() or len(path.parts) < 2:
        raise ValueError("Unsafe path traversal.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    bindings: list[tuple[Path, os.stat_result]] = [
        (Path(path.anchor), os.fstat(descriptor))
    ]
    current = Path(path.anchor)
    try:
        for part in path.parts[1:-1]:
            current /= part
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            bindings.append((current, os.fstat(descriptor)))
        return descriptor, path.name, bindings
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError("Unsafe redirected path.") from exc
        raise


def _read_descriptor(
    parent: int, name: str, limit: int, missing_ok: bool
) -> bytes | None:
    """Read a bounded regular leaf relative to an anchored parent."""
    if on_win:
        raise RuntimeError("POSIX descriptor operations are unavailable on Windows.")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError("Unsafe redirected path.") from exc
        raise
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("Unsafe non-regular file.")
    with os.fdopen(descriptor, "rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("File exceeds size limit.")
    return value


def _read_windows(path: Path, limit: int, missing_ok: bool) -> bytes | None:
    """Read a Windows leaf while every existing parent is pinned."""
    try:
        parents = _open_windows_parents(path, create=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    try:
        try:
            descriptor = _windows_fd(path, _GENERIC_READ, _OPEN_EXISTING)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("Unsafe non-regular file.")
        with os.fdopen(descriptor, "rb") as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError("File exceeds size limit.")
        return value
    finally:
        _close_windows(parents)


def _windows_path(path: Path) -> Path:
    """Reject Windows device paths, streams, traversal, and bare roots."""
    absolute = path.absolute()
    if ".." in path.parts or len(absolute.parts) < 2:
        raise ValueError("Unsafe path traversal.")
    text = str(absolute)
    if text.startswith("\\\\.\\") or text.startswith("\\\\?\\"):
        raise ValueError("Unsafe path traversal.")
    if any(":" in part for part in absolute.parts[1:]):
        raise ValueError("Unsafe path traversal.")
    return absolute


def _windows_info(handle: int):
    """Return Windows handle information or raise the native error."""
    info = _ByHandleFileInformation()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info


def _windows_fd(path: Path, access: int, creation: int) -> int:
    """Open one non-reparse Windows leaf and return a non-inheritable fd."""
    handle = _kernel32.CreateFileW(
        str(path),
        access,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        creation,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            raise FileNotFoundError(error, os.strerror(error), path)
        raise ctypes.WinError(error)
    descriptor: int | None = None
    try:
        info = _windows_info(handle)
        if (
            info.dwFileAttributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or _kernel32.GetFileType(handle) != _FILE_TYPE_DISK
        ):
            raise ValueError("Unsafe redirected path.")
        descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY)
        if descriptor < 0:
            descriptor = None
            raise OSError(ctypes.get_last_error(), "open_osfhandle")
        os.set_inheritable(descriptor, False)
        return descriptor
    except BaseException:
        if descriptor is None:
            _kernel32.CloseHandle(handle)
        else:
            os.close(descriptor)
        raise


def _open_windows_parents(path: Path, *, create: bool) -> list[int]:
    """Pin every Windows parent without delete sharing before leaf access."""
    absolute = _windows_path(path)
    handles: list[int] = []
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:-1]:
            current /= part
            while True:
                handle = _kernel32.CreateFileW(
                    str(current),
                    _GENERIC_READ,
                    _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                    None,
                    _OPEN_EXISTING,
                    _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
                    None,
                )
                if handle != wintypes.HANDLE(-1).value:
                    break
                error = ctypes.get_last_error()
                if not create or error not in {2, 3}:
                    if error in {2, 3}:
                        raise FileNotFoundError(error, os.strerror(error), current)
                    raise ctypes.WinError(error)
                try:
                    current.mkdir(mode=0o700)
                except FileExistsError:
                    pass
            try:
                info = _windows_info(handle)
                if (
                    info.dwFileAttributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or not info.dwFileAttributes & stat.FILE_ATTRIBUTE_DIRECTORY
                    or _kernel32.GetFileType(handle) != _FILE_TYPE_DISK
                ):
                    raise ValueError("Unsafe redirected path.")
                handles.append(handle)
            except BaseException:
                _kernel32.CloseHandle(handle)
                raise
        return handles
    except BaseException:
        _close_windows(handles)
        raise


def _close_windows(handles: list[int]) -> None:
    """Close all Windows parent handles after a pinned operation."""
    for handle in reversed(handles):
        _kernel32.CloseHandle(handle)


def _atomic_write_descriptor(
    parent: int,
    name: str,
    data: bytes,
    expected: bytes | None,
    limit: int,
    bindings: list[tuple[Path, os.stat_result]],
) -> None:
    """Replace a leaf through an anchored POSIX directory descriptor."""
    if on_win:
        raise RuntimeError("POSIX descriptor operations are unavailable on Windows.")
    previous = _read_descriptor(parent, name, limit, True)
    if previous != expected:
        raise ValueError("File changed during the operation.")
    mode = (
        stat.S_IMODE(os.stat(name, dir_fd=parent).st_mode)
        if previous is not None
        else 0o600
    )
    temporary = f".{name}.{secrets.token_hex(16)}"
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
    )
    try:
        try:
            os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        _check_bindings(bindings)
        if _read_descriptor(parent, name, limit, True) != expected:
            raise ValueError("File changed during the operation.")
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def _atomic_write_windows(
    path: Path, data: bytes, expected: bytes | None, limit: int
) -> None:
    """Replace a Windows leaf while its ancestors are pinned against renames."""
    parents = _open_windows_parents(path, create=False)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}")
    try:
        previous = _read_windows(path, limit, True)
        if previous != expected:
            raise ValueError("File changed during the operation.")
        mode = stat.S_IMODE(path.stat().st_mode) if previous is not None else 0o600
        descriptor = _windows_fd(temporary, _GENERIC_WRITE, _CREATE_NEW)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        os.chmod(temporary, mode)
        if _read_windows(path, limit, True) != expected:
            raise ValueError("File changed during the operation.")
        os.replace(temporary, path)
    finally:
        _close_windows(parents)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
