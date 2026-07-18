import subprocess

import pytest

from faye.commands import CommandExecutor, CommandRejected


def test_read_only_command_executes_without_approval():
    executor = CommandExecutor(timeout=5)

    result = executor.run("python --version")

    assert result.returncode == 0


def test_auto_allowed_command_bypasses_shell(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "Python 3.11", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    CommandExecutor(timeout=5).run("python --version")

    command, kwargs = calls[0]
    assert command == ["python", "--version"]
    assert kwargs["shell"] is False


def test_mutating_command_requires_approval():
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="approval"):
        executor.run("mkdir faye-test-directory")


def test_destructive_command_stays_blocked_when_approved():
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="blocked"):
        executor.run("git reset --hard", approved=True)


def test_command_timeout_is_enforced():
    executor = CommandExecutor(timeout=0.01)

    with pytest.raises(subprocess.TimeoutExpired):
        executor.run('python -c "import time; time.sleep(1)"', approved=True)