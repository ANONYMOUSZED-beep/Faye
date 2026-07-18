import pytest

from faye.memory import LearningMemory
from faye.safety import CommandDecision, SafetyPolicy


def test_blocks_destructive_commands_without_explicit_approval():
    policy = SafetyPolicy()

    decision = policy.evaluate("rm -rf /", approved=False)

    assert decision is CommandDecision.BLOCK


def test_allows_read_only_commands():
    policy = SafetyPolicy()

    assert policy.evaluate("python --version", approved=False) is CommandDecision.ALLOW


def test_uv_version_is_not_executable_through_generic_gateway():
    policy = SafetyPolicy()

    assert policy.evaluate("uv --version", approved=False) is CommandDecision.REQUIRE_APPROVAL
    assert policy.evaluate("uv --version", approved=True) is CommandDecision.BLOCK


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git status --short",
        "git diff --textconv",
        "git log --textconv",
        'python --version -c "print(1)"',
        "uv --version --directory escaped",
    ],
)
def test_commands_with_extra_arguments_or_non_status_git_are_not_auto_allowed(command):
    policy = SafetyPolicy()

    decision = policy.evaluate(command, approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_read_only_command_chained_to_mutation_is_not_auto_allowed():
    policy = SafetyPolicy()

    decision = policy.evaluate("git status && mkdir escaped", approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_read_only_prefix_lookalike_is_not_auto_allowed():
    policy = SafetyPolicy()

    decision = policy.evaluate("git statusmalicious", approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_cmd_percent_expansion_is_not_auto_allowed():
    policy = SafetyPolicy()

    decision = policy.evaluate("git status %USERPROFILE%", approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_cmd_delayed_expansion_is_not_auto_allowed():
    policy = SafetyPolicy()

    decision = policy.evaluate("git status !var!", approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_git_diff_output_flag_is_not_auto_allowed():
    policy = SafetyPolicy()

    decision = policy.evaluate("git diff --output=escaped.txt", approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_git_diff_ext_diff_is_not_auto_allowed():
    policy = SafetyPolicy()

    decision = policy.evaluate("git diff --ext-diff", approved=False)

    assert decision in (CommandDecision.REQUIRE_APPROVAL, CommandDecision.BLOCK)


def test_non_ascii_or_control_whitespace_requires_approval():
    policy = SafetyPolicy()

    assert policy.evaluate("git\u00a0status") is CommandDecision.REQUIRE_APPROVAL
    assert policy.evaluate("git\vstatus") is CommandDecision.REQUIRE_APPROVAL


def test_memory_records_feedback_and_returns_improvement_hint(tmp_path):
    memory = LearningMemory(tmp_path / "faye.db")
    memory.record_interaction("summarize this", "too long", score=-1, feedback="be concise")

    hints = memory.improvement_hints("summarize another report")

    assert "be concise" in hints
