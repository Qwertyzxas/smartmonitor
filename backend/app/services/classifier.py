"""Local fallback classifier (scikit-learn) used when OpenRouter is unavailable.

Classifies an incident into network / server / database problems based on
features extracted from the last checks. The model is trained on a synthetic,
rule-derived dataset at first use (deterministic seed) and cached in memory.
"""
from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from sklearn.ensemble import RandomForestClassifier

LABELS = ("network", "server", "database")
DB_KEYWORDS = ("database", "sql", "postgres", "mysql", "mongo", "redis", "deadlock", "connection pool",
               "too many connections", "ora-", "sqlstate", "db error", "query timeout")
FEATURE_NAMES = ("frac_timeout", "frac_conn", "frac_5xx", "frac_gateway", "frac_4xx", "db_keyword",
                 "log_avg_ms", "frac_ok")

_model: RandomForestClassifier | None = None
_lock = threading.Lock()


class CheckLike(Protocol):
    status_code: int | None
    duration_ms: float | None
    error: str | None
    error_kind: str | None
    response_body: str | None


@dataclass
class Classification:
    label: str
    confidence: float
    probabilities: dict[str, float]
    features: dict[str, float]


def extract_features(checks: Sequence[CheckLike]) -> np.ndarray:
    n = max(len(checks), 1)
    timeouts = sum(1 for c in checks if c.error_kind == "timeout")
    conn = sum(1 for c in checks if c.error_kind in {"connection", "dns", "ssl", "protocol"})
    codes = [c.status_code for c in checks if c.status_code]
    s5xx = sum(1 for code in codes if code >= 500)
    gateway = sum(1 for code in codes if code in (502, 503, 504))
    s4xx = sum(1 for code in codes if 400 <= code < 500)
    ok = sum(1 for code in codes if code < 400)
    text = " ".join(f"{c.error or ''} {c.response_body or ''}" for c in checks).lower()
    db_kw = 1.0 if any(k in text for k in DB_KEYWORDS) else 0.0
    durations = [c.duration_ms for c in checks if c.duration_ms]
    log_avg = float(np.log1p(np.mean(durations))) if durations else 0.0
    return np.array([timeouts / n, conn / n, s5xx / n, gateway / n, s4xx / n, db_kw, log_avg, ok / n])


def _synthetic_dataset(rng: np.random.Generator, per_class: int = 400) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[int] = []

    def jitter(v: float, s: float = 0.1) -> float:
        return float(np.clip(v + rng.normal(0, s), 0, 1))

    for _ in range(per_class):
        # network: timeouts / connection errors, no HTTP response
        t = rng.uniform(0, 1)
        rows.append([jitter(t), jitter(1 - t), 0.0, 0.0, 0.0, float(rng.random() < 0.05),
                     float(rng.uniform(6, 10)), jitter(0.05, 0.05)])
        labels.append(0)
        # server: 5xx without DB hints (often gateway errors), or 4xx
        g = rng.uniform(0, 1)
        f5 = rng.uniform(0.5, 1)
        rows.append([jitter(0.05, 0.05), jitter(0.05, 0.05), f5, f5 * g, jitter(0.1, 0.1),
                     float(rng.random() < 0.03), float(rng.uniform(2, 9)), jitter(0.1, 0.1)])
        labels.append(1)
        # database: 5xx (mostly 500) + DB keywords in body/error; any latency, sometimes timeouts
        f5 = rng.uniform(0.4, 1)
        rows.append([jitter(0.1, 0.1), jitter(0.02, 0.02), f5, f5 * rng.uniform(0, 0.3), 0.0,
                     float(rng.random() < 0.95), float(rng.uniform(2, 10)), jitter(0.1, 0.1)])
        labels.append(2)
    return np.array(rows), np.array(labels)


def get_model() -> RandomForestClassifier:
    global _model
    with _lock:
        if _model is None:
            x, y = _synthetic_dataset(np.random.default_rng(42))
            model = RandomForestClassifier(n_estimators=60, max_depth=8, random_state=42)
            model.fit(x, y)
            _model = model
        return _model


def classify(checks: Sequence[CheckLike]) -> Classification:
    features = extract_features(checks)
    model = get_model()
    proba = model.predict_proba(features.reshape(1, -1))[0]
    idx = int(np.argmax(proba))
    return Classification(
        label=LABELS[idx],
        confidence=round(float(proba[idx]), 3),
        probabilities={LABELS[i]: round(float(p), 3) for i, p in enumerate(proba)},
        features={name: round(float(v), 3) for name, v in zip(FEATURE_NAMES, features)},
    )


RECOMMENDATIONS: dict[str, tuple[str, str, str]] = {
    # label: (recommendation, command, severity)
    "network": (
        "Сервис недоступен по сети (таймауты / отказ соединения). Проверьте DNS, балансировщик, "
        "firewall и сетевую связность до хоста. Если хост жив — перезапустите ingress/proxy.",
        "notify_admin", "high"),
    "server": (
        "Приложение возвращает ошибки 5xx/4xx. Проверьте логи приложения и последние деплои; "
        "при зависании воркеров поможет перезапуск сервиса.",
        "restart", "high"),
    "database": (
        "Признаки проблем с базой данных (ошибки соединения/пула, медленные запросы). Проверьте "
        "нагрузку на БД, лимиты соединений и блокировки; рассмотрите масштабирование.",
        "scale_up", "critical"),
}
