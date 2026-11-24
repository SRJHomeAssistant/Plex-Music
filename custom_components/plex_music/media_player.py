"""Read-only Alexa now-playing media player for Home Assistant."""
from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerState, MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alexa_devices import CONF_ALEXA_REGISTERED_DEVICES
from .const import DOMAIN
from .media_proxy import paused_playback_update


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Expose a media player with cover art and track metadata per Echo."""
    async_add_entities(
        AlexaNowPlaying(entry, key, device["name"])
        for key, device in entry.options.get(CONF_ALEXA_REGISTERED_DEVICES, {}).items()
    )


class AlexaNowPlaying(MediaPlayerEntity):
    """Mirror Plex Music skill playback; Alexa controls are not implemented yet."""

    _attr_has_entity_name = True
    _attr_name = "Now playing"
    _attr_supported_features = MediaPlayerEntityFeature(0)

    def __init__(self, entry: ConfigEntry, key: str, name: str) -> None:
        self._entry_id = entry.entry_id
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_alexa_{key}_now_playing"
        self._attr_state = MediaPlayerState.IDLE
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_alexa_{key}")},
            name=name,
            manufacturer="Amazon",
            model="Alexa device",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass,
            f"plex_music_alexa_status_{self._entry_id}_{self._key}",
            self._update_playback,
        ))
        restored = paused_playback_update(self.hass, self._entry_id, self._key)
        if restored:
            self._update_playback(restored)

    def _update_playback(self, update: dict | str) -> None:
        if isinstance(update, str):
            update = {"status": update}
        status = update.get("status")
        active = status in ("Playing", "Paused")
        self._attr_state = (
            MediaPlayerState.PLAYING if status == "Playing"
            else MediaPlayerState.PAUSED if status == "Paused"
            else MediaPlayerState.IDLE
        )
        self._attr_media_title = update.get("title") if active else None
        self._attr_media_artist = update.get("artist") if active else None
        self._attr_media_album_name = update.get("album") if active else None
        self._attr_media_image_url = update.get("artwork") if active else None
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)
