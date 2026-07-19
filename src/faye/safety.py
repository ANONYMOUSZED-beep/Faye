from __future__ import annotations

import enum
import re
import shlex


class CommandDecision(enum.Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class SafetyPolicy:
    """Conservative local-command policy; model text cannot override it."""

    _blocked = (
        re.compile(r"\brm\s+-[^\n]*r[^\n]*f\s+[/~]"),
        re.compile(r"\bformat\s+[a-z]:"),
        re.compile(r"\bdel\s+/[fsq].*\\"),
        re.compile(r"\b(shutdown|reboot)\b"),
        re.compile(r"\bgit\s+reset\s+--hard\b"),
        re.compile(r"\bgit\s+clean\b.*(-f|--force)"),
        re.compile(r"\bgit\s+push\b.*(-f|--force)"),
        re.compile(r"\b(reg\s+delete|diskpart|bcdedit)\b"),
    )

    _auto_allowed = {
        "pwd": ("pwd",),
        "whoami": ("whoami",),
        "python --version": ("python", "--version"),
    }

    def auto_allowed_argv(self, command: str) -> tuple[str, ...] | None:
        """Return fixed argv only for commands safe to run without a shell."""
        has_unsupported_whitespace = any(
            character.isspace() and character not in " \t" for character in command
        )
        if has_unsupported_whitespace:
            return None
        normalized = re.sub(r"[ \t]+", " ", command).strip()
        return self._auto_allowed.get(normalized)

    def parse_argv(self, command: str) -> list[str] | None:
        """Parse command into argv using POSIX shell rules. Returns None if unparseable."""
        try:
            return shlex.split(command)
        except ValueError:
            return None

    def evaluate(self, command: str, approved: bool = False) -> CommandDecision:
        normalized = re.sub(r"[ \t]+", " ", command.lower()).strip()

        if any(pattern.search(normalized) for pattern in self._blocked):
            return CommandDecision.BLOCK

        argv = self.parse_argv(command)
        if argv:
            reconstructed = " ".join(argv).lower()
            if any(pattern.search(reconstructed) for pattern in self._blocked):
                return CommandDecision.BLOCK

        if self.auto_allowed_argv(command) is not None:
            return CommandDecision.ALLOW
        return CommandDecision.BLOCK if approved else CommandDecision.REQUIRE_APPROVAL
