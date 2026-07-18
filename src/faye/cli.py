from __future__ import annotations

import argparse
import os
from pathlib import Path

from faye.agent import AgentRuntime
from faye.commands import CommandExecutor, CommandRejected
from faye.orchestrator import BoundedOrchestrator
from faye.provider import OpenAICompatibleModel
from faye.voice import WindowsVoice
from faye.workspace import build_workspace_capabilities


def build_agent(max_agents: int) -> BoundedOrchestrator:
    state = Path(os.getenv("FAYE_STATE", Path.home() / ".faye" / "memory.db"))
    return BoundedOrchestrator(OpenAICompatibleModel(), state, max_agents=max_agents)


def build_coding_agent(workspace: Path, max_turns: int) -> AgentRuntime:
    return AgentRuntime(
        model=OpenAICompatibleModel(),
        capabilities=build_workspace_capabilities(workspace),
        max_turns=max_turns,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="faye", description="Fast voice-first multi-agent AI")
    parser.add_argument("prompt", nargs="*", help="request for Faye")
    parser.add_argument("--voice", action="store_true", help="listen once and speak the answer")
    parser.add_argument(
        "--agent",
        action="store_true",
        help="use the bounded workspace agent with typed capabilities",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="workspace root for agent capabilities (default: current directory)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=12,
        help="maximum model turns in agent mode (default: 12)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="execute the prompt as a local command instead of sending it to the model",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="confirm a command request; the closed executable allowlist is unchanged",
    )
    parser.add_argument("--agents", type=int, default=100, help="maximum concurrent agents (1-100)")
    args = parser.parse_args()
    if args.voice and args.run:
        parser.error("--voice cannot be combined with --run")
    if args.agent and args.run:
        parser.error("--agent cannot be combined with --run")
    if args.max_turns < 1:
        parser.error("--max-turns must be positive")

    voice = WindowsVoice() if args.voice else None
    command = voice.listen() if voice is not None else " ".join(args.prompt).strip(" \t")
    if not command:
        parser.error("provide a prompt or use --voice")
    if args.run:
        try:
            result = CommandExecutor().run(command, approved=args.approve)
        except CommandRejected as exc:
            parser.error(str(exc))
        text = (result.stdout or result.stderr).strip() or f"Command exited {result.returncode}."
        print(text)
    elif args.agent:
        runtime = build_coding_agent(args.workspace.resolve(), args.max_turns)
        result = runtime.run(command)
        text = result.text
        print(text)
        print(f"\n[{len(result.audit)} tool call(s), {result.turns} turn(s)]")
    else:
        agent = build_agent(args.agents)
        answer = agent.execute(command)
        text = answer.text
        print(text)
        print(f"\n[{answer.tasks_completed} worker(s), {answer.elapsed_ms:.0f} ms]")
    if args.voice:
        voice_output = voice.speak(text)
        if voice_output is not None:
            print(f"[Voice saved to {voice_output}]")


if __name__ == "__main__":
    main()
