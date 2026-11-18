from __future__ import annotations

import json
import threading
import time
from typing import Any

import redis
from loguru import logger

from app.core.config import settings

_client: redis.Redis | None = None
_memory: dict[str, tuple[float | None, str]] = {}
_lock = threading.Lock()


def get_redis() -> redis.Redis | None:
    global _client
    if settings.celery_eager:
        return None
    if _client is None:
        try:
            _client = redis.Redis.from_url(settings.redis_url, decode_responses=True,
                                           socket_connect_timeout=2, socket_timeout=2)
        except Exception as exc:
            logger.warning("Redis init failed: {}", exc)
            return None
    return _client


def _mem_get(key: str) -> str | None:
    with _lock:
        item = _memory.get(key)
        if not item:
            return None
        expires, value = item
        if expires is not None and expires < time.time():
            _memory.pop(key, None)
            return None
        return value


def _mem_set(key: str, value: str, ttl: int | None) -> None:
    with _lock:
        _memory[key] = (time.time() + ttl if ttl else None, value)


def get_str(key: str) -> str | None:
    client = get_redis()
    if client is not None:
        try:
            value = client.get(key)
            return value if isinstance(value, str) else None
        except redis.RedisError as exc:
            logger.debug("Redis GET failed: {}", exc)
    return _mem_get(key)


def set_str(key: str, value: str, ttl: int | None = None) -> None:
    client = get_redis()
    if client is not None:
        try:
            client.set(key, value, ex=ttl)
            return
        except redis.RedisError as exc:
            logger.debug("Redis SET failed: {}", exc)
    _mem_set(key, value, ttl)


def get_json(key: str) -> Any | None:
    raw = get_str(key)
    return json.loads(raw) if raw else None


def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    set_str(key, json.dumps(value, default=str), ttl)


def delete(*keys: str) -> None:
    client = get_redis()
    if client is not None:
        try:
            client.delete(*keys)
        except redis.RedisError:
            pass
    with _lock:
        for k in keys:
            _memory.pop(k, None)


def acquire_lock(key: str, ttl: int) -> bool:
    client = get_redis()
    if client is not None:
        try:
            return bool(client.set(key, "1", nx=True, ex=ttl))
        except redis.RedisError:
            pass
    with _lock:
        item = _memory.get(key)
        if item and (item[0] is None or item[0] > time.time()):
            return False
        _memory[key] = (time.time() + ttl, "1")
        return True


def release_lock(key: str) -> None:
    delete(key)


def scan_keys(prefix: str) -> list[str]:
    client = get_redis()
    if client is not None:
        try:
            return [str(k) for k in client.scan_iter(match=f"{prefix}*")]
        except redis.RedisError:
            pass
    with _lock:
        return [k for k in _memory if k.startswith(prefix)]


def ping() -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False
