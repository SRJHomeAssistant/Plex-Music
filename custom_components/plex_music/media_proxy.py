"""Temporary opaque playback URLs and Plex-to-Alexa HTTPS proxy."""
from __future__ import annotations

import secrets
import logging
import time
import re
from urllib.parse import urlsplit, urlencode

from aiohttp import ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import CONF_PLEX_TOKEN, CONF_PLEX_URL

_LOGGER = logging.getLogger(__name__)
TOKEN_LIFETIME = 4 * 3600


class PlaybackStore:
    """Ephemeral queue and signed-by-randomness stream tokens (never Plex tokens)."""

    def __init__(self):
        self.items = {}
        self.queues = {}
        self.active = {}

    def create(self, entry, device_key: str, tracks: list[dict], base_url: str,
               queue_id: str | None = None):
        queue_id = queue_id or secrets.token_urlsafe(24)
        queue = []
        for track in tracks:
            audio_token = secrets.token_urlsafe(32)
            artwork_token = secrets.token_urlsafe(32) if track.get("thumb") else None
            expiry = time.monotonic() + TOKEN_LIFETIME
            self.items[audio_token] = (expiry, entry, track, "audio")
            if artwork_token:
                self.items[artwork_token] = (expiry, entry, track, "artwork")
            queue.append({
                **track,
                "_entry_id": entry.entry_id,
                "audio_url": f"{base_url}/api/plex_music/media/{audio_token}",
                "artwork_url": f"{base_url}/api/plex_music/media/{artwork_token}" if artwork_token else None,
            })
        self.queues[queue_id] = (time.monotonic() + TOKEN_LIFETIME, device_key, queue)
        self.active[device_key] = {"queue_id": queue_id, "index": 0, "offset": 0, "paused": False}
        return queue_id, queue

    def restore(self, entry, device_key: str, tracks: list[dict],
                base_url: str, index: int, offset: int, paused: bool,
                queue_id: str | None = None):
        """Regenerate ephemeral stream URLs while retaining the saved queue."""
        if not tracks or index < 0 or index >= len(tracks):
            return
        queue_id, _ = self.create(entry, device_key, tracks, base_url, queue_id=queue_id)
        self.active[device_key].update(
            index=index, offset=max(0, offset), paused=paused
        )
        return queue_id

    def snapshot(self, entry_id: str) -> list[dict]:
        """Return only durable metadata, never signed URLs or Plex credentials."""
        rows = []
        for key, state in self.active.items():
            queued = self.queue(state["queue_id"])
            if not queued:
                continue
            tracks = []
            for track in queued[2]:
                if track.get("_entry_id") != entry_id:
                    continue
                tracks.append({
                    field: value for field, value in track.items()
                    if field not in ("audio_url", "artwork_url", "_entry_id")
                })
            if tracks and 0 <= state["index"] < len(tracks):
                rows.append({
                    "device_key": key, "queue_id": state["queue_id"], "tracks": tracks,
                    "index": state["index"], "offset": state["offset"],
                    "paused": state["paused"],
                })
        return rows

    def current(self, device_key: str):
        state = self.active.get(device_key)
        if not state or not self.queue(state["queue_id"]):
            self.active.pop(device_key, None)
            return None
        return state

    def get(self, token: str):
        item = self.items.get(token)
        if item is None or item[0] <= time.monotonic():
            self.items.pop(token, None)
            return None
        return item

    def queue(self, queue_id: str):
        value = self.queues.get(queue_id)
        if value is None or value[0] <= time.monotonic():
            self.queues.pop(queue_id, None)
            return None
        return value


def paused_playback_update(hass, entry_id: str, device_key: str) -> dict | None:
    """Return restored paused track details for one registered Echo, if any."""
    store = hass.data.get("plex_music", {}).get("_playback_store")
    if store is None:
        return None
    state = store.current(device_key)
    if not state or not state["paused"]:
        return None
    queued = store.queue(state["queue_id"])
    if not queued or queued[1] != device_key:
        return None
    tracks = queued[2]
    index = state["index"]
    if not 0 <= index < len(tracks) or tracks[index].get("_entry_id") != entry_id:
        return None
    track = tracks[index]
    return {
        "status": "Paused",
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "artwork": track.get("artwork_url"),
    }


