"""Workspace management for a topic."""

from __future__ import annotations

import json
from pathlib import Path

from domain.models import TopicConfig


class TopicWorkspace:
    """Manage filesystem layout for a topic workspace."""

    def __init__(self, root_dir: str | Path, topic_config: TopicConfig) -> None:
        self.root_dir = Path(root_dir)
        self.topic_config = topic_config
        self.topic_dir = self.root_dir / topic_config.slug
        self.artifacts_dir = self.topic_dir / "artifacts"
        self.database_path = self.topic_dir / "index.sqlite3"
        self.papers_dir = self.topic_dir / "papers"
        self.logs_dir = self.topic_dir / "logs"
        self.reports_dir = self.topic_dir / "reports"
        self.manual_pdfs_dir = self.topic_dir / "manual_pdfs"

    def ensure(self) -> None:
        """Create the workspace directories if they do not exist."""

        for path in [
            self.topic_dir,
            self.artifacts_dir,
            self.logs_dir,
            self.reports_dir,
            self.manual_pdfs_dir,
            self.papers_dir,
            self.papers_dir / "CCF-A",
            self.papers_dir / "CCF-B",
            self.papers_dir / "CCF-C",
            self.papers_dir / "Unranked",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        config_path = self.topic_dir / "topic.json"
        config_path.write_text(
            json.dumps(self.topic_config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def rank_directory(self, ccf_rank: str) -> Path:
        """Return the directory for a CCF rank bucket."""

        normalized = ccf_rank if ccf_rank in {"CCF-A", "CCF-B", "CCF-C", "Unranked"} else f"CCF-{ccf_rank}"
        if normalized not in {"CCF-A", "CCF-B", "CCF-C", "Unranked"}:
            normalized = "Unranked"
        path = self.papers_dir / normalized
        path.mkdir(parents=True, exist_ok=True)
        return path
