from __future__ import annotations

import enum
import re


class CommandDecision(enum.Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class SafetyPolicy:
    """Conservative local-command policy; model text cannot override it."""

    _blocked = (
        r"\brm\s+-[^\n]*r[^\n]*f\s+[/~]",
        r"\bformat\s+[a-z]:",
        r"\bdel\s+/[fsq].*\\",
        r"\b(shutdown|reboot)\b",
        r"\bgit\s+(reset\s+--hard|clean\s+-f|push\s+.*--force)\b",
        r"\b(reg\s+delete|diskpart|bcdedit)\b",
    )
    _read_only = (
        "git status",
        "git diff",
        "git log",
        "pwd",
        "whoami",
        "python --version",
        "uv --version",
    )
    _shell_control = re.compile(r"[;&|`$<>\r\n]")

    def evaluate(self, command: str, approved: bool = False) -> CommandDecision:
        normalized = " ".join(command.lower().split())
        if any(re.search(pattern, normalized) for pattern in self._blocked):
            return CommandDecision.BLOCK
        is_single_command = not self._shell_control.search(command)
        is_read_only = any(
            normalized == prefix or normalized.startswith(f"{prefix} ")
            for prefix in self._read_only
        )
        if is_single_command and is_read_only:
            return CommandDecision.ALLOW
        return CommandDecision.ALLOW if approved else CommandDecision.REQUIRE_APPROVAL
