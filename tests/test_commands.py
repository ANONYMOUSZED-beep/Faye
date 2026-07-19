import subprocess
import sys

import pytest

from faye.commands import CommandExecutor, CommandRejected, _os_username


def test_read_only_command_executes_without_approval():
    executor = CommandExecutor(timeout=5)

    result = executor.run("python --version")

    assert result.returncode == 0


def test_whoami_ignores_spoofable_login_environment(monkeypatch):
    expected = _os_username()
    monkeypatch.setenv("LOGNAME", "spoofed-user")
    monkeypatch.setenv("USER", "spoofed-user")
    monkeypatch.setenv("LNAME", "spoofed-user")
    monkeypatch.setenv("USERNAME", "spoofed-user")

    result = CommandExecutor().run("whoami")

    assert result.stdout.strip() == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Windows account format")
def test_whoami_matches_native_windows_account_identity():
    expected = subprocess.run(
        ["whoami"], capture_output=True, text=True, check=True
    ).stdout.strip()

    result = CommandExecutor().run("whoami")

    assert result.stdout.strip().casefold() == expected.casefold()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API contract")
def test_windows_identity_rejects_unexpected_sizing_error(monkeypatch):
    import ctypes

    calls = 0

    class FakeGetUserNameExW:
        argtypes = None
        restype = None

        def __call__(self, _name_format, buffer, size_pointer):
            nonlocal calls
            calls += 1
            assert buffer is None
            size_pointer._obj.value = 8
            ctypes.set_last_error(5)  # ERROR_ACCESS_DENIED
            return 0

    class FakeSecur32:
        GetUserNameExW = FakeGetUserNameExW()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: FakeSecur32())

    with pytest.raises(OSError) as error:
        _os_username()

    assert error.value.winerror == 5
    assert calls == 1


@pytest.mark.parametrize(
    "command",
    ["PWD", "WhoAmI", "PYTHON --VERSION", "Python --version"],
)
def test_auto_allowed_commands_are_case_sensitive(command):
    with pytest.raises(CommandRejected):
        CommandExecutor().run(command)


def test_python_version_is_in_process(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    result = CommandExecutor(timeout=5).run("python --version")

    assert result.returncode == 0
    assert result.args == ["<internal:python>", "--version"]
    assert result.stdout == f"Python {sys.version.split()[0]}\n"


def test_mutating_command_is_outside_closed_allowlist():
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run("mkdir faye-test-directory")


def test_mutating_command_blocked_even_when_approved():
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run("mkdir faye-test-directory", approved=True)


def test_destructive_command_stays_blocked_when_approved():
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run("git reset --hard", approved=True)


def test_destructive_command_blocked_through_quote_removal():
    """Quote-removal bypass: shell would strip quotes and reconstruct the blocked command."""
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run('git reset --h"ar"d', approved=True)

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run("git reset --h'ar'd", approved=True)


@pytest.mark.parametrize(
    "command",
    [
        "git clean -df",
        "git clean --force -d",
        "git clean -fd",
        "git push -f origin main",
        "git push --force origin main",
    ],
)
def test_destructive_git_variants_blocked_even_when_approved(command):
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run(command, approved=True)


@pytest.mark.parametrize(
    "command",
    [
        "git -c alias.x=reset x --hard",
        "git checkout -- tracked.txt",
        "git restore tracked.txt",
        "git branch -D main",
        "git diff --ext-diff",
        "python git status",
        "cmd /c git status",
        "./git status",
        "../attacker/git status",
        "/tmp/git status",
        "C:/temp/git.exe status",
    ],
)
def test_generic_executor_blocks_non_status_git_commands(command):
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run(command, approved=True)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git status --short",
        "git status --porcelain",
        "git status --porcelain=v1",
        "git status --porcelain=v2",
    ],
)
def test_git_status_is_blocked_even_when_approved(monkeypatch, command):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        CommandExecutor().run(command, approved=True)


def test_hostile_cwd_and_path_cannot_enable_git(tmp_path, monkeypatch):
    fake_git = tmp_path / ("git.exe" if sys.platform == "win32" else "git")
    fake_git.write_text("hostile", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        CommandExecutor(timeout=5).run("git status", approved=True)


def test_uv_version_is_blocked_without_spawning_process(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    with pytest.raises(CommandRejected):
        CommandExecutor(timeout=5).run("uv --version", approved=True)


def test_approval_does_not_make_python_external(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    result = CommandExecutor(timeout=5).run("python --version", approved=True)

    assert result.returncode == 0
    assert result.args == ["<internal:python>", "--version"]


@pytest.mark.parametrize("command", ["pwd", "whoami"])
def test_internal_commands_do_not_spawn_process(monkeypatch, command):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    result = CommandExecutor().run(command)

    assert result.returncode == 0
    assert result.stdout.strip()


@pytest.mark.parametrize(
    "command",
    [
        'python -c "import os; os.remove(\'victim\')"',
        'powershell -Command "Remove-Item victim"',
        'bash -c "rm victim"',
        'cmd /c "del victim"',
        "echo harmless-looking",
    ],
)
def test_generic_executor_blocks_arbitrary_approved_programs(command):
    executor = CommandExecutor()

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        executor.run(command, approved=True)


@pytest.mark.parametrize(
    "substituted_argv",
    [("pwd",), ("whoami",), ("python", "--version")],
)
def test_custom_allow_policy_cannot_translate_arbitrary_input(
    monkeypatch, substituted_argv
):
    class UnsafePolicy:
        @staticmethod
        def evaluate(command, approved=False):
            from faye.safety import CommandDecision

            return CommandDecision.ALLOW

        @staticmethod
        def auto_allowed_argv(command):
            return substituted_argv

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        CommandExecutor(policy=UnsafePolicy()).run("attacker --payload", approved=True)


def test_mutated_policy_allowlist_cannot_translate_arbitrary_input(monkeypatch):
    from faye.safety import SafetyPolicy

    monkeypatch.setitem(SafetyPolicy._auto_allowed, "attacker --payload", ("pwd",))

    with pytest.raises(CommandRejected, match="closed executable allowlist"):
        CommandExecutor().run("attacker --payload", approved=True)


def test_string_subclass_cannot_override_command_normalization():
    class MisleadingCommand(str):
        def lower(self):
            return "pwd"

        def strip(self, *args, **kwargs):
            return "pwd"

    with pytest.raises(CommandRejected, match="plain string"):
        CommandExecutor().run(MisleadingCommand("attacker --payload"), approved=True)
