from __future__ import annotations

import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


class WindowsVoice:
    """Native Windows speech synthesis and recognition through System.Speech."""

    def __init__(
        self,
        runner: Callable[..., Any] = subprocess.run,
        output_dir: str | Path | None = None,
    ) -> None:
        self._runner = runner
        self.output_dir = Path(output_dir or Path.home() / ".faye" / "audio")

    @staticmethod
    def _powershell(script: str) -> list[str]:
        utf8_script = (
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding=[Console]::OutputEncoding; "
            + script
        )
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            utf8_script,
        ]

    def speak(self, text: str) -> Path | None:
        escaped = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$v.Rate=2; "
            f"$v.Speak('{escaped}')"
        )
        try:
            self._runner(
                self._powershell(script),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
            )
            return None
        except subprocess.CalledProcessError:
            return self._speak_to_file(escaped)

    def _speak_to_file(self, escaped_text: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / f"faye-{uuid.uuid4().hex[:10]}.wav"
        escaped_output = str(output.resolve()).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$p='{escaped_output}'; "
            "$v.SetOutputToWaveFile($p); "
            f"$v.Speak('{escaped_text}'); "
            "$v.Dispose(); $p"
        )
        result = self._runner(
            self._powershell(script),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
        rendered = result.stdout.strip() if result.stdout else str(output)
        return Path(rendered)

    def listen(self) -> str:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$r=New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
            "$r.SetInputToDefaultAudioDevice(); "
            "$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
            "$x=$r.Recognize([TimeSpan]::FromSeconds(12)); "
            "if($x){$x.Text}"
        )
        result = self._runner(
            self._powershell(script),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
        return result.stdout.rstrip("\r\n")
