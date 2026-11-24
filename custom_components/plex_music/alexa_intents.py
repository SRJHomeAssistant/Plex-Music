"""Pure Alexa request routing. Network authentication is enforced by the future endpoint."""
from __future__ import annotations

from typing import Any


def extract_track_request(envelope: dict[str, Any]) -> str | None:
    """Extract a requested track from an Alexa PlayTrackIntent envelope.

    This function is NOT a request verifier. Never call it on an unverified HTTP request.
    """
    request = envelope.get("request", {})
    if request.get("type") != "IntentRequest":
        return None
    intent = request.get("intent", {})
    if intent.get("name") != "PlayTrackIntent":
        return None
    track = intent.get("slots", {}).get("track", {}).get("value", "")
    if not isinstance(track, str):
        return None
    track = track.strip()
    return track[:200] if track else None


def requesting_device_id(envelope: dict[str, Any]) -> str | None:
    """Return the opaque ID of the Echo that invoked the skill, if supplied."""
    device_id = (
        envelope.get("context", {})
        .get("System", {})
        .get("device", {})
        .get("deviceId")
    )
    return device_id if isinstance(device_id, str) and device_id else None


def extract_identify_device_request(envelope: dict[str, Any]) -> str | None:
    """Extract ID only for IdentifyDeviceIntent; caller MUST verify Alexa signature."""
    request = envelope.get("request", {})
    if request.get("type") != "IntentRequest":
        return None
    if request.get("intent", {}).get("name") != "IdentifyDeviceIntent":
        return None
    return requesting_device_id(envelope)
