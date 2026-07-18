import pytest

from faye.capabilities import CapabilityError
from faye.workspace import build_workspace_capabilities


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
