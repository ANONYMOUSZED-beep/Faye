from __future__ import annotations

import ctypes
import errno
import json
import os
import secrets
import stat
import tempfile
import weakref
from contextlib import suppress
from pathlib import Path, PureWindowsPath
from typing import Any

from faye.capabilities import Capability, CapabilityError, CapabilityRegistry

MAX_SOURCE_BYTES = 262_144
MAX_OUTPUT_CHARS = 65_536
MAX_WRITE_BYTES = 262_144
MAX_SEARCH_ENTRIES = 10_000
MAX_SEARCH_FILES = 256
MAX_SEARCH_TOTAL_BYTES = 8 * 1024 * 1024
MAX_SEARCH_MATCH_CHARS = 4_096


def _relative_parts(relative_path: str, *, allow_root: bool = False) -> tuple[str, ...]:
    windows_path = PureWindowsPath(relative_path)
    if (
        not relative_path
        or Path(relative_path).is_absolute()
        or windows_path.drive
        or windows_path.root
        or ":" in relative_path
    ):
        raise CapabilityError("path must be a non-empty workspace-relative path")
    parts = Path(relative_path).parts
    if any(part == ".." for part in parts):
        raise CapabilityError("path escapes the workspace")
    parts = tuple(part for part in parts if part not in ("", "."))
    if not parts and not allow_root:
        raise CapabilityError("path must be a non-empty workspace-relative path")
    return parts


def _workspace_path(
    root: Path, relative_path: str, *, allow_root: bool = False
) -> tuple[Path, str]:
    parts = _relative_parts(relative_path, allow_root=allow_root)
    candidate = (root.joinpath(*parts)).resolve()
    try:
        normalized = candidate.relative_to(root).as_posix() or "."
    except ValueError as exc:
        raise CapabilityError("path escapes the workspace") from exc
    return candidate, normalized


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _reject_reparse_components(root: Path, parts: tuple[str, ...]) -> None:
    current = root
    for part in parts:
        current = current / part
        if not current.exists() and not current.is_symlink():
            break
        if _is_reparse_or_symlink(current):
            raise CapabilityError("path escapes the workspace")


def _verify_windows_handle(stream: Any, root: Path) -> None:
    if os.name != "nt":
        return
    import msvcrt

    handle = msvcrt.get_osfhandle(stream.fileno())
    buffer = ctypes.create_unicode_buffer(32_768)
    get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    length = get_final_path(handle, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise OSError("could not resolve opened workspace handle")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    try:
        Path(value).resolve().relative_to(root)
    except ValueError as exc:
        raise CapabilityError("path escapes the workspace") from exc


class _ReadLimitExceeded(OSError):
    """Raised before a bounded operation reads past its remaining budget."""


def _raise_posix_path_escape(exc: OSError) -> None:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise CapabilityError("path escapes the workspace") from exc


_WINDOWS_DIRECTORY_ACCESS = 0x0001 | 0x0040 | 0x0080 | 0x00010000
_WINDOWS_DIRECTORY_SHARE = 0x0001 | 0x0002
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WINDOWS_FILE_ATTRIBUTE_READONLY = 0x00000001
_WINDOWS_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def _windows_handle_path(handle: int) -> Path:
    from ctypes import wintypes

    get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32_768)
    length = get_final_path(handle, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise ctypes.WinError()
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _verify_windows_directory_handle(handle: int, expected: Path) -> None:
    from ctypes import wintypes

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        ]

    info = FileAttributeTagInfo()
    get_info = ctypes.windll.kernel32.GetFileInformationByHandleEx
    get_info.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_info.restype = wintypes.BOOL
    if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError()
    if not info.file_attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY:
        raise CapabilityError("workspace path is not a directory")
    if info.file_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        raise CapabilityError("path escapes the workspace")
    actual = os.path.normcase(str(_windows_handle_path(handle).resolve()))
    wanted = os.path.normcase(str(expected.resolve()))
    if actual != wanted:
        raise CapabilityError("path escapes the workspace")


def _open_windows_directory_handle(path: Path) -> int:
    """Lock a directory against rename/delete while a Windows operation uses it."""
    if os.name != "nt":
        raise OSError("Windows directory handles are unavailable")
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        _WINDOWS_DIRECTORY_ACCESS,
        _WINDOWS_DIRECTORY_SHARE,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError()
    verified_handle = int(handle)
    try:
        _verify_windows_directory_handle(verified_handle, path)
    except BaseException:
        with suppress(OSError):
            _close_windows_handle(verified_handle)
        raise
    return verified_handle


