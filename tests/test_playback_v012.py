"""Tests for the pure Alexa playback and voice-alias helpers."""
from custom_components.plex_music.voice_aliases import resolve_voice_alias, save_voice_aliases
from custom_components.plex_music.alexa_playback import ask_for_music, play_response
from custom_components.plex_music.alexa_wizard import skill_interaction_model


def test_aliases_are_case_insensitive_and_exact():
    options = save_voice_aliases({}, "gem = Jem\nFlorence and the machines = Florence + The Machine")
    aliases = options["voice_aliases"]
    assert resolve_voice_alias(" GEM ", aliases) == "Jem"
    assert resolve_voice_alias("play gem", aliases) == "play gem"
    assert resolve_voice_alias("florence AND the machines", aliases) == "Florence + The Machine"


def test_aliases_can_be_deleted():
    options = save_voice_aliases({"voice_aliases": {"gem": "Jem"}}, "")
    assert options["voice_aliases"] == {}


def test_play_directive_is_silent_and_contains_artwork():
    track = {"title": "Example", "artist": "Artist", "album": "Album",
             "audio_url": "https://example.com/audio", "artwork_url": "https://example.com/cover"}
    response = play_response("queue", [track])
    assert "outputSpeech" not in response["response"]
    directive = response["response"]["directives"][0]
    assert directive["type"] == "AudioPlayer.Play"
    assert directive["audioItem"]["metadata"]["art"]["sources"][0]["url"] == track["artwork_url"]


def test_next_track_is_enqueued():
    tracks = [{"title": "One", "audio_url": "https://example.com/1"},
              {"title": "Two", "audio_url": "https://example.com/2"}]
    directive = play_response("q", tracks, 1, "ENQUEUE")["response"]["directives"][0]
    assert directive["audioItem"]["stream"]["expectedPreviousToken"] == "q:0"


def test_play_prompt_elicits_track():
    response = ask_for_music()
    assert response["response"]["directives"][0]["slotToElicit"] == "track"


def test_interaction_model_has_play_dialogue():
    model = skill_interaction_model()["interactionModel"]
    assert model["dialog"]["intents"][0]["name"] == "PlayTrackIntent"


def test_artist_name_normalisation():
    from custom_components.plex_music.playback import _comparable
    assert _comparable("Florence and the Machine") == _comparable("Florence + The Machine")
    assert _comparable("Florence & The Machine") == _comparable("florence and the machine")
    assert _comparable("Jem") != _comparable("Gem")


def test_v013_control_intents_present():
    model = skill_interaction_model()["interactionModel"]["languageModel"]
    names = {intent["name"] for intent in model["intents"]}
    assert {
        "PausePlaybackIntent", "ResumePlaybackIntent", "NextTrackIntent",
        "PreviousTrackIntent", "StopPlaybackIntent", "ShuffleIntent",
    }.issubset(names)


def test_resume_offset_and_silent_stop():
    from custom_components.plex_music.alexa_playback import stop_response
    track = {"title": "Test", "audio_url": "https://example.com/audio"}
    stream = play_response("q", [track], offset=12345)["response"]["directives"][0]["audioItem"]["stream"]
    assert stream["offsetInMilliseconds"] == 12345
    stopped = stop_response()["response"]
    assert stopped["directives"][0]["type"] == "AudioPlayer.Stop"
    assert "outputSpeech" not in stopped


def test_punctuation_variants_match_exact_song_titles():
    from custom_components.plex_music.playback import _comparable, _candidate_queries

    assert _comparable("Flora's Secret") == _comparable("Flora’s Secret")
    assert _comparable("I've Been Waiting for You") == _comparable("I´ve Been Waiting for You")
    assert _comparable("Various Storms & Saints") == _comparable("Various Storms and Saints")
    assert "Flora’s Secret" in _candidate_queries("Flora's Secret")
    assert "Flora's Secret" in _candidate_queries("Flora’s Secret")
    assert "I´ve Been Waiting for You" in _candidate_queries("I've Been Waiting for You")


def test_catalogue_index_matches_unicode_titles(monkeypatch):
    from types import SimpleNamespace
    from custom_components.plex_music import playback

    playback._TRACK_INDEX.clear()
    calls = []
    class FakeSection:
        key = "5"
        def search(self, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(title="Flora’s Secret", ratingKey="101"),
                    SimpleNamespace(title="I´ve Been Waiting for You", ratingKey="102")]
    section = FakeSection()
    index = playback._indexed_tracks(section, "http://plex.test")
    assert index[playback._comparable("flora's secret")][0].ratingKey == "101"
    assert index[playback._comparable("I've Been Waiting for You")][0].ratingKey == "102"
    playback._indexed_tracks(section, "http://plex.test")
    assert calls == [{"libtype": "track"}]
    playback._TRACK_INDEX.clear()


def test_fuzzy_fallback_is_conservative():
    from types import SimpleNamespace
    from custom_components.plex_music.playback import _fuzzy_title, _comparable

    song = SimpleNamespace(title="Various Storms & Saints")
    index = {_comparable(song.title): [song]}
    assert _fuzzy_title(index, "various storms and scenes") == [song]
    assert _fuzzy_title(index, "saints") == []
    assert _fuzzy_title(index, "completely different song") == []
    competing = SimpleNamespace(title="Various Storms and Scenes")
    index[_comparable(competing.title)] = [competing]
    assert _fuzzy_title(index, "various storms and scens") == []
