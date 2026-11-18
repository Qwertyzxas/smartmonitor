from __future__ import annotations

import pytest

from app.core.security import (TokenError, create_access_token, decode_access_token, hash_password,
                               verify_password)


def test_token_roundtrip() -> None:
    token = create_access_token("42", "admin")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"


def test_tampered_token_rejected() -> None:
    header, payload, sig = create_access_token("1", "viewer").split(".")
    forged = create_access_token("1", "admin").split(".")[1]
    with pytest.raises(TokenError):
        decode_access_token(f"{header}.{forged}.{sig}")


def test_wrong_secret_rejected() -> None:
    token = create_access_token("1", "viewer", secret="a")
    with pytest.raises(TokenError):
        decode_access_token(token, secret="b")


def test_expired_token_rejected() -> None:
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(create_access_token("1", "viewer", ttl_minutes=-1))


def test_password_hashing() -> None:
    hashed = hash_password("s3cret!")
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)
    assert hash_password("s3cret!") != hashed  # salted
