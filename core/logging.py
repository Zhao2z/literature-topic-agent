"""Loguru-based logging configuration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger


def _patch_record(record: dict[str, Any]) -> None:
    """Inject default extra fields and a compact context string."""

    extras = record["extra"]
    extras.setdefault("component", record["name"])
    context_items = [f"{key}={value}" for key, value in extras.items() if key not in {"component", "context"}]
    extras["context"] = " | ".join(context_items)


def configure_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    """Configure process-wide loguru logging."""

    logger.remove()
    logger.configure(patcher=_patch_record)
    logger.add(
        sys.stderr,
        level=level.upper(),
        colorize=True,
        backtrace=True,
        diagnose=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
            "| <level>{level: <8}</level> "
            "| <cyan>{extra[component]: <30}</cyan> "
            "| <white>{message}</white>"
            "<dim>{extra[context]}</dim>"
        ),
    )
    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(path),
            level=level.upper(),
            colorize=False,
            backtrace=True,
            diagnose=False,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} "
                "| {level: <8} "
                "| {extra[component]: <30} "
                "| {message}"
                "{extra[context]}"
            ),
        )


def get_logger(component: str) -> Any:
    """Return a component-bound loguru logger."""

    return logger.bind(component=component)
