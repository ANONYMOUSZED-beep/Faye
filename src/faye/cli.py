from __future__ import annotations

import argparse
import os
from pathlib import Path

from faye.commands import CommandExecutor, CommandRejected
from faye.orchestrator import BoundedOrchestrator
from faye.provider import OpenAICompatibleModel
from faye.voice import WindowsVoice


def build_agent(max_agents: int) -> BoundedOrchestrator:
    state = Path(os.getenv("FAYE_STATE", Path.home() / ".faye" / "memory.db"))
    return BoundedOrchestrator(OpenAICompatibleModel(), state, max_agents=max_agents)


def main() -> None:
    parser = argparse.ArgumentParser(prog="faye", description="Fast voice-first multi-agent AI")
    parser.add_argument("prompt", nargs="*", help="request for Faye")
    parser.add_argument("--voice", action="store_true", help="listen once and speak the answer")
    parser.add_argument(
        "--run",
        action="store_true",
        help="execute the prompt as a local command instead of sending it to the model",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="approve a non-destructive mutating command used with --run",
    )
    parser.add_argument("--agents", type=int, default=100, help="maximum concurrent agents (1-100)")
    args = parser.parse_args()
    agent = build_agent(args.agents)
    voice = WindowsVoice()
    command = voice.listen() if args.voice else " ".join(args.prompt).strip()
    if not command:
        parser.error("provide a prompt or use --voice")
    if args.run:
        try:
            result = CommandExecutor().run(command, approved=args.approve)
        except CommandRejected as exc:
            parser.error(str(exc))
        text = (result.stdout or result.stderr).strip() or f"Command exited {result.returncode}."
        print(text)
    else:
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
