"""Alexa device discovery and registration helpers.

Only feed device IDs from authenticated and skill-ID-verified Alexa requests.
"""
from __future__ import annotations

import hashlib
from typing import Any

CONF_ALEXA_PENDING_DEVICES = "alexa_pending_devices"
CONF_ALEXA_REGISTERED_DEVICES = "alexa_registered_devices"


def device_key(device_id: str) -> str:
    """Opaque stable key; do not expose Amazon device IDs in UI labels."""
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Missing Alexa device ID")
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def discover_device(options: dict[str, Any], device_id: str) -> dict[str, Any]:
    """Record a newly identified device without overwriting existing names."""
    key = device_key(device_id)
    updated = dict(options)
    registered = dict(updated.get(CONF_ALEXA_REGISTERED_DEVICES, {}))
    pending = dict(updated.get(CONF_ALEXA_PENDING_DEVICES, {}))
    if key not in registered and key not in pending:
        pending[key] = {"device_id": device_id}
    updated[CONF_ALEXA_PENDING_DEVICES] = pending
    return updated


def register_devices(options: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """Move named devices from pending to registered, preserving others."""
    updated = dict(options)
    pending = dict(updated.get(CONF_ALEXA_PENDING_DEVICES, {}))
    registered = dict(updated.get(CONF_ALEXA_REGISTERED_DEVICES, {}))
    for key, name in names.items():
        name = name.strip()
        if key not in pending or not name or len(name) > 80:
            raise ValueError("Select a pending device and provide a name (1–80 characters)")
        if any(item.get("name", "").casefold() == name.casefold() for item in registered.values()):
            raise ValueError("A device with this name already exists")
        registered[key] = {**pending.pop(key), "name": name}
    updated[CONF_ALEXA_PENDING_DEVICES] = pending
    updated[CONF_ALEXA_REGISTERED_DEVICES] = registered
    return updated


def delete_devices(options: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Remove selected registered devices, leaving other devices untouched."""
    updated = dict(options)
    registered = dict(updated.get(CONF_ALEXA_REGISTERED_DEVICES, {}))
    for key in keys:
        if key not in registered:
            raise ValueError("Selected device is not registered")
        registered.pop(key)
    updated[CONF_ALEXA_REGISTERED_DEVICES] = registered
    return updated
