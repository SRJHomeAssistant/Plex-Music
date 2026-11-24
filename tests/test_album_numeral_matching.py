"""Regression tests for conservative Roman/Arabic album-number matching."""
from types import SimpleNamespace

from custom_components.plex_music.playback import (
    _album_number_key,
    _album_number_matches,
    _comparable,
)


class FakeAlbumSection:
    def __init__(self, *titles):
        self.albums = [SimpleNamespace(title=title) for title in titles]
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.albums


def test_frozen_arabic_and_roman_numerals_match():
    section = FakeAlbumSection("Frozen II")
    assert [album.title for album in _album_number_matches(section, "Frozen 2")] == ["Frozen II"]
    assert [album.title for album in _album_number_matches(FakeAlbumSection("Frozen 2"), "Frozen II")] == ["Frozen 2"]
    assert _album_number_key("Frozen II") == _album_number_key("Frozen 2")


def test_other_common_album_numbers_match():
    assert _album_number_key("Volume IV") == _album_number_key("Volume 4")
    assert _album_number_key("Rocky III") == _album_number_key("Rocky 3")
    assert _album_number_key("Final Fantasy VII") == _album_number_key("Final Fantasy 7")


def test_does_not_guess_when_multiple_album_titles_collide():
    section = FakeAlbumSection("Frozen II", "Frozen 2")
    assert _album_number_matches(section, "Frozen 2") == []


def test_does_not_fuzzily_match_unrelated_albums():
    assert _album_number_matches(FakeAlbumSection("Frozen III"), "Frozen 2") == []
    assert _album_number_matches(FakeAlbumSection("Frozen II"), "Frozen") == []
    assert _comparable("Frozen II") != _comparable("Frozen 2")

def test_numbered_album_with_soundtrack_subtitle_matches():
    section = FakeAlbumSection("Frozen II (Original Motion Picture Soundtrack)")
    assert [album.title for album in _album_number_matches(section, "Frozen 2")] == [
        "Frozen II (Original Motion Picture Soundtrack)"
    ]


def test_exact_numeral_title_wins_over_subtitled_album():
    section = FakeAlbumSection("Frozen II", "Frozen II: Deluxe Edition")
    assert [album.title for album in _album_number_matches(section, "Frozen 2")] == [
        "Frozen II"
    ]


def test_ambiguous_numbered_album_subtitles_are_rejected():
    section = FakeAlbumSection("Frozen II (Deluxe)", "Frozen II (Soundtrack)")
    assert _album_number_matches(section, "Frozen 2") == []
