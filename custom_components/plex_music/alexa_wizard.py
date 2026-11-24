"""Prepare manual Alexa Developer Console configuration without Amazon credentials."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

# Amazon provides a single Alexa Developer Console login across marketplaces.
ALEXA_CONSOLE_URL = "https://developer.amazon.com/alexa/console/ask"
SUPPORTED_LOCALES = {
    "GB": "en-GB", "IE": "en-GB", "US": "en-US",
    "CA": "en-CA", "AU": "en-AU", "NZ": "en-AU",
    "DE": "de-DE", "FR": "fr-FR", "IT": "it-IT",
    "ES": "es-ES", "IN": "en-IN",
}
# Only en-GB utterances are currently tested; other locales need translations.
INTERACTION_LOCALE = "en-GB"
ENDPOINT_PATH = "/api/plex_music/alexa"


def skill_interaction_model() -> dict:
    """Load the same UK English Alexa model shipped with the integration."""
    model_path = Path(__file__).with_name("alexa_interaction_model_en_GB.json")
    return json.loads(model_path.read_text(encoding="utf-8"))


def interaction_model_json() -> str:
    """Return formatted JSON ready to paste into Alexa's JSON Editor."""
    return json.dumps(skill_interaction_model(), indent=2, ensure_ascii=False)


def skill_endpoint_url(base_url: str) -> str:
    """Proposed endpoint; not functional until a signed-request handler exists."""
    return urljoin(base_url.rstrip("/") + "/", ENDPOINT_PATH.lstrip("/"))


def country_console_info(country: str | None) -> tuple[str, str]:
    """Select locale guidance using Home Assistant country, not IP geolocation."""
    code = (country or "GB").upper()
    return ALEXA_CONSOLE_URL, SUPPORTED_LOCALES.get(code, INTERACTION_LOCALE)
