"""Resolve spoken requests to Plex tracks and queues."""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import threading
import time
import unicodedata
from plexapi.server import PlexServer

from .const import CONF_MUSIC_LIBRARIES, CONF_PLEX_TOKEN, CONF_PLEX_URL
from .voice_aliases import CONF_VOICE_ALIASES, resolve_voice_alias

MAX_QUEUE = 100
INDEX_TTL_SECONDS = 300
_INDEX_LOCK = threading.RLock()
_TRACK_INDEX = {}

_APOSTROPHES = "\u2018\u2019\u02bc\u00b4\u0060\uff07"
_APOSTROPHE_MAP = str.maketrans({ch: "'" for ch in _APOSTROPHES})


def _comparable(value: str) -> str:
    """Compare titles across Unicode punctuation and common speech variants."""
    value = unicodedata.normalize("NFKD", value).translate(_APOSTROPHE_MAP).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\s*[&+]\s*", " and ", value)
    return " ".join(re.findall(r"\w+", value))


# Small Roman numerals commonly used in album titles (for example Frozen II).
# Keep this limited: Roman-looking words in artist/title names must not be
# broadly interpreted as numbers, and exact title matches take priority.
_ROMAN_ALBUM_NUMBERS = {"i": "1", "ii": "2", "iii": "3", "iv": "4",
                        "v": "5", "vi": "6", "vii": "7", "viii": "8",
                        "ix": "9", "x": "10"}


def _album_number_key(value: str) -> str:
    """Normalise standalone decimal/Roman numerals for album-title fallback."""
    words = _comparable(value).split()
    return " ".join(_ROMAN_ALBUM_NUMBERS.get(word, word) for word in words)


def _album_number_matches(section, query: str) -> list:
    """Match numeral variants, including uniquely named album subtitle variants.

    Prefer an entire-title match over a prefix (e.g. 'Frozen II' over
    'Frozen II: Original Motion Picture Soundtrack'). Refuse ambiguous prefixes.
    """
    target = _album_number_key(query)
    words = _comparable(query).split()
    if not any(word.isdecimal() or word in _ROMAN_ALBUM_NUMBERS for word in words):
        return []
    albums = section.search(libtype="album")
    exact = [album for album in albums
             if _album_number_key(str(album.title)) == target]
    if exact:
        return exact if len({_comparable(str(album.title)) for album in exact}) == 1 else []

    # Spoken 'Frozen 2' should also find a catalogue album titled
    # 'Frozen II (Original Motion Picture Soundtrack)'.
    prefixes = [album for album in albums
                if _album_number_key(str(album.title)).startswith(target + " ")]
    return (prefixes if len({_comparable(str(album.title)) for album in prefixes}) == 1
            else [])


def _compact_title(value: str) -> str:
    """Ignore word boundaries only for track-title fallback matching."""
    return _comparable(value).replace(" ", "")


def _candidate_queries(query: str) -> list[str]:
    """Search Plex using several spellings before falling back to its catalogue."""
    normal = unicodedata.normalize("NFKC", query).translate(_APOSTROPHE_MAP)
    variants = [query, normal, normal.replace("'", "’"), normal.replace("'", "´"),
                normal.replace("'", ""), normal.replace("'", " "),
                normal.replace(" & ", " and "), normal.replace(" and ", " & ")]
    first = normal.split()[0] if normal.split() else normal
    variants.extend((first, first.rstrip("'’´")))
    return list(dict.fromkeys(v for v in variants if v.strip()))


def _indexed_tracks(section, server_key: str):
    """Cache a selected section's track metadata; never cache media credentials."""
    cache_key = (server_key, str(section.key))
    with _INDEX_LOCK:
        entry = _TRACK_INDEX.get(cache_key)
        if entry and time.monotonic() - entry[0] < INDEX_TTL_SECONDS:
            return entry[1]
        # An unfiltered track query bypasses Plex's punctuation-sensitive title filter.
        tracks = section.search(libtype="track")
        index = {}
        for track in tracks:
            title_key = _comparable(str(getattr(track, "title", "")))
            if title_key:
                index.setdefault(title_key, []).append(track)
        _TRACK_INDEX[cache_key] = (time.monotonic(), index)
        return index


