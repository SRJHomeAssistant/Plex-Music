"""Test the copy-and-paste Alexa setup generator."""
import json
from custom_components.plex_music.alexa_wizard import (
    country_console_info, interaction_model_json, skill_endpoint_url,
)


def test_generated_json_has_track_intent():
    model = json.loads(interaction_model_json())
    language = model["interactionModel"]["languageModel"]
    assert language["invocationName"] == "plex music"
    assert language["intents"][0]["slots"][0]["type"] == "AMAZON.SearchQuery"
    assert "play {track}" in language["intents"][0]["samples"]


def test_endpoint_and_country():
    assert skill_endpoint_url("https://example.org") == "https://example.org/api/plex_music/alexa"
    url, locale = country_console_info("GB")
    assert url.startswith("https://developer.amazon.com/")
    assert locale == "en-GB"
