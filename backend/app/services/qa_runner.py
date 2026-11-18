from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from loguru import logger

from app.core import cache
from app.core.database import SessionLocal
from app.models import TestRun, TestRunStatus, utcnow
from app.repositories import test_runs as runs_repo
from app.services import notifications

SUITE_DIR = Path(__file__).resolve().parent.parent / "qa" / "system_tests"
BACKEND_ROOT = SUITE_DIR.parent.parent.parent
LOCK_KEY = "lock:system-tests"


def parse_junit(path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    root = ET.parse(path).getroot()
    cases: list[dict[str, Any]] = []
    counts = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for case in root.iter("testcase"):
        outcome, message, details = "passed", None, None
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = node.get("message")
                details = (node.text or "")[-3000:] or None
                break
        classname = case.get("classname", "")
        cases.append({
            "name": case.get("name"),
            "module": classname.split(".")[-1] if classname else None,
            "classname": classname,
            "time": float(case.get("time") or 0),
            "outcome": outcome,
            "message": message,
            "details": details,
        })
        counts["total"] += 1
        counts[{"passed": "passed", "failed": "failed", "skipped": "skipped", "error": "errors"}[outcome]] += 1
    return cases, counts


def _acquire(trigger: str) -> bool:
    if cache.acquire_lock(LOCK_KEY, ttl=900):
        return True
    if trigger != "manual":
        return False
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(3)
        if cache.acquire_lock(LOCK_KEY, ttl=900):
            return True
    return False


def run_system_tests(trigger: str = "scheduled") -> int | None:
    if not _acquire(trigger):
        logger.info("System tests are already running, skip ({})", trigger)
        return None
    try:
        with SessionLocal() as db:
            run = runs_repo.add(db, TestRun(trigger=trigger, status=TestRunStatus.running.value,
                                            started_at=utcnow()))
            db.commit()
            run_id = run.id

        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "junit.xml"
            cmd = [sys.executable, "-m", "pytest", str(SUITE_DIR), "-q", "-p", "no:cacheprovider",
                   f"--junitxml={report}", "-o", "junit_family=xunit2"]
            env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
            output = ""
            status = TestRunStatus.error.value
            cases: list[dict[str, Any]] = []
            counts = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
            try:
                proc = subprocess.run(cmd, cwd=str(BACKEND_ROOT), env=env, capture_output=True,
                                      text=True, timeout=600)
                output = (proc.stdout + "\n" + proc.stderr)[-20000:]
                if report.exists():
                    cases, counts = parse_junit(report)
                    status = (TestRunStatus.passed.value if counts["failed"] == 0 and counts["errors"] == 0
                              and counts["total"] > 0 else TestRunStatus.failed.value)
            except subprocess.TimeoutExpired as exc:
                output = f"Timeout: {exc}"
            except Exception as exc:
                output = f"Runner error: {exc}"
                logger.exception("System test runner failed")

        with SessionLocal() as db:
            stored = runs_repo.get(db, run_id)
            assert stored is not None
            run = stored
            run.status = status
            run.finished_at = utcnow()
            run.duration_s = round(time.perf_counter() - started, 2)
            run.cases = cases
            run.output = output
            for key, value in counts.items():
                setattr(run, key, value)
            db.commit()
            logger.info("System tests #{} finished: {} ({} passed / {} total)", run.id, run.status,
                        run.passed, run.total)
            if run.status != TestRunStatus.passed.value:
                notifications.notify_test_run(run)
        cache.delete("stats:summary")
        return run_id
    finally:
        cache.release_lock(LOCK_KEY)
