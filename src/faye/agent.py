from __future__ import annotations

import json
from typing import Any, Protocol

from faye.capabilities import CapabilityError, CapabilityRegistry
from faye.models import AgentRun, AgentStep, AuditEvent, ToolCall, immutable_json


class ToolCallingModel(Protocol):
    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
    ) -> AgentStep: ...


class AgentLimitError(RuntimeError):
    """Raised when a bounded run exhausts its turns without a final answer."""

    def __init__(self, max_turns: int, audit: tuple[AuditEvent, ...]) -> None:
        super().__init__(f"agent exceeded max_turns={max_turns}")
        self.audit = audit


class AgentToolLimitError(RuntimeError):
    """Raised before a tool batch would exceed the run's action budget."""

    def __init__(
        self,
        max_tool_calls: int,
        requested: int,
        audit: tuple[AuditEvent, ...],
    ) -> None:
        super().__init__(f"agent exceeded max_tool_calls={max_tool_calls}")
        self.requested = requested
        self.audit = audit


class AgentRuntime:
    """Bounded model-to-capability loop with an audit record for every call."""

    def __init__(
        self,
        model: ToolCallingModel,
        capabilities: CapabilityRegistry,
        max_turns: int = 12,
        max_tool_calls: int = 32,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        self.model = model
        self.capabilities = capabilities
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls

    def run(self, prompt: str) -> AgentRun:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        audit: list[AuditEvent] = []
        tools = self.capabilities.schemas()

        for turn in range(1, self.max_turns + 1):
            step = self.model.respond(messages, tools)
            if step.tool_calls:
                if len(audit) + len(step.tool_calls) > self.max_tool_calls:
                    raise AgentToolLimitError(
                        self.max_tool_calls,
                        len(step.tool_calls),
                        tuple(audit),
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": step.text,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(
                                        call.arguments, sort_keys=True, separators=(",", ":")
                                    ),
                                },
                            }
                            for call in step.tool_calls
                        ],
                    }
                )
                for call in step.tool_calls:
                    try:
                        output = self.capabilities.invoke(call.name, call.arguments)
                        ok = True
                    except CapabilityError as exc:
                        output = {"error": str(exc)}
                        ok = False
                    audit.append(
                        AuditEvent(
                            tool_call=ToolCall(
                                id=call.id,
                                name=call.name,
                                arguments=immutable_json(call.arguments),
                            ),
                            ok=ok,
                            output=immutable_json(output),
                        )
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": json.dumps(output, sort_keys=True, separators=(",", ":")),
                        }
                    )
                continue
            if step.text is not None:
                return AgentRun(text=step.text, turns=turn, audit=tuple(audit))
            raise RuntimeError("model returned neither text nor tool calls")

        raise AgentLimitError(self.max_turns, tuple(audit))
