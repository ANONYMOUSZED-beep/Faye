from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str
    instruction: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    output: str
    elapsed_ms: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    text: str
    tasks_completed: int
    elapsed_ms: float
    errors: tuple[str, ...] = ()
