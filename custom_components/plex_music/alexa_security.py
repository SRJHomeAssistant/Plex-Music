"""Verify official Alexa HTTPS requests before handling any intent.

Amazon's certificate URL, certificate chain, request signature, application ID
and request timestamp are all validated. No device ID is trusted before this.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.verification import PolicyBuilder, Store
from cryptography.x509.general_name import DNSName

MAX_REQUEST_AGE_SECONDS = 150
MAX_CERT_BYTES = 65536


def validate_certificate_url(url: str) -> str:
    """Only allow the exact Amazon Alexa certificate bucket and path."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "s3.amazonaws.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.startswith("/echo.api/")):
        raise ValueError("Invalid Alexa certificate URL")
    path = unquote(parsed.path)
    if "\\" in path or any(part in (".", "..") for part in path.split("/")):
        raise ValueError("Invalid Alexa certificate path")
    return url


def _load_pem_chain(pem_bytes: bytes) -> list[x509.Certificate]:
    if len(pem_bytes) > MAX_CERT_BYTES:
        raise ValueError("Certificate response too large")
    certificates = x509.load_pem_x509_certificates(pem_bytes)
    if not certificates:
        raise ValueError("Missing certificate")
    return certificates


def verify_alexa_request(
    raw_body: bytes, signature: str, certificate_pem: bytes,
    envelope: dict, expected_skill_id: str,
) -> None:
    """Raise ValueError for an unauthenticated, expired or wrong-skill request."""
    if not expected_skill_id:
        raise ValueError("Alexa skill ID is not configured")
    chain = _load_pem_chain(certificate_pem)
    with open(certifi.where(), "rb") as trust_file:
        roots = x509.load_pem_x509_certificates(trust_file.read())
    verifier = PolicyBuilder().store(Store(roots)).build_server_verifier(
        DNSName("echo-api.amazon.com")
    )
    verifier.verify(chain[0], chain[1:])
    try:
        decoded_signature = base64.b64decode(signature, validate=True)
        chain[0].public_key().verify(
            decoded_signature, raw_body, padding.PKCS1v15(), hashes.SHA1()
        )
    except Exception as exc:
        raise ValueError("Invalid Alexa request signature") from exc
    request = envelope.get("request", {})
    skill_id = envelope.get("session", {}).get("application", {}).get("applicationId")
    if not skill_id:
        skill_id = envelope.get("context", {}).get("System", {}).get("application", {}).get("applicationId")
    if skill_id != expected_skill_id:
        raise ValueError("Alexa application ID does not match")
    try:
        timestamp = datetime.fromisoformat(request["timestamp"].replace("Z", "+00:00"))
        age = abs((datetime.now(timezone.utc) - timestamp).total_seconds())
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("Invalid Alexa request timestamp") from exc
    if age > MAX_REQUEST_AGE_SECONDS:
        raise ValueError("Expired Alexa request")
