from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from conda.common.compat import on_win

from conda_mcp import files
from conda_mcp.files import atomic_write, load_json, open_lock, read_bytes


def test_read_bytes_reads_regular_file_and_enforces_limit(tmp_path: Path):
    path = tmp_path / "data.json"
    path.write_bytes(b"{}")

    assert read_bytes(path) == b"{}"
    with pytest.raises(ValueError, match="size limit"):
        read_bytes(path, limit=1)
    assert read_bytes(tmp_path / "absent", missing_ok=True) is None


def test_read_bytes_allows_a_missing_parent_when_missing_is_allowed(tmp_path: Path):
    assert read_bytes(tmp_path / "absent" / "file", missing_ok=True) is None


@pytest.mark.parametrize("missing_ok", [False, True])
def test_read_bytes_rejects_a_regular_file_parent(tmp_path: Path, missing_ok: bool):
    parent = tmp_path / "parent"
    parent.write_bytes(b"original")

    with pytest.raises(ValueError, match="Unsafe"):
        read_bytes(parent / "config.json", missing_ok=missing_ok)
    assert parent.read_bytes() == b"original"


def test_read_and_write_bounds_preserve_original_file(tmp_path):
    path = tmp_path / "data"
    path.write_bytes(b"original")
    with pytest.raises(ValueError, match="non-negative"):
        read_bytes(path, limit=-1)
    with pytest.raises(ValueError, match="size"):
        atomic_write(path, b"too large", b"original", limit=3)
    assert path.read_bytes() == b"original"
    with pytest.raises(FileNotFoundError):
        read_bytes(tmp_path / "missing" / "data")


def test_special_files_cannot_be_read_as_regular_files(tmp_path):
    if on_win:
        with pytest.raises((OSError, ValueError)):
            read_bytes(tmp_path)
    else:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match="non-regular"):
            read_bytes(fifo)
        with pytest.raises(ValueError, match="non-regular"):
            read_bytes(tmp_path)


def test_read_bytes_rejects_redirected_leaf(tmp_path: Path):
    target = tmp_path / "target"
    target.write_bytes(b"{}")
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="Unsafe"):
        read_bytes(link)


def test_load_json_rejects_duplicate_keys_and_nonfinite_values():
    assert load_json(b'{"name":"example"}') == {"name": "example"}
    with pytest.raises(ValueError, match="duplicate"):
        load_json(b'{"name":"one","name":"two"}')
    with pytest.raises(ValueError, match="constant"):
        load_json(b'{"number":NaN}')
    with pytest.raises(ValueError, match="UTF-8"):
        load_json(b"\xff")


@pytest.mark.parametrize(
    "raw", [b'{// comment\n"name":"example",}', b'{"name":"example"/* comment */}']
)
def test_load_json_rejects_comments_and_trailing_commas(raw: bytes):
    with pytest.raises(ValueError):
        load_json(raw)


