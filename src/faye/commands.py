from __future__ import annotations

import subprocess

from faye.safety import CommandDecision, SafetyPolicy


class CommandRejected(Exception):
    pass


class CommandExecutor:
    """Runs shell commands under the SafetyPolicy gate."""

    def __init__(self, timeout: float = 30, policy: SafetyPolicy | None = None) -> None:
        self.timeout = timeout
        self.policy = policy or SafetyPolicy()

    def run(
        self, command: str, approved: bool = False
    ) -> subprocess.CompletedProcess[str]:
        decision = self.policy.evaluate(command, approved=approved)
        if decision is CommandDecision.BLOCK:
            raise CommandRejected(f"Command blocked by safety policy: {command!r}")
        if decision is CommandDecision.REQUIRE_APPROVAL:
            raise CommandRejected(
                f"Command requires explicit approval before execution: {command!r}"
            )
        safe_argv = self.policy.auto_allowed_argv(command)
        return subprocess.run(
            list(safe_argv) if safe_argv is not None else command,
            shell=safe_argv is None,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
