import errno
import json
import os
import stat
import threading
from pathlib import Path

import pytest

import faye.workspace as workspace_module
from faye.capabilities import CapabilityError
from faye.workspace import build_workspace_capabilities


@pytest.mark.parametrize("error_number", [errno.ELOOP, errno.ENOTDIR])
def test_posix_nofollow_errors_are_classified_as_workspace_escapes(error_number):
    error = OSError(error_number, "nofollow blocked path")

    with pytest.raises(CapabilityError, match="^path escapes the workspace$"):
        workspace_module._raise_posix_path_escape(error)


def test_workspace_read_file_returns_numbered_bounded_text(tmp_path):
    source = tmp_path / "src" / "demo.py"
    source.parent.mkdir()
    source.write_text("first\nsecond\nthird\n", encoding="utf-8")
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("read_file", {"path": "src/demo.py", "offset": 2, "limit": 1})

    assert output == {
        "path": "src/demo.py",
        "start_line": 2,
        "end_line": 2,
        "total_lines": 3,
        "content": "2|second",
    }


def test_workspace_read_file_rejects_oversized_source_before_returning_content(tmp_path):
    source = tmp_path / "huge.txt"
    source.write_text("x" * 1_000_000, encoding="utf-8")
    registry = build_workspace_capabilities(tmp_path)

    with pytest.raises(CapabilityError, match="file exceeds 262144 bytes"):
        registry.invoke("read_file", {"path": "huge.txt", "limit": 1})


def test_workspace_read_file_rejects_oversized_output(tmp_path):
    source = tmp_path / "long-line.txt"
    source.write_text("x" * 70_000, encoding="utf-8")
    registry = build_workspace_capabilities(tmp_path)

    with pytest.raises(CapabilityError, match="output exceeds 65536 characters"):
        registry.invoke("read_file", {"path": "long-line.txt", "limit": 1})


def test_workspace_read_file_rejects_paths_outside_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    registry = build_workspace_capabilities(workspace)

    with pytest.raises(CapabilityError, match="^path escapes the workspace$"):
        registry.invoke("read_file", {"path": "../secret.txt"})

    with pytest.raises(
        CapabilityError, match="^path must be a non-empty workspace-relative path$"
    ):
        registry.invoke("read_file", {"path": str(outside.resolve())})


def test_workspace_read_file_rejects_windows_drive_and_stream_paths(tmp_path):
    registry = build_workspace_capabilities(tmp_path)

    for path in ("C:relative.txt", "safe.txt:stream", r"\Windows\win.ini"):
        with pytest.raises(
            CapabilityError, match="^path must be a non-empty workspace-relative path$"
        ):
            registry.invoke("read_file", {"path": path})


def test_workspace_read_file_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    registry = build_workspace_capabilities(workspace)

    with pytest.raises(CapabilityError, match="^path escapes the workspace$"):
        registry.invoke("read_file", {"path": "link.txt"})


def test_workspace_read_file_rejects_non_utf8_data(tmp_path):
    source = tmp_path / "binary.dat"
    source.write_bytes(b"\xff\xfe")
    registry = build_workspace_capabilities(tmp_path)

    with pytest.raises(CapabilityError, match="workspace file is not UTF-8 text"):
        registry.invoke("read_file", {"path": "binary.dat"})


