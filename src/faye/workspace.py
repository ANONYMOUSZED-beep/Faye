from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from faye.capabilities import Capability, CapabilityError, CapabilityRegistry

MAX_SOURCE_BYTES = 262_144
MAX_OUTPUT_CHARS = 65_536


def _workspace_file(root: Path, relative_path: str) -> tuple[Path, str]:
    windows_path = PureWindowsPath(relative_path)
    if (
        not relative_path
        or Path(relative_path).is_absolute()
        or windows_path.drive
        or windows_path.root
        or ":" in relative_path
    ):
        raise CapabilityError("path must be a non-empty workspace-relative path")
    candidate = (root / relative_path).resolve()
    try:
        normalized = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise CapabilityError("path escapes the workspace") from exc
    if not candidate.is_file():
        raise CapabilityError(f"workspace file not found: {relative_path}")
    return candidate, normalized


def build_workspace_capabilities(root: str | Path) -> CapabilityRegistry:
    workspace = Path(root).resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}")
    registry = CapabilityRegistry()

    def read_file(arguments: dict[str, Any]) -> dict[str, Any]:
        path, normalized = _workspace_file(workspace, arguments["path"])
        offset = arguments.get("offset", 1)
        limit = arguments.get("limit", 200)
        if offset < 1:
            raise CapabilityError("invalid arguments for read_file: offset must be positive")
        if not 1 <= limit <= 500:
            raise CapabilityError(
                "invalid arguments for read_file: limit must be between 1 and 500"
            )
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
        except OSError as exc:
            raise CapabilityError(f"workspace file could not be read: {normalized}") from exc
        if len(raw) > MAX_SOURCE_BYTES:
            raise CapabilityError(f"workspace file exceeds {MAX_SOURCE_BYTES} bytes: {normalized}")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise CapabilityError(f"workspace file is not UTF-8 text: {normalized}") from exc
        selected = lines[offset - 1 : offset - 1 + limit]
        content = "\n".join(
            f"{line_number}|{line}"
            for line_number, line in enumerate(selected, start=offset)
        )
        if len(content) > MAX_OUTPUT_CHARS:
            raise CapabilityError(
                f"read_file output exceeds {MAX_OUTPUT_CHARS} characters: {normalized}"
            )
        end_line = offset + len(selected) - 1 if selected else min(offset - 1, len(lines))
        return {
            "path": normalized,
            "start_line": offset,
            "end_line": end_line,
            "total_lines": len(lines),
            "content": content,
        }

    registry.register(
        Capability(
            name="read_file",
            description="Read a bounded range of UTF-8 lines from a file inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=read_file,
        )
    )
    return registry
