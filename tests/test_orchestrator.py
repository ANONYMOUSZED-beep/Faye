import threading
import time

import pytest

from faye.models import TaskSpec
from faye.orchestrator import BoundedOrchestrator


class FakeModel:
    def __init__(self, tasks):
        self.tasks = tasks
        self.completed = []

    def plan(self, command, context):
        return self.tasks

    def execute(self, task, context):
        self.completed.append(task.id)
        return f"done:{task.instruction}"

    def synthesize(self, command, results, context):
        return " | ".join(result.output for result in results)


def test_simple_command_uses_fast_path_without_planner(tmp_path):
    model = FakeModel([TaskSpec(id="unused", instruction="unused")])
    agent = BoundedOrchestrator(model=model, state_path=tmp_path / "state.db")

    answer = agent.execute("hello")

    assert "Faye" in answer.text
    assert model.completed == []
    assert answer.elapsed_ms < 100


def test_duplicate_tasks_are_deduplicated(tmp_path):
    tasks = [
        TaskSpec(id="a", instruction="research batteries"),
        TaskSpec(id="b", instruction=" Research   batteries "),
    ]
    model = FakeModel(tasks)
    agent = BoundedOrchestrator(model=model, state_path=tmp_path / "state.db")

    answer = agent.execute("research battery technology")

    assert answer.tasks_completed == 1
    assert model.completed == ["a"]


def test_runs_independent_tasks_concurrently_and_respects_limit(tmp_path):
    lock = threading.Lock()
    active = 0
    peak = 0

    class ConcurrentModel(FakeModel):
        def execute(self, task, context):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return task.id

    tasks = [TaskSpec(id=str(i), instruction=f"task {i}") for i in range(20)]
    agent = BoundedOrchestrator(
        model=ConcurrentModel(tasks), state_path=tmp_path / "state.db", max_agents=8
    )

    answer = agent.execute("perform a complex parallel analysis")

    assert answer.tasks_completed == 20
    assert 2 <= peak <= 8
    assert answer.elapsed_ms < 700


def test_agent_limit_is_hard_capped_at_100(tmp_path):
    with pytest.raises(ValueError, match="between 1 and 100"):
        BoundedOrchestrator(model=FakeModel([]), state_path=tmp_path / "state.db", max_agents=101)
