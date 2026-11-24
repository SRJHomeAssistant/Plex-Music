"""Alexa AudioPlayer response helpers."""
from __future__ import annotations


def play_response(queue_id: str, tracks: list[dict], index: int = 0, behavior: str = "REPLACE_ALL", offset: int = 0) -> dict:
    """Return a speech-free Alexa AudioPlayer directive with display metadata."""
    track = tracks[index]
    token = f"{queue_id}:{index}"
    metadata = {
        "title": track["title"],
        "subtitle": " — ".join(part for part in (track.get("artist"), track.get("album")) if part),
    }
    if track.get("artwork_url"):
        metadata["art"] = {"sources": [{"url": track["artwork_url"]}]}
        metadata["backgroundImage"] = {"sources": [{"url": track["artwork_url"]}]}
    stream = {
        "url": track["audio_url"],
        "token": token,
        "offsetInMilliseconds": max(0, offset),
    }
    if behavior == "ENQUEUE":
        stream["expectedPreviousToken"] = f"{queue_id}:{index - 1}"
    return {
        "version": "1.0",
        "response": {
            "shouldEndSession": True,
            "directives": [{
                "type": "AudioPlayer.Play",
                "playBehavior": behavior,
                "audioItem": {"stream": stream, "metadata": metadata},
            }],
        },
    }


def ask_for_music() -> dict:
    """Elicit the SearchQuery slot so a bare artist/album/track can be spoken."""
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": "What would you like to play?"},
            "directives": [{
                "type": "Dialog.ElicitSlot",
                "slotToElicit": "track",
            }],
            "shouldEndSession": False,
        },
    }


def speech(text: str) -> dict:
    return {"version": "1.0", "response": {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": True,
    }}


def stop_response() -> dict:
    """Stop audio without speaking."""
    return {"version": "1.0", "response": {
        "shouldEndSession": True,
        "directives": [{"type": "AudioPlayer.Stop"}],
    }}
