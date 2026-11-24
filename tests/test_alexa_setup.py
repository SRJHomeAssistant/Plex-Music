"""Tests for URL and skill ID validation."""
import pytest
from custom_components.plex_music.alexa_setup import validate_public_https_url, validate_skill_id


@pytest.mark.parametrize("url", [
    "http://example.org", "https://192.168.1.2", "https://homeassistant.local",
    "https://example.org:8123", "https://example.org/path",
])
def test_reject_unsafe_endpoint(url):
    with pytest.raises(ValueError):
        validate_public_https_url(url)


def test_accept_public_https():
    assert validate_public_https_url("https://ha.example.org/") == "https://ha.example.org"


def test_skill_id():
    assert validate_skill_id("amzn1.ask.skill.12345678-1234-1234-1234-123456789abc")
