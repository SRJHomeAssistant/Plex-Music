"""Voice discovery of albums and songs in selected Plex music libraries."""
from __future__ import annotations

import time

from plexapi.server import PlexServer

from .const import CONF_MUSIC_LIBRARIES, CONF_PLEX_TOKEN, CONF_PLEX_URL
from .playback import _comparable, _candidate_queries, _tracks
from .voice_aliases import CONF_VOICE_ALIASES, resolve_voice_alias

PAGE_SIZE = 5
MAX_RESULTS = 50
RESULT_LIFETIME = 300


def _sections(server, options):
    selected = options.get(CONF_MUSIC_LIBRARIES)
    return [s for s in server.library.sections()
            if s.type == "artist" and (selected is None or str(s.key) in selected)]


def discover(data: dict, options: dict, query: str, kind: str) -> list[dict]:
    """Return exact artist albums or exact song-title matches, with stable IDs."""
    query = resolve_voice_alias(query.strip(), options.get(CONF_VOICE_ALIASES, {}))
    server = PlexServer(data[CONF_PLEX_URL], data[CONF_PLEX_TOKEN])
    found, seen = [], set()
    for section in _sections(server, options):
        if kind == "album":
            artists = []
            for candidate in _candidate_queries(query):
                artists = section.search(title=candidate, libtype="artist", maxresults=50)
                if any(_comparable(str(a.title)) == _comparable(query) for a in artists):
                    break
            for artist in artists:
                if _comparable(str(artist.title)) != _comparable(query):
                    continue
                for album in artist.albums():
                    identity = (str(section.key), str(album.ratingKey))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    found.append({"library_id": str(section.key),
                                  "rating_key": str(album.ratingKey),
                                  "title": str(album.title), "artist": str(artist.title),
                                  "kind": "album"})
                    if len(found) >= MAX_RESULTS:
                        return found
        elif kind == "track":
            matches = []
            for candidate in _candidate_queries(query):
                matches = section.search(title=candidate, libtype="track", maxresults=MAX_RESULTS)
                if any(_comparable(str(t.title)) == _comparable(query) for t in matches):
                    break
            for track in matches:
                if _comparable(str(track.title)) != _comparable(query):
                    continue
                identity = (str(section.key), str(track.ratingKey))
                if identity in seen:
                    continue
                seen.add(identity)
                found.append({"library_id": str(section.key),
                              "rating_key": str(track.ratingKey),
                              "title": str(track.title),
                              "artist": str(getattr(track, "grandparentTitle", "") or ""),
                              "kind": "track"})
                if len(found) >= MAX_RESULTS:
                    return found
    return found


def selected_tracks(data: dict, options: dict, choice: dict, shuffle: bool) -> list[dict]:
    """Resolve an already-discovered item by its Plex ID, not a fuzzy title."""
    server = PlexServer(data[CONF_PLEX_URL], data[CONF_PLEX_TOKEN])
    section = next((s for s in _sections(server, options)
                    if str(s.key) == choice["library_id"]), None)
    if section is None:
        return []
    item = section.fetchItem(int(choice["rating_key"]))
    kind = choice["kind"]
    # Shuffling a single song means shuffling the album containing that song.
    if kind == "track" and shuffle:
        parent = item.album()
        if parent is not None:
            item, kind = parent, "album"
    result = []
    for track in _tracks(item, kind):
        media = getattr(track, "media", [])
        parts = getattr(media[0], "parts", []) if media else []
        if not parts or not getattr(parts[0], "key", None):
            continue
        result.append({
            "key": str(track.ratingKey), "part": str(parts[0].key),
            "title": str(track.title),
            "artist": str(getattr(track, "grandparentTitle", "") or ""),
            "album": str(getattr(track, "parentTitle", "") or ""),
            "thumb": str(getattr(track, "thumb", "") or
                         getattr(track, "parentThumb", "") or ""),
            "duration": int(getattr(track, "duration", 0) or 0),
        })
    return result


def page_text(results: list[dict], offset: int) -> str:
    """Speak at most five choices, numbered within the current page."""
    page = results[offset:offset + PAGE_SIZE]
    parts = []
    for number, item in enumerate(page, 1):
        label = item["title"]
        if item["kind"] == "track":
            label += " by " + item["artist"]
        parts.append(f"Number {number}, {label}.")
    more = " Say more results to hear the next five." if offset + PAGE_SIZE < len(results) else ""
    return " ".join(parts) + more + " Say play number or shuffle number, followed by your choice."


def fresh(state: dict | None) -> bool:
    return bool(state and state.get("expires", 0) > time.monotonic())
