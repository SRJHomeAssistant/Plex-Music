"""Plex Music: authorised server, library selection and catalogue search."""

from __future__ import annotations

import logging
import asyncio
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .catalog import search_music
from .alexa_http import PlexMusicAlexaView
from .media_proxy import PlaybackStore, PlexMusicMediaView
from .playback_db import initialise, read_entry, write_entry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SEARCH_SCHEMA = vol.Schema({
    vol.Required("query"): vol.All(str, vol.Length(min=1, max=200)),
    vol.Optional("kind", default="track"): vol.In(("artist", "album", "track")),
    vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the server and a read-only music search action."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    if not hass.data[DOMAIN].get("_playback_db_ready"):
        db_path = hass.config.path("plex_music_playback.sqlite3")
        await hass.async_add_executor_job(initialise, db_path)
        hass.data[DOMAIN]["_playback_db_path"] = db_path
        hass.data[DOMAIN]["_playback_db_lock"] = asyncio.Lock()
        hass.data[DOMAIN]["_playback_db_ready"] = True

    if not hass.data[DOMAIN].get("_alexa_view_registered"):
        store = PlaybackStore()
        hass.data[DOMAIN]["_playback_store"] = store
        hass.http.register_view(PlexMusicAlexaView(hass, store))
        hass.http.register_view(PlexMusicMediaView(hass, store))
        hass.data[DOMAIN]["_alexa_view_registered"] = True

    store = hass.data[DOMAIN]["_playback_store"]
    saved = await hass.async_add_executor_job(
        read_entry, hass.data[DOMAIN]["_playback_db_path"], entry.entry_id
    )
    endpoint = urlsplit(entry.options.get("alexa_endpoint_url", ""))
    base_url = (
        f"https://{endpoint.netloc}"
        if endpoint.scheme == "https" and endpoint.hostname and endpoint.port in (None, 443)
        else ""
    )
    registered = entry.options.get("alexa_registered_devices", {})
    if base_url:
        for state in saved:
            if state["device_key"] in registered:
                store.restore(entry, state["device_key"], state["tracks"], base_url,
                              state["index"], state["offset"], state["paused"],
                              queue_id=state.get("queue_id"))
        _LOGGER.info("Restored %d Plex Music playback queues for entry %s",
                     len(saved), entry.entry_id)

    if not hass.services.has_service(DOMAIN, "search_music"):

        async def handle_search(call: ServiceCall) -> dict:
            """Search all connected Plex servers' selected music libraries."""
            results = []
            for configured in hass.data.get(DOMAIN, {}).values():
                if not isinstance(configured, ConfigEntry):
                    continue
                try:
                    found = await hass.async_add_executor_job(
                        search_music,
                        dict(configured.data),
                        dict(configured.options),
                        call.data["query"],
                        call.data["kind"],
                        call.data["limit"],
                    )
                except Exception as exc:
                    _LOGGER.warning("Plex Music catalogue search failed: %s", type(exc).__name__)
                    raise HomeAssistantError(
                        "Unable to search Plex music. Check the server connection and selected libraries."
                    ) from exc
                results.extend(found)
            return {"results": results, "count": len(results)}

        hass.services.async_register(
            DOMAIN,
            "search_music",
            handle_search,
            schema=SEARCH_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    # Remove legacy read-only Now playing entities from the entity registry.
    registry = er.async_get(hass)
    for key in registered:
        unique_id = f"{entry.entry_id}_alexa_{key}_now_playing"
        entity_id = registry.async_get_entity_id("media_player", DOMAIN, unique_id)
        if entity_id:
            registry.async_remove(entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recreate device sensors after registering, renaming or deleting Echos."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one server; remove the action when no servers remain."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
    if not unloaded:
        return False
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if not any(isinstance(value, ConfigEntry) for value in hass.data.get(DOMAIN, {}).values()):
        hass.services.async_remove(DOMAIN, "search_music")
    return True


async def async_save_playback(hass: HomeAssistant, entry_id: str) -> None:
    """Serialize snapshots to SQLite without blocking Home Assistant's event loop."""
    data = hass.data[DOMAIN]
    async with data["_playback_db_lock"]:
        snapshot = data["_playback_store"].snapshot(entry_id)
        await hass.async_add_executor_job(
            write_entry, data["_playback_db_path"], entry_id, snapshot
        )