@pytest.mark.skipif(on_win, reason="POSIX permission bits")
def test_atomic_write_checks_expected_and_preserves_permissions(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_bytes(b"old")
    path.chmod(0o640)

    atomic_write(path, b"new", b"old")

    assert path.read_bytes() == b"new"
    assert path.stat().st_mode & 0o777 == 0o640
    with pytest.raises(ValueError, match="changed"):
        atomic_write(path, b"newer", b"old")


def test_atomic_write_creates_only_a_missing_leaf_when_expected_is_none(tmp_path: Path):
    path = tmp_path / "new.json"

    atomic_write(path, b"{}", None)

    assert path.read_bytes() == b"{}"


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_atomic_write_failure_preserves_original_and_removes_staging(
    tmp_path, monkeypatch, operation
):
    path = tmp_path / "config.json"
    path.write_bytes(b"original")
    error = OSError("injected write failure")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(files.os, operation, fail)
    with pytest.raises(OSError) as caught:
        atomic_write(path, b"new", b"original")
    assert caught.value is error
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_write_preserves_a_concurrent_edit_after_staging(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_bytes(b"original")
    fsync = os.fsync

    def edit_during_flush(fd):
        path.write_bytes(b"concurrent edit")
        fsync(fd)

    monkeypatch.setattr(files.os, "fsync", edit_during_flush)
    with pytest.raises(ValueError, match="changed"):
        atomic_write(path, b"new", b"original")
    assert path.read_bytes() == b"concurrent edit"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(on_win, reason="Windows pins parent directories against renames")
def test_atomic_write_rejects_a_disappearing_parent(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    path = parent / "config.json"
    path.write_bytes(b"original")
    moved = tmp_path / "moved"
    fsync = os.fsync

    def move_during_flush(fd):
        parent.rename(moved)
        fsync(fd)

    monkeypatch.setattr(files.os, "fsync", move_during_flush)
    with pytest.raises(ValueError, match="changed"):
        atomic_write(path, b"new", b"original")
    assert not parent.exists()
    assert (moved / "config.json").read_bytes() == b"original"
    assert list(moved.iterdir()) == [moved / "config.json"]


@pytest.mark.skipif(on_win, reason="POSIX permission bits")
def test_atomic_write_preserves_mode_despite_a_permissive_umask(tmp_path: Path):
    path = tmp_path / "config.json"
    previous = os.umask(0)
    try:
        atomic_write(path, b"{}", None)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_file_operations_reject_path_traversal(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsafe"):
        read_bytes(tmp_path / "directory" / ".." / "file", missing_ok=True)


@pytest.mark.skipif(on_win, reason="POSIX descriptor race")
def test_read_bytes_uses_anchored_parent_after_a_real_parent_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    directory = tmp_path / "config"
    directory.mkdir()
    safe = directory / "settings.json"
    safe.write_bytes(b"safe")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "settings.json").write_bytes(b"outside")

    original = os.open
    swapped = False

    def swap(path, *args, **kwargs):
        nonlocal swapped
        result = original(path, *args, **kwargs)
        if not swapped and path == directory.name:
            directory.rename(tmp_path / "old-config")
            directory.symlink_to(outside, target_is_directory=True)
            swapped = True
        return result

    monkeypatch.setattr(os, "open", swap)

    with pytest.raises(ValueError, match="changed"):
        read_bytes(safe)
    assert swapped


@pytest.mark.skipif(on_win, reason="POSIX descriptor race")
def test_atomic_write_rejects_parent_path_replaced_after_anchoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    directory = tmp_path / "config"
    directory.mkdir()
    settings = directory / "settings.json"
    settings.write_bytes(b"old")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "settings.json").write_bytes(b"outside")

    original = os.open
    swapped = False

    def swap(path, *args, **kwargs):
        nonlocal swapped
        result = original(path, *args, **kwargs)
        if not swapped and path == directory.name:
            directory.rename(tmp_path / "old-config")
            directory.symlink_to(outside, target_is_directory=True)
            swapped = True
        return result

    monkeypatch.setattr(os, "open", swap)

    with pytest.raises(ValueError, match="changed"):
        atomic_write(settings, b"new", b"old")

    assert swapped
    assert (tmp_path / "old-config/settings.json").read_bytes() == b"old"
    assert (outside / "settings.json").read_bytes() == b"outside"


@pytest.mark.skipif(on_win, reason="POSIX permission bits")
def test_open_lock_creates_missing_parents_and_regular_private_leaf(tmp_path: Path):
    path = tmp_path / "nested" / "state.lock"

    with open_lock(path) as lock:
        lock.write(b"locked")

    assert path.read_bytes() == b"locked"


@pytest.mark.skipif(on_win, reason="POSIX descriptor parent creation")
def test_open_lock_accepts_parent_created_by_another_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nested" / "state.lock"
    mkdir = os.mkdir
    raced = False

    def create_first(name: str, mode: int = 0o777, *, dir_fd: int | None = None):
        nonlocal raced
        if name == "nested" and dir_fd is not None and not raced:
            raced = True
            mkdir(name, mode, dir_fd=dir_fd)
            raise FileExistsError("another writer created the directory")
        return mkdir(name, mode, dir_fd=dir_fd)

    monkeypatch.setattr(files.os, "mkdir", create_first)

    with open_lock(path):
        pass

    assert raced
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(on_win, reason="POSIX permission bits")
def test_open_lock_creates_private_leaf_despite_a_permissive_umask(tmp_path: Path):
    path = tmp_path / "state.lock"
    previous = os.umask(0)
    try:
        with open_lock(path):
            pass
    finally:
        os.umask(previous)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_open_lock_rejects_a_redirected_parent_before_creating_it(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = tmp_path / "redirected"
    redirected.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Unsafe"):
        with open_lock(redirected / "nested" / "state.lock"):
            pass

    assert not (outside / "nested").exists()


def test_open_lock_rejects_redirected_leaf_and_hardlinked_lock(tmp_path: Path):
    target = tmp_path / "target"
    target.write_bytes(b"x")
    original_mode = stat.S_IMODE(target.stat().st_mode)
    link = tmp_path / "state.lock"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="Unsafe"):
        with open_lock(link):
            pass
    hardlink = tmp_path / "hard.lock"
    os.link(target, hardlink)
    with pytest.raises(ValueError, match="Unsafe"):
        with open_lock(hardlink):
            pass
    if on_win:
        assert target.read_bytes() == hardlink.read_bytes() == b"x"
        assert target.stat().st_nlink == 2
    else:
        assert stat.S_IMODE(target.stat().st_mode) == original_mode


@pytest.mark.skipif(on_win, reason="mkfifo is unavailable on Windows")
def test_open_lock_rejects_a_fifo_without_blocking(tmp_path: Path):
    path = tmp_path / "state.lock"
    os.mkfifo(path)

    with pytest.raises(ValueError, match="Unsafe"):
        with open_lock(path):
            pass


@pytest.mark.skipif(on_win, reason="fchmod is unavailable on Windows")
def test_open_lock_closes_descriptor_when_fchmod_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "state.lock"
    closed: list[int] = []
    original_close = os.close

    def fail_fchmod(descriptor: int, mode: int) -> None:
        raise OSError("permission denied")

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(os, "fchmod", fail_fchmod)
    monkeypatch.setattr(os, "close", record_close)

    with pytest.raises(OSError, match="permission"):
        with open_lock(path):
            pass

    assert len(closed) >= 2


@pytest.mark.skipif(on_win, reason="fchmod is unavailable on Windows")
def test_atomic_write_closes_staged_descriptor_when_fchmod_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "config.json"
    staged: list[int] = []
    original_close = os.close
    original_open = os.open

    def fail_fchmod(descriptor: int, mode: int) -> None:
        raise OSError("permission denied")

    def record_close(descriptor: int) -> None:
        original_close(descriptor)

    def record_open(name, flags, *args, **kwargs):
        descriptor = original_open(name, flags, *args, **kwargs)
        if flags & os.O_EXCL:
            staged.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "fchmod", fail_fchmod)
    monkeypatch.setattr(os, "close", record_close)
    monkeypatch.setattr(os, "open", record_open)

    with pytest.raises(OSError, match="permission"):
        atomic_write(path, b"{}", None)

    assert len(staged) == 1
    with pytest.raises(OSError):
        os.fstat(staged[0])
    assert not list(tmp_path.glob(".config.json.*"))


@pytest.mark.skipif(not on_win, reason="requires native Windows handles")
def test_windows_file_operations_reject_device_namespaces(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsafe"):
        read_bytes(Path(r"\\.\NUL"), missing_ok=True)


@pytest.mark.skipif(not on_win, reason="requires native Windows handles")
def test_windows_read_allows_missing_parent_when_missing_is_allowed(tmp_path: Path):
    assert read_bytes(tmp_path / "absent" / "file", missing_ok=True) is None


@pytest.mark.skipif(not on_win, reason="requires native Windows handles")
def test_windows_lock_keeps_parent_handles_open_until_the_lock_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    closed: list[int] = []
    original_close = files._close_windows

    def record_close(handles: list[int]) -> None:
        closed.extend(handles)
        original_close(handles)

    monkeypatch.setattr(files, "_close_windows", record_close)
    with open_lock(tmp_path / "nested" / "state.lock"):
        assert not closed
    assert closed


@pytest.mark.skipif(not on_win, reason="requires native Windows handles")
def test_windows_create_file_signature_and_descriptor_are_safe(tmp_path: Path):
    assert len(files._kernel32.CreateFileW.argtypes) == 7
    descriptor = files._windows_fd(
        tmp_path / "state.lock", files._GENERIC_WRITE, files._CREATE_NEW
    )
    try:
        assert not os.get_inheritable(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.skipif(not on_win, reason="requires native Windows junctions")
def test_windows_file_operations_reject_junction_parent(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True
    )

    with pytest.raises(ValueError, match="Unsafe"):
        read_bytes(junction / "file", missing_ok=True)
