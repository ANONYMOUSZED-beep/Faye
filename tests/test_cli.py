import sys

import pytest

from faye import cli
from faye.models import AgentRun


def test_agent_mode_uses_bounded_workspace_runtime(tmp_path, monkeypatch, capsys):
    calls = []

    class FakeRuntime:
        def run(self, prompt):
            calls.append(("run", prompt))
            return AgentRun(text="Inspected the workspace.", turns=2, audit=())

    def build_runtime(workspace, max_turns, allow_writes=False):
        calls.append(("build", workspace, max_turns, allow_writes))
        return FakeRuntime()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("--agent must not construct the swarm orchestrator")

    monkeypatch.setattr(cli, "build_coding_agent", build_runtime)
    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "faye",
            "--agent",
            "--workspace",
            str(tmp_path),
            "--max-turns",
            "3",
            "inspect",
            "the workspace",
        ],
    )

    cli.main()

    assert calls == [
        ("build", tmp_path.resolve(), 3, False),
        ("run", "inspect the workspace"),
    ]
    output = capsys.readouterr().out
    assert "Inspected the workspace." in output
    assert "[0 tool call(s), 2 turn(s)]" in output


def test_agent_write_mode_explicitly_enables_workspace_writes(
    tmp_path, monkeypatch, capsys
):
    calls = []

    class FakeRuntime:
        def run(self, prompt):
            calls.append(("run", prompt))
            return AgentRun(text="Updated the workspace.", turns=1, audit=())

    def build_runtime(workspace, max_turns, allow_writes=False):
        calls.append(("build", workspace, max_turns, allow_writes))
        return FakeRuntime()

    monkeypatch.setattr(cli, "build_coding_agent", build_runtime)
    monkeypatch.setattr(
        sys,
        "argv",
        ["faye", "--agent", "--write", "--workspace", str(tmp_path), "update", "it"],
    )

    cli.main()

    assert calls == [
        ("build", tmp_path.resolve(), 12, True),
        ("run", "update it"),
    ]
    assert "Updated the workspace." in capsys.readouterr().out


@pytest.mark.parametrize("count", ["0", "101"])
def test_agents_out_of_range_rejects_before_dependency_construction(
    count, tmp_path, monkeypatch
):
    state = tmp_path / "nested" / "memory.db"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid --agents must reject before dependencies")

    monkeypatch.setattr(cli, "WindowsVoice", fail_if_called)
    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setattr(cli, "build_coding_agent", fail_if_called)
    monkeypatch.setenv("FAYE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["faye", "--agents", count, "hello"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert not state.exists()
    assert not state.parent.exists()


def test_write_without_agent_rejects_before_dependency_construction(
    tmp_path, monkeypatch
):
    state = tmp_path / "nested" / "memory.db"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("--write without --agent must reject before dependencies")

    monkeypatch.setattr(cli, "WindowsVoice", fail_if_called)
    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setattr(cli, "build_coding_agent", fail_if_called)
    monkeypatch.setenv("FAYE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["faye", "--write", "update", "it"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert not state.exists()
    assert not state.parent.exists()


def test_agent_run_conflict_rejects_before_dependency_construction(tmp_path, monkeypatch):
    state = tmp_path / "nested" / "memory.db"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("--agent --run must reject before constructing dependencies")

    monkeypatch.setattr(cli, "WindowsVoice", fail_if_called)
    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setattr(cli, "build_coding_agent", fail_if_called)
    monkeypatch.setenv("FAYE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["faye", "--agent", "--run", "pwd"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert not state.exists()
    assert not state.parent.exists()


def test_blocked_run_does_not_build_agent_or_create_state(tmp_path, monkeypatch):
    state = tmp_path / "nested" / "memory.db"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("blocked --run must not construct the agent")

    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setenv("FAYE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["faye", "--run", "--approve", "git status"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert not state.exists()
    assert not state.parent.exists()


def test_voice_run_is_rejected_before_voice_or_agent_construction(tmp_path, monkeypatch):
    state = tmp_path / "nested" / "memory.db"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("--voice --run must reject before constructing dependencies")

    monkeypatch.setattr(cli, "WindowsVoice", fail_if_called)
    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setenv("FAYE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["faye", "--voice", "--run"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert not state.exists()
    assert not state.parent.exists()


@pytest.mark.parametrize(
    "command",
    ["\u00a0pwd", "pwd\u00a0", "\u2003whoami", "whoami\u2003", "\npwd", "whoami\r"],
)
def test_run_does_not_strip_unsupported_edge_whitespace(
    command, tmp_path, monkeypatch
):
    state = tmp_path / "nested" / "memory.db"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("blocked --run must not construct the agent")

    monkeypatch.setattr(cli, "build_agent", fail_if_called)
    monkeypatch.setenv("FAYE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["faye", "--run", command])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert not state.exists()
    assert not state.parent.exists()
