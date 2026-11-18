"""Loguru-based logging with file rotation; std logging is routed into loguru."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings

_configured = False


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(component: str = "app") -> None:
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, enqueue=False,
               format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
                      "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
    logger.add(log_dir / f"{component}.log", level=settings.log_level, rotation="10 MB",
               retention="14 days", compression="zip", enqueue=True, encoding="utf-8")
    # Dedicated audit log for the AI agent and executed commands
    logger.add(log_dir / "agent.log", level="INFO", rotation="5 MB", retention="30 days",
               enqueue=True, encoding="utf-8", filter=lambda r: r["extra"].get("audit") is True)

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "sqlalchemy.engine"):
        lg = logging.getLogger(name)
        lg.handlers = [InterceptHandler()]
        lg.propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


audit_logger = logger.bind(audit=True)
