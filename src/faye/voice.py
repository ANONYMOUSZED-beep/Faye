from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any


class WindowsVoice:
    """Native Windows speech synthesis and recognition through System.Speech."""

    def __init__(self, runner: Callable[..., Any] = subprocess.run) -> None:
        self._runner = runner

    def speak(self, text: str) -> None:
        escaped = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$v.Rate=2; "
            f"$v.Speak('{escaped}')"
        )
        self._runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
        )

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
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
