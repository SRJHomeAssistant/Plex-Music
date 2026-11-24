"""Unit tests for Alexa device discovery and registration."""
from custom_components.plex_music.alexa_devices import (
    CONF_ALEXA_PENDING_DEVICES, CONF_ALEXA_REGISTERED_DEVICES,
    discover_device, device_key, register_devices, delete_devices,
)
from custom_components.plex_music.alexa_intents import extract_identify_device_request


def test_identify_intent():
    request = {"request": {"type": "IntentRequest", "intent": {"name": "IdentifyDeviceIntent"}},
               "context": {"System": {"device": {"deviceId": "echo-1"}}}}
    assert extract_identify_device_request(request) == "echo-1"


def test_discovery_and_registration():
    options = discover_device({}, "echo-1")
    options = discover_device(options, "echo-1")
    key = device_key("echo-1")
    assert len(options[CONF_ALEXA_PENDING_DEVICES]) == 1
    updated = register_devices(options, {key: "Kitchen Echo"})
    assert key not in updated[CONF_ALEXA_PENDING_DEVICES]
    assert updated[CONF_ALEXA_REGISTERED_DEVICES][key]["name"] == "Kitchen Echo"
    assert key not in discover_device(updated, "echo-1")[CONF_ALEXA_PENDING_DEVICES]


def test_delete_registered_device():
    options = discover_device({}, "echo-1")
    key = device_key("echo-1")
    options = register_devices(options, {key: "Kitchen Echo"})
    updated = delete_devices(options, [key])
    assert key not in updated[CONF_ALEXA_REGISTERED_DEVICES]
    assert key not in updated[CONF_ALEXA_PENDING_DEVICES]
    assert key in discover_device(updated, "echo-1")[CONF_ALEXA_PENDING_DEVICES]
