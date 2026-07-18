from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol

from faye.memory import LearningMemory
from faye.models import AgentAnswer, TaskResult, TaskSpec


class AgentModel(Protocol):
    def plan(self, command: str, context: str) -> list[TaskSpec]: ...
    def execute(self, task: TaskSpec, context: str) -> str: ...
    def synthesize(self, command: str, results: list[TaskResult], context: str) -> str: ...


class BoundedOrchestrator:
    """Fast bounded fan-out: up to 100 workers, only when useful."""

    def __init__(self, model: AgentModel, state_path: str | Path, max_agents: int = 100) -> None:
        if not 1 <= max_agents <= 100:
            raise ValueError("max_agents must be between 1 and 100")
        self.model = model
        self.max_agents = max_agents
        self.memory = LearningMemory(state_path)

    @staticmethod
    def _fast_path(command: str) -> str | None:
        normalized = re.sub(r"[^a-z ]", "", command.lower()).strip()
        if normalized in {"hi", "hello", "hey", "hey faye", "hello faye"}:
            return "Faye online. Fast, synthetic, and ready—what are we hunting?"
        if normalized in {"who are you", "what are you"}:
            return (
                "I'm Faye: an artificial multi-agent system, not a human. "
                "Sharp tools, sharper timing."
            )
        return None

    @staticmethod
    def _deduplicate(tasks: list[TaskSpec]) -> list[TaskSpec]:
        seen: set[str] = set()
        unique: list[TaskSpec] = []
        for task in tasks:
            key = " ".join(task.instruction.lower().split())
            if key not in seen:
                seen.add(key)
                unique.append(task)
        return unique

    def execute(self, command: str) -> AgentAnswer:
        started = time.perf_counter()
        if quick := self._fast_path(command):
            elapsed = (time.perf_counter() - started) * 1000
            self.memory.record_interaction(command, quick)
            return AgentAnswer(quick, 0, elapsed)

        context = self.memory.recent_context()
        hints = self.memory.improvement_hints(command)
        if hints:
            context += f"\nPrior feedback to apply:\n{hints}"
        tasks = self._deduplicate(self.model.plan(command, context))[:100]
        results: list[TaskResult] = []
        workers = min(self.max_agents, len(tasks))
        if workers:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="faye-mini") as pool:
                futures = {pool.submit(self._run_task, task, context): task for task in tasks}
                for future in as_completed(futures):
                    results.append(future.result())
        results.sort(key=lambda result: result.task_id)
        good = [result for result in results if result.error is None]
        text = (
            self.model.synthesize(command, good, context)
            if good
            else "No worker completed successfully."
        )
        elapsed = (time.perf_counter() - started) * 1000
        errors = tuple(result.error for result in results if result.error)
        self.memory.record_interaction(command, text)
        return AgentAnswer(text, len(good), elapsed, errors)

    def _run_task(self, task: TaskSpec, context: str) -> TaskResult:
        started = time.perf_counter()
        try:
            output = self.model.execute(task, context)
            return TaskResult(task.id, output, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            return TaskResult(task.id, "", (time.perf_counter() - started) * 1000, str(exc))

    def learn(self, prompt: str, response: str, feedback: str, score: int = -1) -> None:
        self.memory.record_interaction(prompt, response, score=score, feedback=feedback)
