from faye.memory import LearningMemory
from faye.safety import CommandDecision, SafetyPolicy


def test_blocks_destructive_commands_without_explicit_approval():
    policy = SafetyPolicy()

    decision = policy.evaluate("rm -rf /", approved=False)

    assert decision is CommandDecision.BLOCK


def test_allows_read_only_commands():
    policy = SafetyPolicy()

    assert policy.evaluate("git status", approved=False) is CommandDecision.ALLOW


def test_memory_records_feedback_and_returns_improvement_hint(tmp_path):
    memory = LearningMemory(tmp_path / "faye.db")
    memory.record_interaction("summarize this", "too long", score=-1, feedback="be concise")

    hints = memory.improvement_hints("summarize another report")

    assert "be concise" in hints
