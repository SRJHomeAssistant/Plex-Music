"""Authenticated public Alexa skill endpoint for identifying Echo devices."""
from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlsplit

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .alexa_devices import discover_device, device_key, CONF_ALEXA_REGISTERED_DEVICES
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .alexa_intents import extract_identify_device_request, extract_track_request, requesting_device_id
from .alexa_playback import ask_for_music, play_response, stop_response
from .playback import resolve_music
from .voice_discovery import discover, selected_tracks, page_text, fresh, PAGE_SIZE, RESULT_LIFETIME
from .playback_db import read_history, record_played
from .voice_aliases import CONF_VOICE_ALIASES, resolve_voice_alias
from .alexa_security import validate_certificate_url, verify_alexa_request
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 32768
CERT_CACHE_SECONDS = 3600


def speech(text: str, keep_open: bool = False) -> dict:
    """Build a plain Alexa response for a custom intent."""
    return {"version": "1.0", "response": {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": not keep_open,
        **({"reprompt": {"outputSpeech": {"type": "PlainText", "text": "Say play number two, shuffle number two, more results, or cancel."}}} if keep_open else {}),
    }}


class PlexMusicAlexaView(HomeAssistantView):
    """Alexa skill requests do not use Home Assistant user tokens."""

    url = "/api/plex_music/alexa"
    name = "api:plex_music:alexa"
    requires_auth = False

    def __init__(self, hass, store):
        self.hass = hass
        self.store = store
        self._cert_cache = {}
        self._discovery = {}
        self._playback_warnings = {}
        self._last_playback_failures = {}

    async def post(self, request: web.Request) -> web.Response:
        if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY_BYTES, actual_size=request.content_length)
        raw = await request.read()
        if len(raw) > MAX_BODY_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY_BYTES, actual_size=len(raw))
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("Invalid request envelope")
            cert_url = validate_certificate_url(request.headers.get("SignatureCertChainUrl", ""))
            signature = request.headers["Signature"]
            cert = await self._get_certificate(cert_url)
        except (ValueError, KeyError, json.JSONDecodeError):
            raise web.HTTPBadRequest() from None
        for entry in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry, ConfigEntry):
                continue
            skill_id = entry.options.get("alexa_skill_id", "")
            if not skill_id:
                continue
            try:
                await self.hass.async_add_executor_job(
                    verify_alexa_request, raw, signature, cert, envelope, skill_id
                )
            except Exception:
                continue
            request_data = envelope.get("request", {})
            event_type = request_data.get("type", "")
            caller = requesting_device_id(envelope)
            registered = entry.options.get(CONF_ALEXA_REGISTERED_DEVICES, {})
            caller_key = device_key(caller) if caller else None
            async def persist_queue():
                from . import async_save_playback
                await async_save_playback(self.hass, entry.entry_id)

            def diagnostics(**changes):
                if caller_key and caller_key in registered:
                    self.hass.loop.call_soon_threadsafe(
                        async_dispatcher_send, self.hass,
                        f"plex_music_alexa_diagnostics_{entry.entry_id}_{caller_key}",
                        changes,
                    )
            diagnostics(request_type=event_type,
                        last_called=datetime.now(timezone.utc).isoformat())
            # Log request routing without recording utterances, slots or device IDs.
            if event_type in ("LaunchRequest", "IntentRequest") or event_type.startswith("PlaybackController."):
                intent_name = str(request_data.get("intent", {}).get("name") or "") if event_type == "IntentRequest" else ""
                _LOGGER.info("Plex Music Alexa request routing: type=%s intent=%s", event_type, intent_name or "-")
            if event_type == "System.ExceptionEncountered":
                error = request_data.get("error", {})
                _LOGGER.error("Alexa rejected skill response: %s: %s",
                              error.get("type"), error.get("message"))
                return web.json_response({"version": "1.0", "response": {}})
            if event_type.startswith("AudioPlayer."):
                diagnostics(last_alexa_event=event_type.removeprefix("AudioPlayer."))
                stream_token = request_data.get("token", "")
                if event_type in ("AudioPlayer.PlaybackStarted", "AudioPlayer.PlaybackFailed"):
                    _LOGGER.info("Plex Music Alexa stream event: event=%s token=%s", event_type, stream_token)
                queue_id, separator, position = stream_token.rpartition(":")
                queued = self.store.queue(queue_id) if separator else None
                if queued and caller_key == queued[1] and position.isdigit():
                    index = int(position)
                    tracks = queued[2]
                    state = self.store.current(caller_key) if caller_key else None
                    if state and state["queue_id"] == queue_id and event_type in (
                        "AudioPlayer.PlaybackStarted", "AudioPlayer.PlaybackResumed",
                        "AudioPlayer.PlaybackStopped", "AudioPlayer.PlaybackFinished",
                    ):
                        state["index"] = index
                        state["offset"] = max(0, int(request_data.get("offsetInMilliseconds", 0) or 0))
                        state["paused"] = event_type == "AudioPlayer.PlaybackStopped"
                        await persist_queue()
                    if index < len(tracks):
                        # The Alexa request has been signature-verified and its
                        # device/queue/token matched. Keep long sessions alive.
                        self.store.touch(caller_key, queue_id)
                        if event_type == "AudioPlayer.PlaybackFailed":
                            failed = tracks[index]
                            _LOGGER.error(
                                "Alexa music playback issue: song=%r artist=%r album=%r codec=%r container=%r error=%s",
                                failed.get("title"), failed.get("artist"), failed.get("album"),
                                failed.get("audio_codec"), failed.get("container"), request_data.get("error"),
                            )
                            error = request_data.get("error") or {}
                            error_type = str(error.get("type") or "unknown") if isinstance(error, dict) else "unknown"
                            diagnostics(stream_status=f"Alexa playback failed: {error_type}",
                                        failed_track=failed.get("title"),
                                        failed_codec=failed.get("audio_codec") or "unknown")
                            if caller_key and caller_key in registered:
                                self._last_playback_failures[(entry.entry_id, caller_key)] = {
                                    "echo_name": str(registered.get(caller_key, {}).get("name") or "Unknown Echo"),
                                    "title": str(failed.get("title") or "Unknown song"),
                                    "artist": str(failed.get("artist") or ""),
                                    "album": str(failed.get("album") or ""),
                                    "file_type": str(failed.get("audio_codec") or failed.get("container") or "unknown").upper(),
                                    "error_type": error_type,
                                }
                                self._playback_warnings[(entry.entry_id, caller_key)] = (
                                    f"Sorry, I couldn't play {failed.get('title') or 'that song'}. "
                                    "There was an audio playback problem. "
                                    "Please check the Plex Music logs for details."
                                )
                        if event_type == "AudioPlayer.PlaybackStarted":
                            started = tracks[index]
                            _LOGGER.info(
                                "Alexa playback started: title=%r artist=%r album=%r source_codec=%r source_container=%r",
                                started.get("title"), started.get("artist"), started.get("album"),
                                started.get("audio_codec"), started.get("container"),
                            )
                            if caller_key:
                                self._playback_warnings.pop((entry.entry_id, caller_key), None)
                        if event_type == "AudioPlayer.PlaybackStarted" and state and state["queue_id"] == queue_id:
                            played_key = str(tracks[index].get("key", ""))
                            if played_key:
                                await self.hass.async_add_executor_job(
                                    record_played, self.hass.data[DOMAIN]["_playback_db_path"],
                                    entry.entry_id, played_key
                                )
                        if (event_type == "AudioPlayer.PlaybackNearlyFinished"
                                and state and state["queue_id"] == queue_id
                                and index + 1 < len(tracks)):
                            return web.json_response(play_response(queue_id, tracks, index + 1, "ENQUEUE"))
                        status = {
                            "AudioPlayer.PlaybackStarted": "Playing",
                            "AudioPlayer.PlaybackResumed": "Playing",
                            "AudioPlayer.PlaybackStopped": "Paused",
                            "AudioPlayer.PlaybackFailed": "Idle",
                        }.get(event_type)
                        # A track finishing is not the end of a multi-track queue.
                        # Keep the display Playing until the next track starts.
                        if event_type == "AudioPlayer.PlaybackFinished" and index == len(tracks) - 1:
                            status = "Idle"
                        if status and caller_key in registered and state and state["queue_id"] == queue_id:
                            track = tracks[index]
                            if status == "Playing":
                                diagnostics(track=track.get("title"), artist=track.get("artist"),
                                            album=track.get("album"), source="Plex")
                            else:
                                diagnostics(track=None, artist=None, album=None,
                                            source=None, stream_status=None)
                            self.hass.loop.call_soon_threadsafe(async_dispatcher_send, self.hass, f"plex_music_alexa_status_{entry.entry_id}_{caller_key}", {
                                "status": status,
                                "title": track["title"] if status in ("Playing", "Paused") else None,
                                "artist": track["artist"] if status == "Playing" else None,
                                "album": track["album"] if status == "Playing" else None,
                                "artwork": track["artwork_url"] if status == "Playing" else None,
                            })
                return web.json_response({"version": "1.0", "response": {}})
            if event_type.startswith("PlaybackController."):
                action = {
                    "PlaybackController.PlayCommandIssued": "resume",
                    "PlaybackController.PauseCommandIssued": "pause",
                    "PlaybackController.NextCommandIssued": "next",
                    "PlaybackController.PreviousCommandIssued": "previous",
                }.get(event_type)
                state = self.store.current(caller_key) if caller_key else None
                if not action or not state or caller_key not in registered:
                    return web.json_response({"version": "1.0", "response": {}})
                queue_id = state["queue_id"]
                self.store.touch(caller_key, queue_id)
                tracks = self.store.queue(queue_id)[2]
                if action == "pause":
                    state["paused"] = True
                    await persist_queue()
                    return web.json_response(stop_response())
                if action == "resume":
                    state["paused"] = False
                    await persist_queue()
                    result = play_response(queue_id, tracks, state["index"], offset=state["offset"])
                else:
                    index = max(0, state["index"] + (1 if action == "next" else -1))
                    if index >= len(tracks):
                        return web.json_response({"version": "1.0", "response": {}})
                    state.update(index=index, offset=0, paused=False)
                    await persist_queue()
                    result = play_response(queue_id, tracks, index)
                return web.json_response(result)
            device_id = extract_identify_device_request(envelope)
            if device_id is not None:
                updated = discover_device(dict(entry.options), device_id)
                if updated != dict(entry.options):
                    self.hass.config_entries.async_update_entry(entry, options=updated)
                return web.json_response(speech(
                    "Device identified. Open Plex Music in Home Assistant to give this Echo a name."
                ))
            # Failure history is queried explicitly; don't interrupt ordinary skill launches.
            if event_type == "IntentRequest":
                intent = request_data.get("intent", {})
                name = intent.get("name")
                diagnostics(intent=name)
                # The broad legacy Play/Shuffle search-query slots can capture
                # "number two" before Alexa chooses a discovery selection intent.
                if name in ("PlayTrackIntent", "ShuffleIntent") and caller_key:
                    spoken_slot = str((intent.get("slots", {}).get("track") or {}).get("value") or "").strip()
                    match = re.fullmatch(r"(?:number|option|choice)\\s+(\\d+|one|two|three|four|five)", spoken_slot, re.I)
                    if match and fresh(self._discovery.get((entry.entry_id, caller_key))):
                        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                        value = match.group(1).casefold()
                        intent = {"slots": {"number": {"value": str(words.get(value, value))}}}
                        name = "ShuffleDiscoveryIntent" if name == "ShuffleIntent" else "PlayDiscoveryIntent"
                if name in ("AMAZON.CancelIntent", "AMAZON.StopIntent") and caller_key:
                    if fresh(self._discovery.get((entry.entry_id, caller_key))):
                        self._discovery.pop((entry.entry_id, caller_key), None)
                        return web.json_response({"version": "1.0", "response": {"shouldEndSession": True}})
                if name == "WhyDidntPlayIntent":
                    if not caller_key or caller_key not in registered:
                        return web.json_response(speech("Please identify this Echo in Plex Music first."))
                    failure = self._last_playback_failures.get((entry.entry_id, caller_key))
                    if not failure:
                        return web.json_response(speech("I haven't recorded a playback failure on this Echo since Plex Music last started."))
                    answer = f"On {failure['echo_name']}, the last song that failed was {failure['title']}"
                    if failure["artist"]:
                        answer += f" by {failure['artist']}"
                    if failure["album"]:
                        answer += f", from the album {failure['album']}"
                    answer += f". Source file type: {failure['file_type']}."
                    answer += " Alexa reported a playback error. The file type is not necessarily unsupported. Check the Plex Music logs for the cause."
                    return web.json_response(speech(answer))
                if name == "WhatsPlayingIntent":
                    if not caller_key or caller_key not in registered:
                        return web.json_response(speech("Please identify this Echo in Plex Music first."))
                    state = self.store.current(caller_key)
                    queued = self.store.queue(state["queue_id"]) if state else None
                    if not queued or not queued[2] or state["index"] >= len(queued[2]):
                        return web.json_response(speech("Plex Music is not playing anything on this Echo."))
                    track = queued[2][state["index"]]
                    title = str(track.get("title") or "an unknown song")
                    artist = str(track.get("artist") or "an unknown artist")
                    album = str(track.get("album") or "")
                    answer = f"That's {title} by {artist}"
                    if album:
                        answer += f", from the album {album}"
                    if state.get("paused"):
                        answer = "Paused on " + answer.removeprefix("That's ")
                    return web.json_response(speech(answer + "."))
                actions = {
                    "PausePlaybackIntent": "pause", "ResumePlaybackIntent": "resume",
                    "AMAZON.PauseIntent": "pause", "AMAZON.ResumeIntent": "resume",
                    "NextTrackIntent": "next", "PreviousTrackIntent": "previous",
                    "AMAZON.NextIntent": "next", "AMAZON.PreviousIntent": "previous",
                    "StopPlaybackIntent": "stop", "AMAZON.StopIntent": "stop",
                    "AMAZON.CancelIntent": "stop",
                }
                if name in actions:
                    if not caller_key or caller_key not in registered:
                        if actions[name] == "stop" or name == "AMAZON.PauseIntent":
                            return web.json_response({"version": "1.0", "response": {"shouldEndSession": True}})
                        return web.json_response(speech("Please identify this Echo in Plex Music first."))
                    if name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
                        self._discovery.pop((entry.entry_id, caller_key), None)
                    action = actions[name]
                    state = self.store.current(caller_key)
                    if action == "stop":
                        self.store.active.pop(caller_key, None)
                        await persist_queue()
                        diagnostics(track=None, artist=None, album=None,
                                    source=None, stream_status=None)
                        self.hass.loop.call_soon_threadsafe(
                            async_dispatcher_send, self.hass,
                            f"plex_music_alexa_status_{entry.entry_id}_{caller_key}",
                            {"status": "Idle"},
                        )
                        return web.json_response(stop_response())
                    if not state:
                        # Alexa can route native stop as a pause to a recently used skill.
                        # Never speak or alter another Echo\'s queue for an idle caller.
                        if name == "AMAZON.PauseIntent":
                            return web.json_response(stop_response())
                        return web.json_response(speech("There is no Plex Music playback to control."))
                    queue_id = state["queue_id"]
                    self.store.touch(caller_key, queue_id)
                    tracks = self.store.queue(queue_id)[2]
                    if action == "pause":
                        state["paused"] = True
                        await persist_queue()
                        return web.json_response(stop_response())
                    if action == "resume":
                        state["paused"] = False
                        await persist_queue()
                        return web.json_response(play_response(
                            queue_id, tracks, state["index"], offset=state["offset"]
                        ))
                    index = state["index"] + (1 if action == "next" else -1)
                    index = max(0, index)
                    if index >= len(tracks):
                        return web.json_response(speech("You have reached the end of the queue."))
                    state.update(index=index, offset=0, paused=False)
                    await persist_queue()
                    return web.json_response(play_response(queue_id, tracks, index))
                if name in ("FindAlbumsIntent", "FindSongsIntent"):
                    if not caller_key or caller_key not in registered:
                        return web.json_response(speech("Please identify this Echo in Plex Music first."))
                    slot_name = "artist" if name == "FindAlbumsIntent" else "song"
                    query = str((intent.get("slots", {}).get(slot_name) or {}).get("value") or "").strip()[:200]
                    if not query:
                        return web.json_response(speech("Tell me which artist or song to find."))
                    kind = "album" if name == "FindAlbumsIntent" else "track"
                    try:
                        results = await self.hass.async_add_executor_job(
                            discover, dict(entry.data), dict(entry.options), query, kind
                        )
                    except Exception:
                        _LOGGER.exception("Plex Music voice discovery failed")
                        return web.json_response(speech("I couldn't search your Plex music library."))
                    if not results:
                        self._discovery.pop((entry.entry_id, caller_key), None)
                        return web.json_response(speech("I couldn't find any matching music in Plex."))
                    self._discovery[(entry.entry_id, caller_key)] = {
                        "results": results, "offset": 0,
                        "expires": monotonic() + RESULT_LIFETIME,
                    }
                    label = "albums" if kind == "album" else "songs"
                    intro = f"I found {len(results)} matching {label}. "
                    if len(results) == 50:
                        intro = "Here are the first 50 matches. "
                    return web.json_response(speech(intro + page_text(results, 0), keep_open=True))
                if name in ("PlayDiscoveryIntent", "ShuffleDiscoveryIntent", "MoreDiscoveryIntent", "RepeatDiscoveryIntent"):
                    if not caller_key or caller_key not in registered:
                        return web.json_response(speech("Please identify this Echo in Plex Music first."))
                    key = (entry.entry_id, caller_key)
                    browsing = self._discovery.get(key)
                    if not fresh(browsing):
                        self._discovery.pop(key, None)
                        return web.json_response(speech("Your search has expired. Ask me to find albums or songs again."))
                    results = browsing["results"]
                    offset = browsing["offset"]
                    browsing["expires"] = monotonic() + RESULT_LIFETIME
                    if name == "MoreDiscoveryIntent":
                        if offset + PAGE_SIZE >= len(results):
                            return web.json_response(speech("Those are all the results. " + page_text(results, offset), keep_open=True))
                        offset += PAGE_SIZE
                        browsing["offset"] = offset
                        return web.json_response(speech(page_text(results, offset), keep_open=True))
                    if name == "RepeatDiscoveryIntent":
                        return web.json_response(speech(page_text(results, offset), keep_open=True))
                    slots = intent.get("slots", {})
                    raw_number = str((slots.get("number") or {}).get("value") or "")
                    try:
                        number = int(raw_number)
                    except (TypeError, ValueError):
                        number = 0
                    if number < 1 or number > min(PAGE_SIZE, len(results) - offset):
                        return web.json_response(speech("Choose a number from the results I just read. " + page_text(results, offset), keep_open=True))
                    choice = results[offset + number - 1]
                    shuffle = name == "ShuffleDiscoveryIntent"
                    try:
                        tracks = await self.hass.async_add_executor_job(
                            selected_tracks, dict(entry.data), dict(entry.options), choice, shuffle
                        )
                    except Exception:
                        _LOGGER.exception("Plex Music discovery selection failed")
                        return web.json_response(speech("I couldn't load that selection from Plex."))
                    if not tracks:
                        return web.json_response(speech("That selection has no playable tracks. Choose another number.", keep_open=True))
                    endpoint = entry.options.get("alexa_endpoint_url", "")
                    parsed = urlsplit(endpoint)
                    base_url = f"https://{parsed.netloc}" if parsed.scheme == "https" and parsed.hostname and parsed.port in (None, 443) else ""
                    if not base_url:
                        return web.json_response(speech("A public HTTPS address is required for playback."))
                    if shuffle:
                        history = await self.hass.async_add_executor_job(
                            read_history, self.hass.data[DOMAIN]["_playback_db_path"], entry.entry_id
                        )
                        random.SystemRandom().shuffle(tracks)
                        if len(tracks) > 1:
                            rank = {key: pos for pos, key in enumerate(history)}
                            first = max(range(len(tracks)), key=lambda i: rank.get(
                                str(tracks[i].get("key", "")), len(history)))
                            tracks[0], tracks[first] = tracks[first], tracks[0]
                    self._discovery.pop(key, None)
                    queue_id, queue = self.store.create(entry, caller_key, tracks, base_url)
                    await persist_queue()
                    first_track = queue[0]
                    _LOGGER.info(
                        "Plex Music Alexa playback requested: mode=%s tracks=%d first_title=%r first_artist=%r first_key=%r",
                        "shuffle" if shuffle else "play", len(queue), first_track.get("title"),
                        first_track.get("artist"), first_track.get("key"),
                    )
                    return web.json_response(play_response(queue_id, queue))
                if name in ("PlayTrackIntent", "PlayAlbumIntent", "PlaySongIntent", "PlayArtistIntent", "ShuffleIntent", "ShuffleAlbumIntent"):
                    slot_name = {"PlayAlbumIntent": "album", "PlaySongIntent": "song",
                                 "PlayArtistIntent": "artist", "ShuffleIntent": "track",
                                 "ShuffleAlbumIntent": "album"}.get(name)
                    spoken = (str((intent.get("slots", {}).get(slot_name) or {}).get("value") or "").strip()[:200]
                              if slot_name else extract_track_request(envelope))
                    if not spoken:
                        return web.json_response(ask_for_music())
                    if not caller_key or caller_key not in registered:
                        return web.json_response(speech("Please identify this Echo in Plex Music first."))
                    self.hass.loop.call_soon_threadsafe(
                        async_dispatcher_send,
                        self.hass,
                        f"plex_music_alexa_heard_{entry.entry_id}_{caller_key}",
                        spoken,
                    )
                    resolved = resolve_voice_alias(spoken, entry.options.get(CONF_VOICE_ALIASES, {}))
                    diagnostics(requested_music=spoken, plex_search=resolved,
                                search_result="Searching", source="Plex")
                    match_signal = f"plex_music_alexa_match_{entry.entry_id}_{caller_key}"
                    def report_match(status, tracks=None, error=None):
                        first = tracks[0] if tracks else {}
                        details = {
                            "status": status, "heard": spoken, "resolved_query": resolved,
                            "alias_applied": resolved != spoken, "match_count": len(tracks or []),
                            "artist": first.get("artist"), "album": first.get("album"),
                            "track": first.get("title"), "error": error,
                        }
                        self.hass.loop.call_soon_threadsafe(
                            async_dispatcher_send, self.hass, match_signal, details
                        )
                    _LOGGER.info("Plex Music match request: heard=%r, resolved=%r, alias=%s",
                                 spoken, resolved, resolved != spoken)
                    try:
                        tracks, resolved_kind = await self.hass.async_add_executor_job(
                            resolve_music, dict(entry.data), dict(entry.options), spoken,
                            {"PlayAlbumIntent": "album", "PlaySongIntent": "track",
                             "PlayArtistIntent": "artist", "ShuffleAlbumIntent": "album"}.get(name), True
                        )
                    except Exception:
                        diagnostics(search_result="Search error")
                        report_match("Error", error="Plex catalogue lookup failed")
                        _LOGGER.exception("Plex Music playback catalogue lookup failed")
                        return web.json_response(speech("I couldn't access your Plex music library."))
                    if not tracks:
                        diagnostics(search_result="Not found")
                        report_match("Not found")
                        return web.json_response(speech("I couldn't find that music in Plex."))
                    endpoint = entry.options.get("alexa_endpoint_url", "")
                    parsed = urlsplit(endpoint)
                    base_url = f"https://{parsed.netloc}" if parsed.scheme == "https" and parsed.hostname and parsed.port in (None, 443) else ""
                    _LOGGER.info("Plex Music resolved %d tracks for Alexa playback", len(tracks))
                    if not base_url:
                        return web.json_response(speech("A public HTTPS address is required for playback."))
                    if name in ("ShuffleIntent", "ShuffleAlbumIntent"):
                        history = await self.hass.async_add_executor_job(
                            read_history, self.hass.data[DOMAIN]["_playback_db_path"],
                            entry.entry_id
                        )
                        random.SystemRandom().shuffle(tracks)
                        if len(tracks) > 1:
                            # Start with the least recently played available track.
                            # Never repeat the most recent track if alternatives exist.
                            rank = {key: pos for pos, key in enumerate(history)}
                            first = max(range(len(tracks)), key=lambda i: rank.get(
                                str(tracks[i].get("key", "")), len(history)))
                            tracks[0], tracks[first] = tracks[first], tracks[0]
                    diagnostics(search_result=f"{len(tracks)} Plex track(s) found",
                                artist=tracks[0].get("artist"), album=tracks[0].get("album"),
                                track=tracks[0].get("title"), stream_status="Awaiting stream")
                    report_match("Matched", tracks)
                    queue_id, queue = self.store.create(entry, caller_key, tracks, base_url)
                    await persist_queue()
                    first_track = queue[0]
                    _LOGGER.info(
                        "Plex Music Alexa playback requested: mode=%s tracks=%d first_title=%r first_artist=%r first_key=%r",
                        "shuffle" if name == "ShuffleIntent" else "play", len(queue), first_track.get("title"),
                        first_track.get("artist"), first_track.get("key"),
                    )
                    return web.json_response(play_response(queue_id, queue))
            _LOGGER.warning("Plex Music Alexa request fell through to generic prompt: type=%s intent=%s",
                            event_type, str(request_data.get("intent", {}).get("name") or "-"))
            return web.json_response(speech("Say play followed by an artist, album or track."))
        _LOGGER.warning("Rejected unauthenticated or unrecognised Alexa skill request")
        raise web.HTTPForbidden()

    async def _get_certificate(self, url: str) -> bytes:
        from time import monotonic
        cached = self._cert_cache.get(url)
        if cached and cached[0] > monotonic():
            return cached[1]
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, allow_redirects=False, timeout=10) as response:
                if response.status != 200 or response.content_length and response.content_length > 65536:
                    raise ValueError("Unable to fetch Alexa certificate")
                cert = await response.content.read(65537)
                if len(cert) > 65536:
                    raise ValueError("Alexa certificate too large")
        except Exception as exc:
            raise web.HTTPBadRequest() from exc
        self._cert_cache[url] = (monotonic() + CERT_CACHE_SECONDS, cert)
        return cert
