#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
TOKEN = ""


def call(method: str, path: str, body: Any = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}/api{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode()[:400]}") from exc


def step(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def wait_for(predicate: Callable[[], Any], timeout: float, what: str) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(3)
    raise SystemExit(f"timeout waiting for {what}")


def main() -> None:
    global TOKEN
    TOKEN = call("POST", "/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
    step("logged in as admin")

    if "--qa" in sys.argv:
        call("POST", "/qa/runs")

        def finished() -> Any:
            runs = call("GET", "/qa/runs?size=5")["items"]
            done = [r for r in runs if r["trigger"] == "manual" and r["status"] != "running"]
            return done[0] if done else None

        run = wait_for(finished, 300, "self-test run")
        detail = call("GET", f"/qa/runs/{run['id']}")
        for case in detail["cases"]:
            if case["outcome"] not in ("passed", "skipped"):
                print(f"  {case['outcome']}: {case['classname']}::{case['name']} — {case['message']}")
        step(f"self-tests: {run['status']} ({run['passed']}/{run['total']}, skipped {run['skipped']})")
        if run["status"] != "passed":
            raise SystemExit(1)
        return

    services = call("GET", "/services")
    assert services, "demo services must be seeded"
    step(f"dashboard lists {len(services)} services")

    svc = call("POST", "/sim/e2e/service")
    sid = svc["id"]
    step(f"added service #{sid} {svc['url']}")

    res = call("POST", f"/services/{sid}/check")
    assert res["check"]["status"] == "up", res
    series = call("GET", f"/services/{sid}/timeseries?hours=1")
    assert len(series) >= 1, "check must be stored and appear on the chart"
    step("manual check stored and visible in timeseries")

    call("PUT", "/settings", {"auto_actions_enabled": True})
    call("PUT", f"/services/{sid}", {"auto_actions_enabled": True})
    call("PUT", "/sim/e2e", {"mode": "down"})
    call("POST", f"/services/{sid}/check")
    res = call("POST", f"/services/{sid}/check")
    incident_id = res["incident_opened"]
    assert incident_id, f"incident must open after 2 failed checks: {res}"
    step(f"incident #{incident_id} opened after 2 failed checks")

    incident = wait_for(lambda: (lambda i: i if i["actions"] else None)(call("GET", f"/incidents/{incident_id}")),
                        120, "AI agent recommendation")
    action = incident["actions"][0]
    step(f"agent ({action['source']}): {action['command']} -> {action['status']} | {action['recommendation'][:90]}")
    assert action["recommendation"]
    if action["command"] in ("restart", "scale_up", "notify_admin"):
        assert action["status"] == "executed", action
        step("auto-action logged as executed")

    call("PUT", "/sim/e2e", {"mode": "up"})
    res = call("POST", f"/services/{sid}/check")
    assert res["incident_resolved"] == incident_id
    step("incident resolved after recovery")

    convs = call("GET", "/ai/conversations?size=5")
    assert convs["total"] >= 1
    call("DELETE", f"/services/{sid}")
    step("OK")


if __name__ == "__main__":
    main()
