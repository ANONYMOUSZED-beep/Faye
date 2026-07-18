import subprocess

import pytest

from faye.commands import CommandExecutor, CommandRejected


def test_read_only_command_executes_without_approval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import subprocess

    subprocess.run("git init", shell=True, capture_output=True, cwd=str(tmp_path))
    executor = CommandExecutor(timeout=5)

    result = executor.run("git status --short")

    assert result.returncode == 0


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