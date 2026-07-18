import sys

import pytest

from faye import cli


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
