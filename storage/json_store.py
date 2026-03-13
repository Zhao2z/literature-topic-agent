"""JSON artifact persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain.models import PaperRecord, ProcessingJob


class JsonArtifactStore:
    """Persist workflow artifacts as JSON files."""

    def __init__(self, artifacts_dir: str | Path) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def save_papers(self, papers: list[PaperRecord], filename: str = "papers.json") -> Path:
        """Write paper records to disk."""

        path = self.artifacts_dir / filename
        data = [paper.model_dump(mode="json") for paper in papers]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_papers(self, filename: str = "papers.json") -> list[PaperRecord]:
        """Load paper records from disk."""

        path = self.artifacts_dir / filename
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [PaperRecord.model_validate(row) for row in rows]

    def save_job(self, job: ProcessingJob, filename: str = "job.json") -> Path:
        """Write a job record to disk."""

        path = self.artifacts_dir / filename
        path.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_json(self, payload: Any, filename: str) -> Path:
        """Write an arbitrary JSON payload to disk."""

        path = self.artifacts_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
