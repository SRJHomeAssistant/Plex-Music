"""Discover Plex music library sections without exposing credentials."""

from __future__ import annotations

from plexapi.server import PlexServer


def get_music_libraries(url: str, token: str) -> dict[str, str]:
    """Return music library section IDs mapped to their display names.

    Plex music sections have type 'artist'; movies and TV are excluded.
    IDs are stored as strings to remain compatible with HA selectors.
    """
    server = PlexServer(url, token)
    return {
        str(section.key): section.title
        for section in server.library.sections()
        if section.type == "artist"
    }
