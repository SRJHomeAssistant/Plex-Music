"""Regression checks for explicit Alexa music type routing in the UK model."""
import json
from pathlib import Path


MODEL = Path(__file__).resolve().parents[1] / "alexa" / "interaction_model_en_GB.json"


def test_explicit_play_utterances_have_distinct_intents():
    data = json.loads(MODEL.read_text(encoding="utf-8"))
    intents = {intent["name"]: intent for intent in data["interactionModel"]["languageModel"]["intents"]}
    assert "play {track}" in intents["PlayTrackIntent"]["samples"]
    assert "play album {album}" in intents["PlayAlbumIntent"]["samples"]
    assert "play song {song}" in intents["PlaySongIntent"]["samples"]
    assert "play artist {artist}" in intents["PlayArtistIntent"]["samples"]
    assert "shuffle {track}" in intents["ShuffleIntent"]["samples"]
    assert "shuffle album {album}" in intents["ShuffleAlbumIntent"]["samples"]
    assert not any("album" in sample or "artist" in sample or "song" in sample
                   for sample in intents["PlayTrackIntent"]["samples"])
    for name in ("PlayAlbumIntent", "PlaySongIntent", "PlayArtistIntent", "ShuffleAlbumIntent"):
        assert len(intents[name]["slots"]) == 1
        assert intents[name]["slots"][0]["type"] == "AMAZON.SearchQuery"
