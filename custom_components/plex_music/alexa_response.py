"""Pure Alexa AudioPlayer response construction; no unofficial device APIs."""
from __future__ import annotations

from typing import Any


def play_response(audio_url: str, token: str, *, title: str = "", artist: str = "",
                  voice_confirmation: bool = False) -> dict[str, Any]:
    """Return an official AudioPlayer.Play skill response.

    Caller must supply a short-lived, public HTTPS audio URL. Never pass a Plex token.
    """
    if not audio_url.startswith("https://"):
        raise ValueError("Alexa audio requires a public HTTPS URL")
    if not token:
        raise ValueError("A non-empty opaque playback token is required")

    response: dict[str, Any] = {
        "directives": [{
            "type": "AudioPlayer.Play",
            "playBehavior": "REPLACE_ALL",
            "audioItem": {
                "stream": {
                    "url": audio_url,
                    "token": token,
                    "offsetInMilliseconds": 0,
                }
            },
        }],
        "shouldEndSession": True,
    }
    if voice_confirmation:
        name = title.strip() or "your music"
        by = f" by {artist.strip()}" if artist.strip() else ""
        response["outputSpeech"] = {
            "type": "PlainText",
            "text": f"Playing {name}{by}.",
        }
    return {"version": "1.0", "response": response}
