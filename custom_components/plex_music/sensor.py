"""Status sensors for Alexa devices registered with Plex Music."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .alexa_devices import CONF_ALEXA_REGISTERED_DEVICES
from .const import DOMAIN
from .media_proxy import paused_playback_update


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create a status sensor for each registered Alexa device."""
    devices = entry.options.get(CONF_ALEXA_REGISTERED_DEVICES, {})
    entities = []
    for key, device in devices.items():
        entities.append(AlexaDeviceStatusSensor(entry, key, device["name"]))
        entities.append(AlexaHeardSensor(entry, key, device["name"]))
        entities.append(AlexaPlexMatchSensor(entry, key, device["name"]))
        for field, title, icon in DIAGNOSTIC_FIELDS:
            entities.append(AlexaDiagnosticSensor(entry, key, device["name"], field, title, icon))
    async_add_entities(entities)


class AlexaDeviceStatusSensor(SensorEntity):
    """Status of an Echo registered through the Plex Music skill.

    Verified playback events update the sensor and its current-track attributes.
    """

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:speaker"

    def __init__(self, entry: ConfigEntry, key: str, friendly_name: str) -> None:
        self._entry_id = entry.entry_id
        self._device_key = key
        self._attr_unique_id = f"{entry.entry_id}_alexa_{key}_status"
        self._attr_native_value = "Idle"
        self._attr_extra_state_attributes = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_alexa_{key}")},
            name=friendly_name,
            manufacturer="Amazon",
            model="Alexa device",
        )

    async def async_added_to_hass(self) -> None:
        """Listen for verified Alexa playback lifecycle events."""
        self.async_on_remove(async_dispatcher_connect(
            self.hass,
            f"plex_music_alexa_status_{self._entry_id}_{self._device_key}",
            self._async_update_status,
        ))
        restored = paused_playback_update(self.hass, self._entry_id, self._device_key)
        if restored:
            self._async_update_status(restored)

    def _async_update_status(self, update: dict | str) -> None:
        """Update status and track details after a verified Alexa event."""
        if isinstance(update, str):
            update = {"status": update}
        status = update.get("status")
        if status in ("Playing", "Paused", "Idle"):
            # Display paused playback as Idle while retaining its saved resume state.
            self._attr_native_value = "Playing" if status == "Playing" else "Idle"
            self._attr_extra_state_attributes = {
                "media_title": update.get("title"),
                "media_artist": update.get("artist"),
                "media_album_name": update.get("album"),
            } if status == "Playing" else {}
            self._attr_entity_picture = update.get("artwork") if status == "Playing" else None
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)


class AlexaHeardSensor(SensorEntity):
    """Last phrase Alexa supplied to this skill, before voice overrides."""

    _attr_has_entity_name = True
    _attr_name = "Alexa Heard"
    _attr_icon = "mdi:microphone-message"
    _attr_native_value = "Unknown"

    def __init__(self, entry: ConfigEntry, key: str, friendly_name: str) -> None:
        self._entry_id = entry.entry_id
        self._device_key = key
        self._attr_unique_id = f"{entry.entry_id}_alexa_{key}_heard"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_alexa_{key}")},
            name=friendly_name,
            manufacturer="Amazon",
            model="Alexa device",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass,
            f"plex_music_alexa_heard_{self._entry_id}_{self._device_key}",
            self._async_update_heard,
        ))

    def _async_update_heard(self, phrase: str) -> None:
        if isinstance(phrase, str) and phrase.strip():
            self._attr_native_value = phrase[:200]
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

class AlexaPlexMatchSensor(SensorEntity):
    """Most recent Plex catalogue match for a verified Alexa request."""

    _attr_has_entity_name = True
    _attr_name = "Plex Match"
    _attr_icon = "mdi:music-box-multiple"
    _attr_native_value = "Unknown"

    def __init__(self, entry: ConfigEntry, key: str, friendly_name: str) -> None:
        self._entry_id = entry.entry_id
        self._device_key = key
        self._attr_unique_id = f"{entry.entry_id}_alexa_{key}_plex_match"
        self._attr_extra_state_attributes = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_alexa_{key}")},
            name=friendly_name,
            manufacturer="Amazon",
            model="Alexa device",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass,
            f"plex_music_alexa_match_{self._entry_id}_{self._device_key}",
            self._update_match,
        ))

    def _update_match(self, result: dict) -> None:
        self._attr_native_value = result.get("status", "Unknown")
        self._attr_extra_state_attributes = {
            "heard": result.get("heard"),
            "resolved_query": result.get("resolved_query"),
            "alias_applied": result.get("alias_applied", False),
            "match_count": result.get("match_count", 0),
            "artist": result.get("artist"),
            "album": result.get("album"),
            "track": result.get("track"),
            "error": result.get("error"),
        }
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

DIAGNOSTIC_FIELDS = (
    ("album", "Album", "mdi:album"),
    ("artist", "Artist", "mdi:account-music"),
    ("intent", "Intent", "mdi:message-text"),
    ("last_alexa_event", "Last Alexa Event", "mdi:message-badge"),
    ("last_called", "Last Called", "mdi:clock-outline"),
    ("plex_search", "Plex Search", "mdi:magnify"),
    ("request_type", "Request Type", "mdi:microphone"),
    ("requested_music", "Requested Music", "mdi:music-note"),
    ("search_result", "Search Result", "mdi:playlist-check"),
    ("source", "Source", "mdi:music-box-multiple"),
    ("track", "Track", "mdi:music-note"),
    ("stream_status", "Stream Status", "mdi:access-point-network"),
)


class AlexaDiagnosticSensor(SensorEntity):
    """One field of verified Alexa playback diagnostics."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, key: str, friendly_name: str,
                 field: str, title: str, icon: str) -> None:
        self._entry_id = entry.entry_id
        self._device_key = key
        self._field = field
        self._attr_unique_id = f"{entry.entry_id}_alexa_{key}_diagnostic_{field}"
        self._attr_name = title
        self._attr_icon = icon
        self._attr_native_value = "Unknown"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_alexa_{key}")},
            name=friendly_name,
            manufacturer="Amazon",
            model="Alexa device",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass,
            f"plex_music_alexa_diagnostics_{self._entry_id}_{self._device_key}",
            self._update,
        ))

    def _update(self, changes: dict) -> None:
        if self._field in changes:
            value = changes[self._field]
            if self._field == "last_called":
                try:
                    timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
                    self._attr_native_value = (
                        dt_util.as_local(timestamp).strftime("%d/%m/%Y %H:%M:%S")
                        if isinstance(timestamp, datetime) and timestamp.tzinfo is not None
                        else "Unknown"
                    )
                except (TypeError, ValueError):
                    self._attr_native_value = "Unknown"
            else:
                self._attr_native_value = str(value)[:255] if value is not None else "Unknown"
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)
