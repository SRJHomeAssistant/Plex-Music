"""Regression tests for the v1.1.0-beta.1 queue and lifetime changes."""
from types import SimpleNamespace

from custom_components.plex_music.playback import _tracks
from custom_components.plex_music.media_proxy import PlaybackStore


def test_artist_albums_are_not_cut_off_at_100_tracks():
    albums = [
        SimpleNamespace(tracks=lambda start=n: [f"album-{start}-track-{i}" for i in range(12)])
        for n in range(10)
    ]
    artist = SimpleNamespace(albums=lambda: albums)
    tracks = _tracks(artist, "artist")
    assert len(tracks) == 120
    assert tracks[0] == "album-0-track-0"
    assert tracks[99] == "album-8-track-3"
    assert tracks[-1] == "album-9-track-11"


def test_long_album_not_truncated():
    album = SimpleNamespace(tracks=lambda: list(range(150)))
    assert _tracks(album, "album") == list(range(150))


def test_active_stream_urls_survive_initial_four_hour_expiry(monkeypatch):
    from custom_components.plex_music import media_proxy

    clock = [100.0]
    monkeypatch.setattr(media_proxy.time, "monotonic", lambda: clock[0])
    store = PlaybackStore()
    entry = SimpleNamespace(entry_id="entry-a")
    song = {"title": "First", "key": "123", "part": "/library/parts/123/file.mp3",
            "thumb": "/library/metadata/123/thumb"}
    queue_id, queue = store.create(entry, "study", [song], "https://example.org")
    audio_token = queue[0]["audio_url"].rsplit("/", 1)[1]
    art_token = queue[0]["artwork_url"].rsplit("/", 1)[1]
    assert store.get(audio_token) is not None
    assert store.get(art_token) is not None

    clock[0] += media_proxy.TOKEN_LIFETIME - 10
    assert store.touch("study", queue_id)
    clock[0] += 30  # Original URLs have now passed their initial expiry.
    assert store.get(audio_token) is not None
    assert store.get(art_token) is not None
    assert len(store.queue(queue_id)[2]) == 1


def test_no_verified_activity_means_queue_and_urls_expire(monkeypatch):
    from custom_components.plex_music import media_proxy

    clock = [1.0]
    monkeypatch.setattr(media_proxy.time, "monotonic", lambda: clock[0])
    store = PlaybackStore()
    entry = SimpleNamespace(entry_id="entry")
    queue_id, queue = store.create(entry, "study", [{"title": "A"}], "https://example.org")
    token = queue[0]["audio_url"].rsplit("/", 1)[1]
    clock[0] += media_proxy.TOKEN_LIFETIME + 1
    assert not store.touch("study", queue_id)
    assert store.get(token) is None


def test_other_echo_cannot_extend_queue(monkeypatch):
    from custom_components.plex_music import media_proxy

    clock = [1.0]
    monkeypatch.setattr(media_proxy.time, "monotonic", lambda: clock[0])
    store = PlaybackStore()
    entry = SimpleNamespace(entry_id="entry")
    queue_id, queue = store.create(entry, "study", [{"title": "A"}], "https://example.org")
    assert not store.touch("kitchen", queue_id)
    clock[0] += media_proxy.TOKEN_LIFETIME + 1
    assert store.get(queue[0]["audio_url"].rsplit("/", 1)[1]) is None


def test_replacing_queue_invalidates_old_urls():
    store = PlaybackStore()
    entry = SimpleNamespace(entry_id="entry")
    old_id, old_tracks = store.create(entry, "study", [{"title": "Old"}], "https://example.org")
    old_token = old_tracks[0]["audio_url"].rsplit("/", 1)[1]
    store.create(entry, "study", [{"title": "New"}], "https://example.org")
    assert store.get(old_token) is None
    assert not store.touch("study", old_id)
