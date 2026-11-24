"""Tests for official Alexa response payloads."""
import pytest

from custom_components.plex_music.alexa_response import play_response


def test_silent_playback_has_no_speech():
    payload = play_response("https://music.example.org/audio/opaque", "queue-1")
    response = payload["response"]
    assert "outputSpeech" not in response
    assert response["shouldEndSession"] is True
    assert response["directives"][0]["type"] == "AudioPlayer.Play"
    assert response["directives"][0]["audioItem"]["stream"]["token"] == "queue-1"


def test_spoken_confirmation():
    response = play_response(
        "https://music.example.org/audio/opaque", "queue-2",
        title="Dog Days Are Over", artist="Florence + the Machine",
        voice_confirmation=True,
    )["response"]
    assert response["outputSpeech"]["text"] == (
        "Playing Dog Days Are Over by Florence + the Machine."
    )


def test_rejects_private_http_audio():
    with pytest.raises(ValueError):
        play_response("http://192.168.1.2:32400/music", "queue-3")
