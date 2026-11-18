"""Built-in "fake external service" used to simulate outages from the admin UI."""
from __future__ import annotations

from app.core import cache

MODES = ("up", "down", "slow", "db_error", "timeout", "flaky")
PREFIX = "sim:"


def get_mode(name: str) -> str:
    return cache.get_str(PREFIX + name) or "up"


def set_mode(name: str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode}")
    cache.set_str(PREFIX + name, mode)


def list_modes() -> dict[str, str]:
    return {key[len(PREFIX):]: cache.get_str(key) or "up" for key in cache.scan_keys(PREFIX)}