class PlexMusicMediaView(HomeAssistantView):
    """Proxy audio and artwork to Alexa without exposing the Plex token."""

    url = "/api/plex_music/media/{token}"
    name = "api:plex_music:media"
    requires_auth = False

    def __init__(self, hass, store: PlaybackStore):
        self.hass = hass
        self.store = store

    async def get(self, request: web.Request, token: str):
        item = self.store.get(token)
        if item is None:
            _LOGGER.warning("Plex Music stream request rejected: expired or unknown token")
            raise web.HTTPNotFound()
        _, entry, track, kind = item
        def stream_diagnostic(value):
            if kind == "audio":
                for device, state in self.store.active.items():
                    queued = self.store.queue(state["queue_id"])
                    if queued and any(
                        t.get("key") == track.get("key") for t in queued[2]
                    ):
                        self.hass.loop.call_soon_threadsafe(
                            async_dispatcher_send, self.hass,
                            f"plex_music_alexa_diagnostics_{entry.entry_id}_{device}",
                            {"stream_status": value},
                        )
        transcode = False
        base = entry.data[CONF_PLEX_URL].rstrip("/")
        if kind == "artwork":
            path = track["thumb"]
            if not path.startswith("/") or path.startswith("//"):
                raise web.HTTPNotFound()
            url = base + path
        else:
            # Recovered Alexa Audio Player uses the original Plex media part,
            # not the universal music transcoder (which returned HTTP 400).
            path = track.get("part", "")
            if not isinstance(path, str) or not path.startswith("/library/parts/"):
                _LOGGER.error("Plex Music missing a valid media-part path")
                stream_diagnostic("Invalid Plex media part")
                raise web.HTTPBadGateway()
            parsed = urlsplit(path)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith("/library/parts/"):
                raise web.HTTPBadGateway()
            codec = str(track.get("audio_codec") or "").lower()
            container = str(track.get("container") or "").lower()
            transcode = codec not in ("mp3", "mpeg") or container not in ("mp3", "")
            if transcode:
                media_key = str(track.get("key") or "")
                if not media_key.isdigit():
                    stream_diagnostic("Invalid Plex metadata key")
                    raise web.HTTPBadGateway()
                params = {
                    "path": f"/library/metadata/{media_key}",
                    "protocol": "http",
                    "directPlay": "0",
                    "directStream": "0",
                    "directStreamAudio": "0",
                    "mediaIndex": "0",
                    "partIndex": "0",
                    "musicBitrate": "256",
                    "X-Plex-Platform": "Generic",
                    "X-Plex-Product": "Plex Music Alexa",
                    "X-Plex-Client-Identifier": "homeassistant-plex-music-alexa",
                    "X-Plex-Client-Profile-Extra": (
                        "add-transcode-target(type=musicProfile&context=streaming"
                        "&protocol=http&container=mp3&audioCodec=mp3)"
                    ),
                }
                url = base + "/music/:/transcode/universal/start.mp3?" + urlencode(params)
                stream_diagnostic(f"Plex MP3 transcode requested ({codec or container or 'unknown'})")
                _LOGGER.info("Plex Music transcode requested: title=%r codec=%s container=%s",
                             track.get("title"), codec, container)
            else:
                url = base + path
                stream_diagnostic("Direct MP3 requested")
        headers = {"X-Plex-Token": entry.data[CONF_PLEX_TOKEN]}
        if kind == "audio" and not transcode and request.headers.get("Range"):
            requested_range = request.headers["Range"]
            if not re.fullmatch(r"bytes=(?:[0-9]+-[0-9]*|-[0-9]+)", requested_range):
                raise web.HTTPBadRequest()
            headers["Range"] = requested_range
        session = async_get_clientsession(self.hass)
        try:
            upstream = await session.get(url, headers=headers, timeout=ClientTimeout(total=None, sock_connect=10, sock_read=60))
        except Exception as exc:
            stream_diagnostic(f"Connection error: {type(exc).__name__}")
            _LOGGER.error("Plex Music upstream %s connection failed: %s", kind, type(exc).__name__)
            raise web.HTTPBadGateway() from None
        stream_diagnostic(f"Plex HTTP {upstream.status}")
        if upstream.status == 416:
            upstream.release()
            raise web.HTTPRequestRangeNotSatisfiable()
        if upstream.status not in (200, 206):
            _LOGGER.error("Plex Music upstream %s returned HTTP %s (media key=%s)", kind, upstream.status, track.get("key") if kind == "audio" else "artwork")
            upstream.release()
            raise web.HTTPBadGateway()
        response_headers = {
            "Content-Type": "audio/mpeg" if kind == "audio" else upstream.headers.get("Content-Type", "image/jpeg"),
            "Cache-Control": "private, no-store",
            **({"Accept-Ranges": "bytes"} if not transcode else {}),
            "X-Content-Type-Options": "nosniff",
        }
        if kind == "audio":
            if transcode:
                upstream_type = upstream.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if upstream_type not in ("audio/mpeg", "audio/mp3", "application/octet-stream"):
                    _LOGGER.error("Plex Music transcode returned unexpected content type %r for %r",
                                  upstream_type, track.get("title"))
                    stream_diagnostic("Plex transcode returned non-MP3 response")
                    upstream.release()
                    raise web.HTTPBadGateway()
                stream_diagnostic(f"Plex MP3 transcode HTTP {upstream.status}")
            else:
                stream_diagnostic(f"Direct MP3 HTTP {upstream.status}")
        for header in ("Content-Length", "Content-Range"):
            if not transcode and header in upstream.headers:
                response_headers[header] = upstream.headers[header]
        if kind == "audio":
            _LOGGER.info(
                "Plex Music stream: title=%r artist=%r album=%r source_codec=%r "
                "source_container=%r mode=%s output_type=%s plex_http=%s",
                track.get("title"), track.get("artist"), track.get("album"),
                track.get("audio_codec"), track.get("container"),
                "plex_transcode" if transcode else "direct",
                response_headers["Content-Type"], upstream.status,
            )
        response = web.StreamResponse(status=upstream.status, headers=response_headers)
        try:
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(65536):
                await response.write(chunk)
            await response.write_eof()
        except (ConnectionError, OSError):
            pass
        finally:
            upstream.release()
        return response
