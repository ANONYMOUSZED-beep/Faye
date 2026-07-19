from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


def immutable_json(value: Any) -> Any:
    """Return a detached, deeply immutable snapshot of a JSON-like value."""
    if type(value) is dict:
        return MappingProxyType({key: immutable_json(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(immutable_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AgentStep:
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditEvent:
    tool_call: ToolCall
    ok: bool
    output: Any


@dataclass(frozen=True, slots=True)
class AgentRun:
    text: str
    turns: int
    audit: tuple[AuditEvent, ...] = ()


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
