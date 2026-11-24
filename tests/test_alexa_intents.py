"""Alexa intent extraction tests."""
from custom_components.plex_music.alexa_intents import (
    extract_track_request,
    requesting_device_id,
)


def test_track_intent():
    envelope = {
        "request": {"type": "IntentRequest", "intent": {
            "name": "PlayTrackIntent", "slots": {
                "track": {"value": " Dog Days Are Over "}}}},
        "context": {"System": {"device": {"deviceId": "opaque-device"}}},
    }
    assert extract_track_request(envelope) == "Dog Days Are Over"
    assert requesting_device_id(envelope) == "opaque-device"


def test_ignores_other_intents():
    assert extract_track_request({"request": {"type": "LaunchRequest"}}) is None
    assert requesting_device_id({}) is None