def _fuzzy_title(index: dict, query: str) -> list:
    """Return one unambiguous high-confidence title, or no match.

    Never guess short titles; exact catalogue matches always take precedence.
    """
    target = _comparable(query)
    if len(target) < 12 or len(target.split()) < 3:
        return []
    scored = sorted(
        ((SequenceMatcher(None, target, title).ratio(), title) for title in index
         if abs(len(title) - len(target)) <= max(6, len(target) // 3)
         and title.split()[0] == target.split()[0]),
        reverse=True,
    )
    if not scored or scored[0][0] < 0.84:
        return []
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.10:
        return []
    return index[scored[0][1]]


def _album_title_prefix_matches(section, query: str) -> list:
    """Find a unique album whose title starts with the spoken title.

    Useful for subtitles such as "Paint the Sky With Stars: The Best of Enya".
    Never choose arbitrarily when multiple different albums share the prefix.
    """
    target = _comparable(query)
    if len(target) < 12 or len(target.split()) < 3:
        return []
    albums = section.search(libtype="album")
    matches = [album for album in albums
               if _comparable(str(album.title)).startswith(target + " ")]
    titles = {_comparable(str(album.title)) for album in matches}
    return matches if len(titles) == 1 else []


def _tracks(item, kind: str) -> list:
    if kind == "track":
        return [item]
    if kind == "album":
        return list(item.tracks())[:MAX_QUEUE]
    tracks = []
    for album in item.albums():
        tracks.extend(album.tracks())
        if len(tracks) >= MAX_QUEUE:
            break
    return tracks[:MAX_QUEUE]


def resolve_music(data: dict, options: dict, spoken: str, preferred_kind: str | None = None,
                  return_kind: bool = False) -> list[dict] | tuple[list[dict], str | None]:
    """Return track metadata for the first suitable selected-library match."""
    query = resolve_voice_alias(spoken.strip(), options.get(CONF_VOICE_ALIASES, {}))
    server = PlexServer(data[CONF_PLEX_URL], data[CONF_PLEX_TOKEN])
    selected = options.get(CONF_MUSIC_LIBRARIES)
    sections = [
        section for section in server.library.sections()
        if section.type == "artist" and (selected is None or str(section.key) in selected)
    ]
    kinds = [preferred_kind] if preferred_kind else ["artist", "album", "track"]
    fuzzy_candidates = []
    for kind in kinds:
        for section in sections:
            matches = []
            for search_query in _candidate_queries(query):
                matches = section.search(title=search_query, libtype=kind, maxresults=50)
                if any(_comparable(str(m.title)) == _comparable(query) for m in matches):
                    break
            # Prefer Plex's fast search, but fall back to a local catalogue index.
            # The catalogue is fetched only on a miss and cached for five minutes.
            exact = [m for m in matches if _comparable(str(m.title)) == _comparable(query)]
            if not exact and kind == "album":
                exact = _album_title_prefix_matches(section, query)
            if not exact and kind == "album":
                exact = _album_number_matches(section, query)
            if not exact and kind == "track":
                index = _indexed_tracks(section, data[CONF_PLEX_URL])
                exact = index.get(_comparable(query), [])
                if not exact:
                    # Alexa may split a compound word: "Heart Lines" / "Heartlines".
                    # Only accept a unique normalized title, not an arbitrary first hit.
                    compact = _compact_title(query)
                    compact_titles = [title for title in index if _compact_title(title) == compact]
                    if len(compact_titles) == 1:
                        exact = index[compact_titles[0]]
                if not exact:
                    fuzzy_candidates.extend(_fuzzy_title(index, query))
            if not exact:
                continue
            for item in exact:
                tracks = _tracks(item, kind)
                result = []
                for track in tracks:
                    media = getattr(track, "media", [])
                    parts = getattr(media[0], "parts", []) if media else []
                    if not parts or not getattr(parts[0], "key", None):
                        continue
                    result.append({
                        "key": str(track.ratingKey),
                        "part": str(parts[0].key),
                        "audio_codec": str(getattr(media[0], "audioCodec", "") or "").lower(),
                        "container": str(getattr(media[0], "container", "") or "").lower(),
                        "title": str(track.title),
                        "artist": str(getattr(track, "grandparentTitle", "") or ""),
                        "album": str(getattr(track, "parentTitle", "") or ""),
                        "thumb": str(getattr(track, "thumb", "") or getattr(track, "parentThumb", "") or ""),
                        "duration": int(getattr(track, "duration", 0) or 0),
                    })
                if result:
                    return (result[:MAX_QUEUE], kind) if return_kind else result[:MAX_QUEUE]
    # Only consider fuzzy results after every selected library has had an exact chance.
    # Refuse ambiguity: never silently pick between different matching titles.
    if "track" in kinds and fuzzy_candidates:
        unique_titles = {_comparable(str(t.title)) for t in fuzzy_candidates}
        if len(unique_titles) == 1:
            for track in fuzzy_candidates:
                media = getattr(track, "media", [])
                parts = getattr(media[0], "parts", []) if media else []
                if not parts or not getattr(parts[0], "key", None):
                    continue
                result = [{
                    "key": str(track.ratingKey), "part": str(parts[0].key),
                    "audio_codec": str(getattr(media[0], "audioCodec", "") or "").lower(),
                    "container": str(getattr(media[0], "container", "") or "").lower(),
                    "title": str(track.title),
                    "artist": str(getattr(track, "grandparentTitle", "") or ""),
                    "album": str(getattr(track, "parentTitle", "") or ""),
                    "thumb": str(getattr(track, "thumb", "") or getattr(track, "parentThumb", "") or ""),
                    "duration": int(getattr(track, "duration", 0) or 0),
                }]
                return (result, "track") if return_kind else result
    return ([], None) if return_kind else []
