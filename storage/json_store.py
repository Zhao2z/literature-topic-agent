"""JSON artifact persistence."""

from __future__ import annotations

import json
from pathlib import Path

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

    def save_job(self, job: ProcessingJob, filename: str = "job.json") -> Path:
        """Write a job record to disk."""

        path = self.artifacts_dir / filename
        path.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
