from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class CapabilityError(ValueError):
    """Raised when a model requests an unavailable or invalid capability."""


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class CapabilityRegistry:
    """Closed registry of explicitly named, typed agent capabilities."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._capabilities:
            raise CapabilityError(f"capability already registered: {capability.name}")
        self._capabilities[capability.name] = capability

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return tuple(capability.schema() for capability in self._capabilities.values())

    def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            capability = self._capabilities[name]
        except KeyError as exc:
            raise CapabilityError(f"unknown capability: {name}") from exc
        self._validate_arguments(capability, arguments)
        try:
            return capability.handler(arguments)
        except CapabilityError:
            raise
        except Exception as exc:
            raise CapabilityError(
                f"capability {name} failed: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _validate_arguments(capability: Capability, arguments: dict[str, Any]) -> None:
        if type(arguments) is not dict:
            raise CapabilityError(f"invalid arguments for {capability.name}: expected an object")
        schema = capability.parameters
        required = schema.get("required", ())
        for name in required:
            if name not in arguments:
                raise CapabilityError(
                    f"invalid arguments for {capability.name}: missing required field {name}"
                )
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unexpected = arguments.keys() - properties.keys()
            if unexpected:
                name = sorted(unexpected)[0]
                raise CapabilityError(
                    f"invalid arguments for {capability.name}: unexpected field {name}"
                )
        type_names = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for name, value in arguments.items():
            expected_name = properties.get(name, {}).get("type")
            expected = type_names.get(expected_name)
            if expected is not None and type(value) not in (
                expected if isinstance(expected, tuple) else (expected,)
            ):
                raise CapabilityError(
                    f"invalid arguments for {capability.name}: {name} must be a {expected_name}"
                )