def test_workspace_search_text_returns_bounded_workspace_matches(tmp_path):
    source = tmp_path / "src" / "demo.py"
    source.parent.mkdir()
    source.write_text("alpha\nneedle one\nneedle two\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("needle ignored\n", encoding="utf-8")
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke(
        "search_text",
        {"query": "needle", "path": "src", "file_glob": "*.py", "limit": 1},
    )

    assert output == {
        "matches": [{"path": "src/demo.py", "line": 2, "text": "needle one"}],
        "truncated": True,
    }


def test_workspace_search_text_rejects_symlink_directory_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle", encoding="utf-8")
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")
    registry = build_workspace_capabilities(workspace)

    with pytest.raises(CapabilityError, match="^path escapes the workspace$"):
        registry.invoke("search_text", {"query": "needle", "path": "linked"})


def test_workspace_search_text_stops_at_aggregate_file_budget(tmp_path, monkeypatch):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_SEARCH_FILES", 1, raising=False)
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert len(output["matches"]) == 1
    assert output["truncated"] is True


def test_workspace_search_processes_all_candidates_acquired_before_entry_limit(
    tmp_path, monkeypatch
):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_SEARCH_ENTRIES", 2)
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert [match["path"] for match in output["matches"]] == ["0.txt", "1.txt"]
    assert output["truncated"] is True


def test_workspace_search_text_stops_at_aggregate_byte_budget(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_SEARCH_TOTAL_BYTES", 8, raising=False)
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert len(output["matches"]) == 1
    assert output["truncated"] is True


def test_workspace_search_text_bounds_each_match_and_aggregate_output(tmp_path):
    (tmp_path / "large.txt").write_text(
        ("needle" + "x" * 30_000 + "\n") * 4,
        encoding="utf-8",
    )
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert output["truncated"] is True
    assert all(
        len(match["text"]) <= workspace_module.MAX_SEARCH_MATCH_CHARS
        for match in output["matches"]
    )
    assert len(json.dumps(output["matches"])) <= workspace_module.MAX_OUTPUT_CHARS


def test_workspace_write_file_is_not_registered_by_default(tmp_path):
    registry = build_workspace_capabilities(tmp_path)

    with pytest.raises(CapabilityError, match="^unknown capability: write_file$"):
        registry.invoke("write_file", {"path": "result.txt", "content": "done"})


def test_workspace_write_file_atomically_replaces_utf8_file_when_enabled(tmp_path):
    target = tmp_path / "src" / "result.txt"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    registry = build_workspace_capabilities(tmp_path, allow_writes=True)

    output = registry.invoke(
        "write_file",
        {"path": "src/result.txt", "content": "new value\n"},
    )

    assert output == {"path": "src/result.txt", "bytes_written": 10, "created": False}
    assert target.read_text(encoding="utf-8") == "new value\n"
    assert list(target.parent.glob(".faye-write-*")) == []


def test_workspace_write_file_rejects_symlink_parent_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")
    registry = build_workspace_capabilities(workspace, allow_writes=True)

    with pytest.raises(CapabilityError, match="^path escapes the workspace$"):
        registry.invoke(
            "write_file",
            {"path": "linked/escaped.txt", "content": "must not escape"},
        )

    assert not (outside / "escaped.txt").exists()


def test_workspace_write_cleanup_failure_does_not_mask_original_error(tmp_path, monkeypatch):
    registry = build_workspace_capabilities(tmp_path, allow_writes=True)

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    def fail_cleanup(self, *args, **kwargs):
        raise PermissionError("cleanup failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    with pytest.raises(CapabilityError, match="workspace file could not be written") as error:
        registry.invoke("write_file", {"path": "result.txt", "content": "new"})

    assert str(error.value.__cause__) == "replace failed"


def test_posix_descriptor_cleanup_attempts_every_close_without_raising(monkeypatch):
    calls = []

    def fail_close(descriptor):
        calls.append(descriptor)
        raise OSError("close failed")

    monkeypatch.setattr(os, "close", fail_close)

    workspace_module._close_posix_descriptors(10, None, 11, 12)

    assert calls == [10, 11, 12]


def test_posix_write_cleanup_attempts_every_resource_without_raising(monkeypatch):
    calls = []

    def fail_close(descriptor):
        calls.append(("close", descriptor))
        raise OSError("close failed")

    def fail_unlink(name, *, dir_fd):
        calls.append(("unlink", name, dir_fd))
        raise OSError("unlink failed")

    monkeypatch.setattr(os, "close", fail_close)
    monkeypatch.setattr(os, "unlink", fail_unlink)

    workspace_module._cleanup_posix_write(10, 11, ".faye-write-test")

    assert calls == [
        ("close", 11),
        ("unlink", ".faye-write-test", 10),
        ("close", 10),
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-handle race regression")
def test_workspace_read_file_resists_parent_symlink_swap(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    safe = workspace / "safe"
    outside = tmp_path / "outside"
    safe.mkdir(parents=True)
    outside.mkdir()
    (safe / "data.txt").write_text("inside", encoding="utf-8")
    (outside / "data.txt").write_text("outside secret", encoding="utf-8")
    registry = build_workspace_capabilities(workspace)
    original_open = os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "data.txt" and dir_fd is not None and not swapped:
            swapped = True
            safe.rename(workspace / "moved-safe")
            safe.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)

    output = registry.invoke("read_file", {"path": "safe/data.txt"})

    assert output["content"] == "1|inside"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-handle race regression")
def test_workspace_write_file_resists_parent_symlink_swap(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    safe = workspace / "safe"
    outside = tmp_path / "outside"
    safe.mkdir(parents=True)
    outside.mkdir()
    registry = build_workspace_capabilities(workspace, allow_writes=True)
    original_replace = os.replace
    swapped = False

    def swapping_replace(source, destination, *args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            safe.rename(workspace / "moved-safe")
            safe.symlink_to(outside, target_is_directory=True)
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", swapping_replace)

    registry.invoke("write_file", {"path": "safe/result.txt", "content": "inside"})

    assert not (outside / "result.txt").exists()
    assert (workspace / "moved-safe" / "result.txt").read_text(encoding="utf-8") == "inside"


def test_workspace_search_charges_oversized_reads_to_byte_budget(tmp_path, monkeypatch):
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x" * 20, encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_SOURCE_BYTES", 4)
    monkeypatch.setattr(workspace_module, "MAX_SEARCH_TOTAL_BYTES", 4)
    original_read = workspace_module._read_workspace_bytes
    reads = 0

    def counted_read(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(workspace_module, "_read_workspace_bytes", counted_read)
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert output["truncated"] is True
    assert reads == 1


def test_workspace_search_exact_file_limit_is_not_truncated(tmp_path, monkeypatch):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("needle", encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_SEARCH_FILES", 3)
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert [match["path"] for match in output["matches"]] == [
        "0.txt",
        "1.txt",
        "2.txt",
    ]
    assert output["truncated"] is False


def test_workspace_search_bounds_utf8_serialized_envelope(tmp_path, monkeypatch):
    (tmp_path / "unicode.txt").write_text("needle" + "é" * 200, encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_OUTPUT_CHARS", 120)
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    serialized = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(serialized) <= workspace_module.MAX_OUTPUT_CHARS
    assert output["truncated"] is True


def test_workspace_search_stops_consuming_directory_at_entry_budget(tmp_path, monkeypatch):
    for index in range(10):
        (tmp_path / f"{index}.txt").write_text("needle", encoding="utf-8")
    monkeypatch.setattr(workspace_module, "MAX_SEARCH_ENTRIES", 1)
    original_scandir = os.scandir
    consumed = 0

    class BoundedIterator:
        def __init__(self, iterator):
            self.iterator = iterator

        def __enter__(self):
            self.iterator.__enter__()
            return self

        def __exit__(self, *args):
            return self.iterator.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal consumed
            consumed += 1
            if consumed > 2:
                raise AssertionError("search consumed beyond its entry budget")
            return next(self.iterator)

    monkeypatch.setattr(os, "scandir", lambda path: BoundedIterator(original_scandir(path)))
    registry = build_workspace_capabilities(tmp_path)

    output = registry.invoke("search_text", {"query": "needle", "limit": 100})

    assert output["truncated"] is True
    assert consumed == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX root-handle race regression")
def test_workspace_read_resists_workspace_root_symlink_swap(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "data.txt").write_text("inside", encoding="utf-8")
    (outside / "data.txt").write_text("outside secret", encoding="utf-8")
    registry = build_workspace_capabilities(workspace)
    workspace.rename(tmp_path / "moved-workspace")
    workspace.symlink_to(outside, target_is_directory=True)

    output = registry.invoke("read_file", {"path": "data.txt"})

    assert output["content"] == "1|inside"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-lock regression")
def test_windows_directory_lock_requests_delete_without_share_delete():
    assert workspace_module._WINDOWS_DIRECTORY_ACCESS == 0x000100C1
    assert workspace_module._WINDOWS_DIRECTORY_SHARE == 0x00000003


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-handle regression")
def test_windows_directory_handle_rejects_reparse_point(tmp_path):
    target = tmp_path / "target"
    link = tmp_path / "link"
    target.mkdir()
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(CapabilityError, match="path escapes the workspace"):
        workspace_module._open_windows_directory_handle(link)


@pytest.mark.skipif(os.name != "nt", reason="Windows metadata regression")
def test_windows_write_preserves_existing_readonly_mode(tmp_path):
    target = tmp_path / "result.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(stat.S_IREAD)
    registry = build_workspace_capabilities(tmp_path, allow_writes=True)
    try:
        registry.invoke("write_file", {"path": "result.txt", "content": "new"})
        assert stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE == 0
        assert target.read_text(encoding="utf-8") == "new"
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="Windows metadata regression")
def test_windows_replace_failure_restores_destination_readonly_mode(tmp_path):
    target = tmp_path / "result.txt"
    missing_replacement = tmp_path / "missing.tmp"
    target.write_text("old", encoding="utf-8")
    target.chmod(stat.S_IREAD)
    try:
        with pytest.raises(OSError):
            workspace_module._replace_windows_file(missing_replacement, target)
        assert stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE == 0
        assert target.read_text(encoding="utf-8") == "old"
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-lock regression")
def test_windows_write_blocks_parent_path_swap_until_replace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    safe = workspace / "safe"
    outside = tmp_path / "outside"
    safe.mkdir(parents=True)
    outside.mkdir()
    registry = build_workspace_capabilities(workspace, allow_writes=True)
    original_replace = os.replace
    rename_started = threading.Event()
    rename_finished = threading.Event()
    rename_errors = []

    def competing_rename():
        rename_started.set()
        try:
            safe.rename(workspace / "moved-safe")
        except OSError as exc:
            rename_errors.append(exc)
        finally:
            rename_finished.set()

    def swapping_replace(source, destination, *args, **kwargs):
        thread = threading.Thread(target=competing_rename)
        thread.start()
        assert rename_started.wait(timeout=2)
        assert rename_finished.wait(timeout=2)
        thread.join(timeout=2)
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", swapping_replace)
    registry.invoke("write_file", {"path": "safe/result.txt", "content": "inside"})

    assert len(rename_errors) == 1
    assert isinstance(rename_errors[0], PermissionError)
    assert not (outside / "result.txt").exists()
    assert (safe / "result.txt").read_text(encoding="utf-8") == "inside"
