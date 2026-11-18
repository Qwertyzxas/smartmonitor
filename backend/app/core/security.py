"""Self-made JWT (HS256) and PBKDF2 password hashing — stdlib only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.core.config import settings

PBKDF2_ITERATIONS = 260_000


class TokenError(Exception):
    """Raised when a JWT is malformed, has an invalid signature or is expired."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(message: bytes, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest())


def create_access_token(subject: str, role: str, ttl_minutes: int | None = None,
                        secret: str | None = None) -> str:
    now = int(time.time())
    ttl = (ttl_minutes if ttl_minutes is not None else settings.jwt_ttl_minutes) * 60
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + ttl, "jti": secrets.token_hex(8)}
    signing_input = (
        _b64encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = _sign(signing_input.encode(), secret or settings.jwt_secret)
    return f"{signing_input}.{signature}"


def decode_access_token(token: str, secret: str | None = None) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature = token.split(".")
    except ValueError as exc:
        raise TokenError("Malformed token") from exc

    expected = _sign(f"{header_b64}.{payload_b64}".encode(), secret or settings.jwt_secret)
    if not hmac.compare_digest(expected, signature):
        raise TokenError("Invalid signature")

    try:
        header = json.loads(_b64decode(header_b64))
        payload: dict[str, Any] = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("Malformed token") from exc

    if header.get("alg") != "HS256":
        raise TokenError("Unsupported algorithm")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("Token expired")
    return payload


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64decode(salt_b64), int(iterations))
    return hmac.compare_digest(_b64encode(digest), digest_b64)
