"""Topic configuration loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from domain.models import TopicConfig


def load_topic_config(path: str | Path) -> TopicConfig:
    """Load a topic configuration file from YAML or JSON."""

    file_path = Path(path)
    raw_text = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() in {".yaml", ".yml"}:
        payload: dict[str, Any] = yaml.safe_load(raw_text) or {}
    elif file_path.suffix.lower() == ".json":
        payload = json.loads(raw_text)
    else:
        raise ValueError(f"unsupported topic config format: {file_path.suffix}")
    return TopicConfig.model_validate(payload)