def _close_windows_handle(handle: int) -> None:
    if os.name == "nt" and not ctypes.windll.kernel32.CloseHandle(handle):
        raise ctypes.WinError()


def _lock_windows_directory_chain(
    root: Path, parts: tuple[str, ...], root_handle: int | None = None
) -> list[int]:
    handles: list[int] = []
    current = root
    try:
        if root_handle is None:
            handles.append(_open_windows_directory_handle(current))
        for part in parts:
            current /= part
            handles.append(_open_windows_directory_handle(current))
            if _is_reparse_or_symlink(current):
                raise CapabilityError("path escapes the workspace")
        return handles
    except BaseException:
        for handle in reversed(handles):
            with suppress(OSError):
                _close_windows_handle(handle)
        raise


def _open_parent_fd(
    root: Path, parts: tuple[str, ...], root_fd: int | None = None
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.dup(root_fd) if root_fd is not None else os.open(root, flags | nofollow)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags | nofollow, dir_fd=descriptor)
            previous = descriptor
            descriptor = child
            os.close(previous)
        return descriptor
    except BaseException:
        _close_posix_descriptors(descriptor)
        raise


def _read_workspace_bytes(
    root: Path,
    relative_path: str,
    root_fd: int | None = None,
    *,
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    parts = _relative_parts(relative_path)
    normalized = Path(*parts).as_posix()

    def read_opened(stream: Any) -> bytes:
        if max_bytes is not None and os.fstat(stream.fileno()).st_size > max_bytes:
            raise _ReadLimitExceeded(normalized)
        limit = MAX_SOURCE_BYTES if max_bytes is None else min(MAX_SOURCE_BYTES, max_bytes)
        return stream.read(limit + 1 if max_bytes is None else limit)

    if os.name == "posix":
        parent_fd: int | None = None
        file_fd: int | None = None
        try:
            parent_fd = _open_parent_fd(root, parts, root_fd)
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise CapabilityError(f"workspace file not found: {relative_path}")
            with os.fdopen(file_fd, "rb") as stream:
                file_fd = None
                return read_opened(stream), normalized
        except (CapabilityError, _ReadLimitExceeded):
            raise
        except OSError as exc:
            _raise_posix_path_escape(exc)
            raise CapabilityError(f"workspace file could not be read: {normalized}") from exc
        finally:
            _close_posix_descriptors(file_fd, parent_fd)

    path, normalized = _workspace_path(root, relative_path)
    _reject_reparse_components(root, parts)
    if not path.is_file():
        raise CapabilityError(f"workspace file not found: {relative_path}")
    try:
        with path.open("rb") as stream:
            _verify_windows_handle(stream, root)
            raw = read_opened(stream)
    except (CapabilityError, _ReadLimitExceeded):
        raise
    except OSError as exc:
        raise CapabilityError(f"workspace file could not be read: {normalized}") from exc
    return raw, normalized


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short workspace write")
        view = view[written:]


def _close_posix_descriptors(*descriptors: int | None) -> None:
    for descriptor in descriptors:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _cleanup_posix_write(
    parent_fd: int | None, temporary_fd: int | None, temporary_name: str
) -> None:
    _close_posix_descriptors(temporary_fd)
    if parent_fd is not None:
        if temporary_name:
            with suppress(OSError):
                os.unlink(temporary_name, dir_fd=parent_fd)
        _close_posix_descriptors(parent_fd)


def _write_posix(
    root: Path, parts: tuple[str, ...], content: bytes, root_fd: int | None = None
) -> bool:
    parent_fd: int | None = None
    temporary_fd: int | None = None
    temporary_name = f".faye-write-{secrets.token_hex(12)}"
    created = True
    existing_mode: int | None = None
    try:
        parent_fd = _open_parent_fd(root, parts, root_fd)
        try:
            metadata = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise CapabilityError(
                    f"workspace path is not a file: {Path(*parts).as_posix()}"
                )
            created = False
            existing_mode = stat.S_IMODE(metadata.st_mode)
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        _write_all(temporary_fd, content)
        os.fsync(temporary_fd)
        if existing_mode is not None:
            os.fchmod(temporary_fd, existing_mode)
        os.close(temporary_fd)
        temporary_fd = None
        os.replace(
            temporary_name,
            parts[-1],
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_name = ""
        os.fsync(parent_fd)
        return created
    finally:
        _cleanup_posix_write(parent_fd, temporary_fd, temporary_name)


def _replace_windows_file(replacement: Path, destination: Path) -> None:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = (wintypes.LPCWSTR,)
    get_attributes.restype = wintypes.DWORD
    set_attributes = kernel32.SetFileAttributesW
    set_attributes.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    set_attributes.restype = wintypes.BOOL
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    )
    replace_file.restype = wintypes.BOOL

    attributes = get_attributes(str(destination))
    if attributes == _WINDOWS_INVALID_FILE_ATTRIBUTES:
        raise ctypes.WinError(ctypes.get_last_error())
    writable_attributes = attributes & ~_WINDOWS_FILE_ATTRIBUTE_READONLY
    attributes_changed = writable_attributes != attributes
    if attributes_changed and not set_attributes(str(destination), writable_attributes):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not replace_file(str(destination), str(replacement), None, 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException as original_error:
        if attributes_changed and not set_attributes(str(destination), attributes):
            original_error.add_note(
                f"also failed to restore destination attributes: "
                f"{ctypes.WinError(ctypes.get_last_error())}"
            )
        raise
    if attributes_changed and not set_attributes(str(destination), attributes):
        raise ctypes.WinError(ctypes.get_last_error())


def _write_windows(
    root: Path,
    parts: tuple[str, ...],
    content: bytes,
    root_handle: int | None = None,
) -> bool:
    normalized = Path(*parts).as_posix()
    path, _ = _workspace_path(root, normalized)
    _reject_reparse_components(root, parts)
    parent = path.parent.resolve()
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise CapabilityError("path escapes the workspace") from exc
    if not parent.is_dir():
        raise CapabilityError(f"workspace parent directory not found: {normalized}")

    # Each handle requests DELETE access but omits FILE_SHARE_DELETE. Windows
    # therefore rejects root/parent rename or deletion until the atomic replace
    # completes, closing the path-check/replace race.
    directory_handles = _lock_windows_directory_chain(
        root, parts[:-1], root_handle
    )
    temporary_name: str | None = None
    try:
        _reject_reparse_components(root, parts)
        if path.exists() and not path.is_file():
            raise CapabilityError(f"workspace path is not a file: {normalized}")
        created = not path.exists()
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".faye-write-", dir=parent, delete=False
        ) as stream:
            temporary_name = stream.name
            _verify_windows_handle(stream, root)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if created:
            os.replace(temporary_name, path)
        else:
            _replace_windows_file(Path(temporary_name), path)
        temporary_name = None
        return created
    finally:
        if temporary_name is not None:
            with suppress(OSError):
                Path(temporary_name).unlink()
        for handle in reversed(directory_handles):
            with suppress(OSError):
                _close_windows_handle(handle)


def _path_search_candidates(
    workspace: Path, search_root: Path, search_normalized: str, file_glob: str
) -> tuple[list[str], bool]:
    if search_root.is_file():
        return (
            [search_normalized] if Path(search_normalized).match(file_glob) else [],
            False,
        )
    if not search_root.is_dir():
        raise CapabilityError(f"workspace path not found: {search_normalized}")
    candidates: list[str] = []
    entries_seen = 0
    truncated = False
    stack = [search_root]
    while stack and not truncated:
        directory = stack.pop()
        records: list[tuple[str, bool, bool]] = []
        with os.scandir(directory) as entries:
            while True:
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                entries_seen += 1
                if entries_seen > MAX_SEARCH_ENTRIES:
                    truncated = True
                    break
                try:
                    records.append(
                        (
                            entry.name,
                            entry.is_dir(follow_symlinks=False),
                            entry.is_file(follow_symlinks=False),
                        )
                    )
                except OSError:
                    continue
        child_dirs: list[Path] = []
        for name, is_dir, is_file in sorted(records):
            child = directory / name
            if is_dir and not _is_reparse_or_symlink(child):
                child_dirs.append(child)
            elif is_file and not _is_reparse_or_symlink(child):
                normalized = child.relative_to(workspace).as_posix()
                if Path(normalized).match(file_glob):
                    candidates.append(normalized)
                    if len(candidates) > MAX_SEARCH_FILES:
                        truncated = True
                        break
        if not truncated:
            stack.extend(reversed(child_dirs))
    return candidates[:MAX_SEARCH_FILES], truncated


def _open_posix_search_root(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        for index, part in enumerate(parts):
            child_flags = flags
            if index < len(parts) - 1:
                child_flags |= getattr(os, "O_DIRECTORY", 0)
            child = os.open(part, child_flags, dir_fd=descriptor)
            previous = descriptor
            descriptor = child
            os.close(previous)
        return descriptor
    except BaseException:
        _close_posix_descriptors(descriptor)
        raise


def _posix_search_candidates(
    root_fd: int, search_parts: tuple[str, ...], file_glob: str
) -> tuple[list[str], bool]:
    descriptor = _open_posix_search_root(root_fd, search_parts)
    try:
        metadata = os.fstat(descriptor)
    except BaseException:
        _close_posix_descriptors(descriptor)
        raise
    if stat.S_ISREG(metadata.st_mode):
        _close_posix_descriptors(descriptor)
        normalized = Path(*search_parts).as_posix()
        return ([normalized] if Path(normalized).match(file_glob) else [], False)
    if not stat.S_ISDIR(metadata.st_mode):
        _close_posix_descriptors(descriptor)
        raise CapabilityError(f"workspace path not found: {Path(*search_parts).as_posix()}")

    candidates: list[str] = []
    entries_seen = 0
    truncated = False
    stack: list[tuple[int, tuple[str, ...]]] = [(descriptor, search_parts)]
    try:
        while stack and not truncated:
            directory_fd, prefix = stack.pop()
            records: list[tuple[str, bool, bool]] = []
            child_dirs: list[tuple[int, tuple[str, ...]]] = []
            try:
                with os.scandir(directory_fd) as entries:
                    while True:
                        try:
                            entry = next(entries)
                        except StopIteration:
                            break
                        entries_seen += 1
                        if entries_seen > MAX_SEARCH_ENTRIES:
                            truncated = True
                            break
                        try:
                            records.append(
                                (
                                    entry.name,
                                    entry.is_dir(follow_symlinks=False),
                                    entry.is_file(follow_symlinks=False),
                                )
                            )
                        except OSError:
                            continue
                for name, is_dir, is_file in sorted(records):
                    child_parts = (*prefix, name)
                    if is_dir:
                        try:
                            child_fd = os.open(
                                name,
                                os.O_RDONLY
                                | getattr(os, "O_DIRECTORY", 0)
                                | getattr(os, "O_NOFOLLOW", 0),
                                dir_fd=directory_fd,
                            )
                        except OSError:
                            continue
                        child_dirs.append((child_fd, child_parts))
                    elif is_file:
                        normalized = Path(*child_parts).as_posix()
                        if Path(normalized).match(file_glob):
                            candidates.append(normalized)
                            if len(candidates) > MAX_SEARCH_FILES:
                                truncated = True
                                break
                if not truncated:
                    stack.extend(reversed(child_dirs))
                    child_dirs = []
            finally:
                _close_posix_descriptors(
                    directory_fd, *(child_fd for child_fd, _ in child_dirs)
                )
    finally:
        _close_posix_descriptors(*(pending_fd for pending_fd, _ in stack))
    return candidates[:MAX_SEARCH_FILES], truncated


def _search_payload_size(matches: list[dict[str, Any]], truncated: bool) -> int:
    payload = {"matches": matches, "truncated": truncated}
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def build_workspace_capabilities(
    root: str | Path, *, allow_writes: bool = False
) -> CapabilityRegistry:
    workspace = Path(root).resolve()
    if not workspace.is_dir() or _is_reparse_or_symlink(workspace):
        raise ValueError(f"workspace is not a directory: {workspace}")
    registry = CapabilityRegistry()
    root_fd: int | None = None
    root_handle: int | None = None
    if os.name == "posix":
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        root_fd = os.open(workspace, flags)
        weakref.finalize(registry, os.close, root_fd)
    elif os.name == "nt":
        root_handle = _open_windows_directory_handle(workspace)
        weakref.finalize(registry, _close_windows_handle, root_handle)

    def read_file(arguments: dict[str, Any]) -> dict[str, Any]:
        offset = arguments.get("offset", 1)
        limit = arguments.get("limit", 200)
        if offset < 1:
            raise CapabilityError("invalid arguments for read_file: offset must be positive")
        if not 1 <= limit <= 500:
            raise CapabilityError(
                "invalid arguments for read_file: limit must be between 1 and 500"
            )
        raw, normalized = _read_workspace_bytes(workspace, arguments["path"], root_fd)
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

    def search_text(arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments["query"]
        relative_path = arguments.get("path", ".")
        file_glob = arguments.get("file_glob", "*")
        limit = arguments.get("limit", 100)
        if not query:
            raise CapabilityError("invalid arguments for search_text: query must not be empty")
        if not file_glob:
            raise CapabilityError("invalid arguments for search_text: file_glob must not be empty")
        if not 1 <= limit <= 500:
            raise CapabilityError(
                "invalid arguments for search_text: limit must be between 1 and 500"
            )

        search_parts = _relative_parts(relative_path, allow_root=True)
        if os.name == "posix":
            assert root_fd is not None
            try:
                candidates, truncated = _posix_search_candidates(
                    root_fd, search_parts, file_glob
                )
            except OSError as exc:
                _raise_posix_path_escape(exc)
                raise CapabilityError(f"workspace path not found: {relative_path}") from exc
        else:
            search_root, search_normalized = _workspace_path(
                workspace, relative_path, allow_root=True
            )
            _reject_reparse_components(workspace, search_parts)
            candidates, truncated = _path_search_candidates(
                workspace, search_root, search_normalized, file_glob
            )

        matches: list[dict[str, Any]] = []
        total_bytes = 0
        acquisition_truncated = truncated
        processing_truncated = False
        stop_processing = False
        for normalized in candidates:
            remaining = MAX_SEARCH_TOTAL_BYTES - total_bytes
            if remaining <= 0:
                processing_truncated = True
                break
            read_limit = min(MAX_SOURCE_BYTES, remaining)
            try:
                raw, verified_normalized = _read_workspace_bytes(
                    workspace,
                    normalized,
                    root_fd,
                    max_bytes=read_limit,
                )
            except _ReadLimitExceeded:
                if remaining <= MAX_SOURCE_BYTES:
                    processing_truncated = True
                    break
                continue
            except CapabilityError:
                continue
            total_bytes += len(raw)
            try:
                lines = raw.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query not in line:
                    continue
                if len(matches) >= limit:
                    processing_truncated = True
                    stop_processing = True
                    break
                displayed = line[:MAX_SEARCH_MATCH_CHARS]
                match = {
                    "path": verified_normalized,
                    "line": line_number,
                    "text": displayed,
                }
                prospective = [*matches, match]
                if _search_payload_size(prospective, False) > MAX_OUTPUT_CHARS:
                    processing_truncated = True
                    stop_processing = True
                    break
                matches.append(match)
                if len(displayed) < len(line):
                    processing_truncated = True
            if stop_processing:
                break

        truncated = acquisition_truncated or processing_truncated
        if _search_payload_size(matches, truncated) > MAX_OUTPUT_CHARS:
            raise CapabilityError("search_text output budget is too small")
        return {"matches": matches, "truncated": truncated}

    registry.register(
        Capability(
            name="search_text",
            description="Search literal text in bounded UTF-8 files inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "file_glob": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=search_text,
        )
    )

    if allow_writes:

        def write_file(arguments: dict[str, Any]) -> dict[str, Any]:
            parts = _relative_parts(arguments["path"])
            normalized = Path(*parts).as_posix()
            encoded = arguments["content"].encode("utf-8")
            if len(encoded) > MAX_WRITE_BYTES:
                raise CapabilityError(
                    f"write_file content exceeds {MAX_WRITE_BYTES} bytes: {normalized}"
                )
            try:
                created = (
                    _write_posix(workspace, parts, encoded, root_fd)
                    if os.name == "posix"
                    else _write_windows(workspace, parts, encoded, root_handle)
                )
            except CapabilityError:
                raise
            except OSError as exc:
                if os.name == "posix":
                    _raise_posix_path_escape(exc)
                raise CapabilityError(
                    f"workspace file could not be written: {normalized}"
                ) from exc
            return {
                "path": normalized,
                "bytes_written": len(encoded),
                "created": created,
            }

        registry.register(
            Capability(
                name="write_file",
                description=(
                    "Atomically write bounded UTF-8 content to a file inside the workspace."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                handler=write_file,
            )
        )
    return registry
