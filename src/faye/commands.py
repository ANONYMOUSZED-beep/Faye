from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from faye.safety import CommandDecision, SafetyPolicy


class CommandRejected(Exception):
    pass


def _os_username() -> str:
    """Return the effective OS account name without consulting login environment variables."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        name_sam_compatible = 2
        get_user_name_ex = ctypes.WinDLL(
            "secur32", use_last_error=True
        ).GetUserNameExW
        get_user_name_ex.argtypes = [
            wintypes.INT,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.ULONG),
        ]
        get_user_name_ex.restype = wintypes.BOOL

        error_more_data = 234
        size = wintypes.ULONG(0)
        ctypes.set_last_error(0)
        sizing_succeeded = get_user_name_ex(
            name_sam_compatible, None, ctypes.byref(size)
        )
        sizing_error = ctypes.get_last_error()
        if sizing_succeeded or sizing_error != error_more_data or size.value == 0:
            raise ctypes.WinError(sizing_error)

        buffer = ctypes.create_unicode_buffer(size.value)
        if not get_user_name_ex(
            name_sam_compatible, buffer, ctypes.byref(size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.value

    import os
    import pwd

    return pwd.getpwuid(os.geteuid()).pw_name


class CommandExecutor:
    """Runs narrowly allowed commands entirely in-process. No subprocess is ever launched."""

    def __init__(self, timeout: float = 30, policy: SafetyPolicy | None = None) -> None:
        self.timeout = timeout
        self.policy = policy or SafetyPolicy()

    @staticmethod
    def _closed_argv(command: str) -> tuple[str, ...] | None:
        """Map only a plain, ASCII-space/tab-normalized command to an internal operation."""
        if type(command) is not str:
            raise CommandRejected("Command must be a plain string")
        if any(character.isspace() and character not in " \t" for character in command):
            return None

        normalized = " ".join(command.replace("\t", " ").split()).strip(" \t")
        if normalized == "pwd":
            return ("pwd",)
        if normalized == "whoami":
            return ("whoami",)
        if normalized == "python --version":
            return ("python", "--version")
        return None

    @staticmethod
    def _internal_result(
        safe_argv: tuple[str, ...],
    ) -> subprocess.CompletedProcess[str] | None:
        if safe_argv == ("pwd",):
            return subprocess.CompletedProcess(
                ["<internal:pwd>"], 0, f"{Path.cwd()}\n", ""
            )
        if safe_argv == ("whoami",):
            return subprocess.CompletedProcess(
                ["<internal:whoami>"], 0, f"{_os_username()}\n", ""
            )
        if safe_argv == ("python", "--version"):
            version = sys.version.split()[0]
            return subprocess.CompletedProcess(
                ["<internal:python>", "--version"], 0, f"Python {version}\n", ""
            )
        return None

    def run(
        self, command: str, approved: bool = False
    ) -> subprocess.CompletedProcess[str]:
        safe_argv = self._closed_argv(command)
        if safe_argv is None:
            raise CommandRejected(
                f"Command is outside the closed executable allowlist: {command!r}"
            )

        decision = self.policy.evaluate(command, approved=approved)
        if decision is CommandDecision.BLOCK:
            raise CommandRejected(f"Command blocked by safety policy: {command!r}")
        if decision is CommandDecision.REQUIRE_APPROVAL:
            raise CommandRejected(
                f"Command requires explicit approval before execution: {command!r}"
            )

        internal_result = self._internal_result(safe_argv)
        if internal_result is not None:
            return internal_result

        # Unreachable: every auto_allowed command is handled above.
        raise CommandRejected(
            f"Command is outside the closed executable allowlist: {command!r}"
        )
