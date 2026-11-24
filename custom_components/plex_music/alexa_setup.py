"""Validate Alexa skill setup metadata without provisioning remote services."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit


def validate_public_https_url(value: str) -> str:
    """Require a public HTTPS origin; DNS and reachability need separate checks."""
    url = value.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("A public HTTPS URL is required")
    if parts.port not in (None, 443) or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("Use an HTTPS origin with no path, query or custom port")
    host = parts.hostname
    if host in ("localhost",) or host.endswith((".local", ".internal", ".lan")):
        raise ValueError("Local hostnames cannot be reached by Alexa")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
            raise ValueError("A public DNS hostname is required") from None
    else:
        if not ip.is_global:
            raise ValueError("Private and reserved IP addresses are not supported")
    return url


def validate_skill_id(value: str) -> str:
    """Validate the shape of an Alexa skill ID (not its ownership)."""
    skill_id = value.strip()
    if not re.fullmatch(r"amzn1\.ask\.skill\.[0-9a-fA-F-]{36}", skill_id):
        raise ValueError("Expected an Amazon Alexa skill ID")
    return skill_id
