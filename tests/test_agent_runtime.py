import pytest

from faye.agent import AgentLimitError, AgentRuntime, AgentToolLimitError
from faye.capabilities import Capability, CapabilityRegistry
from faye.models import AgentStep, ToolCall


class ScriptedModel:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.requests = []

    def respond(self, messages, tools):
        self.requests.append((messages, tools))
        return next(self.steps)


def test_agent_executes_typed_capability_and_returns_result_to_model():
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="lookup_symbol",
            description="Look up a source symbol",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            handler=lambda arguments: {"path": "src/faye/agent.py", "name": arguments["name"]},
        )
    )
    model = ScriptedModel(
        [
            AgentStep(
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="lookup_symbol",
                        arguments={"name": "AgentRuntime"},
                    ),
                )
            ),
            AgentStep(text="AgentRuntime is defined in src/faye/agent.py."),
        ]
    )

    result = AgentRuntime(model=model, capabilities=registry, max_turns=4).run(
        "Where is AgentRuntime defined?"
    )

    assert result.text == "AgentRuntime is defined in src/faye/agent.py."
    assert result.turns == 2
    assert len(result.audit) == 1
    assert result.audit[0].tool_call == ToolCall(
        id="call-1", name="lookup_symbol", arguments={"name": "AgentRuntime"}
    )
    assert result.audit[0].ok is True
    assert result.audit[0].output == {"path": "src/faye/agent.py", "name": "AgentRuntime"}
    second_messages, tools = model.requests[1]
    assert tools[0]["function"]["name"] == "lookup_symbol"
    assert second_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "lookup_symbol",
        "content": '{"name":"AgentRuntime","path":"src/faye/agent.py"}',
    }


def test_agent_audit_snapshots_nested_requests_and_outputs_immutably():
    registry = CapabilityRegistry()
    output = {"result": {"values": [1, {"state": "original"}]}}
    arguments = {"query": {"terms": ["alpha", {"weight": 1}]}}
    registry.register(
        Capability(
            name="inspect",
            description="Inspect nested input",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "object"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda _arguments: output,
        )
    )
    model = ScriptedModel(
        [
            AgentStep(
                tool_calls=(ToolCall(id="call-1", name="inspect", arguments=arguments),)
            ),
            AgentStep(text="done"),
        ]
    )

    result = AgentRuntime(model=model, capabilities=registry).run("Inspect it")
    arguments["query"]["terms"][1]["weight"] = 99
    output["result"]["values"][1]["state"] = "mutated"

    event = result.audit[0]
    assert event.tool_call.arguments == {
        "query": {"terms": ("alpha", {"weight": 1})}
    }
    assert event.output == {
        "result": {"values": (1, {"state": "original"})}
    }
    with pytest.raises(TypeError):
        event.tool_call.arguments["query"]["terms"][1]["weight"] = 2
    with pytest.raises(TypeError):
        event.output["result"]["values"][1]["state"] = "changed"


def test_agent_rejects_invalid_arguments_without_invoking_handler():
    invoked = []
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="read_file",
            description="Read a project file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda arguments: invoked.append(arguments),
        )
    )
    model = ScriptedModel(
        [
            AgentStep(
                tool_calls=(
                    ToolCall(id="bad-1", name="read_file", arguments={"path": 7}),
                )
            ),
            AgentStep(text="I could not read the file because the arguments were invalid."),
        ]
    )

    result = AgentRuntime(model=model, capabilities=registry).run("Read the project file")

    assert invoked == []
    assert result.text == "I could not read the file because the arguments were invalid."
    assert result.audit[0].ok is False
    assert result.audit[0].output == {
        "error": "invalid arguments for read_file: path must be a string"
    }
    assert model.requests[1][0][-1]["content"] == (
        '{"error":"invalid arguments for read_file: path must be a string"}'
    )


def test_agent_audits_capability_failure_and_allows_model_recovery():
    registry = CapabilityRegistry()

    def fail(_arguments):
        raise OSError("file is locked")

    registry.register(
        Capability(
            name="read_file",
            description="Read a project file",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=fail,
        )
    )
    model = ScriptedModel(
        [
            AgentStep(tool_calls=(ToolCall(id="failed-1", name="read_file", arguments={}),)),
            AgentStep(text="The file could not be read because it is locked."),
        ]
    )

    result = AgentRuntime(model=model, capabilities=registry).run("Read it")

    assert result.text == "The file could not be read because it is locked."
    assert result.audit[0].ok is False
    assert result.audit[0].output == {
        "error": "capability read_file failed: OSError: file is locked"
    }
    assert model.requests[1][0][-1]["content"] == (
        '{"error":"capability read_file failed: OSError: file is locked"}'
    )


def test_agent_rejects_unknown_capability_and_allows_model_recovery():
    model = ScriptedModel(
        [
            AgentStep(
                tool_calls=(
                    ToolCall(id="unknown-1", name="shell", arguments={"command": "pwd"}),
                )
            ),
            AgentStep(text="That capability is unavailable."),
        ]
    )

    result = AgentRuntime(model=model, capabilities=CapabilityRegistry()).run("Run pwd")

    assert result.text == "That capability is unavailable."
    assert result.audit[0].ok is False
    assert result.audit[0].output == {"error": "unknown capability: shell"}


def test_agent_rejects_tool_batch_that_exceeds_remaining_budget_atomically():
    invoked = []
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="tick",
            description="Record one bounded step",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda _arguments: invoked.append("tick"),
        )
    )
    model = ScriptedModel(
        [
            AgentStep(
                tool_calls=(
                    ToolCall(id="tick-1", name="tick", arguments={}),
                    ToolCall(id="tick-2", name="tick", arguments={}),
                )
            )
        ]
    )

    with pytest.raises(AgentToolLimitError, match="exceeded max_tool_calls=1") as failure:
        AgentRuntime(
            model=model,
            capabilities=registry,
            max_tool_calls=1,
        ).run("Keep going")

    assert invoked == []
    assert failure.value.audit == ()
    assert failure.value.requested == 2


def test_agent_stops_at_turn_limit_and_preserves_audit():
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="tick",
            description="Record one bounded step",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda _arguments: {"tick": True},
        )
    )
    model = ScriptedModel(
        [
            AgentStep(tool_calls=(ToolCall(id="tick-1", name="tick", arguments={}),)),
            AgentStep(tool_calls=(ToolCall(id="tick-2", name="tick", arguments={}),)),
            AgentStep(text="must never be reached"),
        ]
    )

    with pytest.raises(AgentLimitError, match="exceeded max_turns=2") as failure:
        AgentRuntime(model=model, capabilities=registry, max_turns=2).run("Keep going")

    assert len(model.requests) == 2
    assert [event.tool_call.id for event in failure.value.audit] == ["tick-1", "tick-2"]
    assert all(event.ok for event in failure.value.audit)
