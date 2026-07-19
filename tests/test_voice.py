import subprocess
from types import SimpleNamespace

from faye.voice import WindowsVoice


def test_windows_voice_escapes_text_before_speaking():
    calls = []
    voice = WindowsVoice(runner=lambda args, **kwargs: calls.append(args))

    voice.speak("That's Faye")

    script = calls[0][-1]
    assert "That''s Faye" in script


def test_windows_voice_returns_recognized_text():
    class Result:
        stdout = "open my calendar\n"

    voice = WindowsVoice(runner=lambda *args, **kwargs: Result())

    assert voice.listen() == "open my calendar"


def test_windows_voice_falls_back_to_wave_file_when_audio_device_is_missing(tmp_path):
    calls = []

    class Result:
        stdout = str(tmp_path / "faye.wav") + "\n"

    def runner(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, args, stderr="Audio device error")
        return Result()

    voice = WindowsVoice(runner=runner, output_dir=tmp_path)

    output = voice.speak("Faye is online")

    assert output == tmp_path / "faye.wav"
    assert "SetOutputToWaveFile" in calls[1][-1]


def test_windows_voice_uses_explicit_utf8_for_every_subprocess(tmp_path):
    calls = []

    class Result:
        stdout = "recognized\n"

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    voice = WindowsVoice(runner=runner, output_dir=tmp_path)
    voice.speak("hello")
    voice._speak_to_file("hello")
    voice.listen()

    assert len(calls) == 3
    for args, kwargs in calls:
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "strict"
        assert kwargs["text"] is True
        assert "OutputEncoding" in args[-1]


def test_listen_preserves_unsupported_edge_whitespace():
    recognized = "\u00a0pwd\u00a0"

    def runner(*args, **kwargs):
        return SimpleNamespace(stdout=recognized + chr(13) + chr(10))

    assert WindowsVoice(runner=runner).listen() == recognized
