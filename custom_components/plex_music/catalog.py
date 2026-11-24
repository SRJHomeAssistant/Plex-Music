"""Read-only Plex music catalogue search."""

from __future__ import annotations

from plexapi.server import PlexServer

from .const import CONF_MUSIC_LIBRARIES, CONF_PLEX_TOKEN, CONF_PLEX_URL


def search_music(data: dict, options: dict, query: str, kind: str, limit: int) -> list[dict]:
    """Search only selected Plex music libraries and return safe metadata."""
    server = PlexServer(data[CONF_PLEX_URL], data[CONF_PLEX_TOKEN])
    sections = [
        section for section in server.library.sections()
        if section.type == "artist"
    ]
    selected = options.get(CONF_MUSIC_LIBRARIES)
    if selected is not None:
        sections = [section for section in sections if str(section.key) in selected]

    results: list[dict] = []
    for section in sections:
        # plexapi searches within each music library and returns Plex media objects.
        matches = section.search(title=query, libtype=kind, maxresults=limit)
        for item in matches:
            results.append({
                "library": section.title,
                "library_id": str(section.key),
                "type": kind,
                "title": str(getattr(item, "title", "")),
                "artist": str(getattr(item, "grandparentTitle", "") or getattr(item, "parentTitle", "") or ""),
                "album": str(getattr(item, "parentTitle", "")) if kind == "track" else "",
                "rating_key": str(getattr(item, "ratingKey", "")),
            })
            if len(results) >= limit:
                return results
    return results
