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
