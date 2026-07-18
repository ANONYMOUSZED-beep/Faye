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
    _auto_allowed = {
        "pwd": ("pwd",),
        "whoami": ("whoami",),
        "python --version": ("python", "--version"),
        "uv --version": ("uv", "--version"),
    }

    def auto_allowed_argv(self, command: str) -> tuple[str, ...] | None:
        """Return fixed argv only for commands safe to run without a shell."""
        has_unsupported_whitespace = any(
            character.isspace() and character not in " \t" for character in command
        )
        if has_unsupported_whitespace:
            return None
        normalized = re.sub(r"[ \t]+", " ", command.lower()).strip()
        return self._auto_allowed.get(normalized)

    def evaluate(self, command: str, approved: bool = False) -> CommandDecision:
        normalized = re.sub(r"[ \t]+", " ", command.lower()).strip()
        if any(re.search(pattern, normalized) for pattern in self._blocked):
            return CommandDecision.BLOCK
        if self.auto_allowed_argv(command) is not None:
            return CommandDecision.ALLOW
        return CommandDecision.ALLOW if approved else CommandDecision.REQUIRE_APPROVAL
