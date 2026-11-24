"""User-managed Alexa voice recognition overrides."""
from __future__ import annotations

CONF_VOICE_ALIASES = "voice_aliases"


def normalise_phrase(value: str) -> str:
    """Normalise case and spacing without changing punctuation."""
    return " ".join(value.casefold().split())


def resolve_voice_alias(query: str, aliases: dict[str, str]) -> str:
    """Replace only an exact spoken phrase, never a substring."""
    return aliases.get(normalise_phrase(query), query)


def save_voice_aliases(options: dict, text: str) -> dict:
    """Parse one 'heard = intended' override per line."""
    aliases: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            raise ValueError("Each override must use: heard = intended")
        heard, intended = (part.strip() for part in line.split("=", 1))
        key = normalise_phrase(heard)
        if not key or not intended or len(key) > 200 or len(intended) > 200:
            raise ValueError("Override names must be between 1 and 200 characters")
        if key in aliases:
            raise ValueError("Each spoken phrase can only appear once")
        if len(aliases) >= 100:
            raise ValueError("A maximum of 100 overrides is supported")
        aliases[key] = intended
    return {**options, CONF_VOICE_ALIASES: aliases}
