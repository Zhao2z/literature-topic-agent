"""Repair persisted CCF ranks and relocate paper artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.logging import get_logger
from download.artifacts import build_download_candidates_payload
from download.naming import build_pdf_filename
from domain.models import PaperRecord
from providers.interfaces import AbstractVenueRankProvider
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)


class RankRepairWorkflow:
    """Recompute ranks for persisted papers and move files when buckets change."""

    def __init__(
        self,
        *,
        venue_rank_provider: AbstractVenueRankProvider,
        sqlite_store: SQLiteStore,
        json_store: JsonArtifactStore,
    ) -> None:
        self.venue_rank_provider = venue_rank_provider
        self.sqlite_store = sqlite_store
        self.json_store = json_store

    def run(self, *, workspace: TopicWorkspace) -> list[PaperRecord]:
        """Repair paper ranks and relocate local artifacts."""

        papers = self.json_store.load_papers()
        moved = 0
        changed = 0
        for paper in papers:
            new_rank = self.venue_rank_provider.get_rank(paper.venue, paper.dblp_url)
            if new_rank == paper.ccf_rank:
                continue
            old_rank = paper.ccf_rank
            paper.ccf_rank = new_rank
            changed += 1
            if paper.local_pdf_path and Path(paper.local_pdf_path).exists():
                moved += _relocate_paper_files(workspace=workspace, paper=paper)
            paper.timestamps.updated_at = datetime.now(timezone.utc)
            LOGGER.bind(
                paper_id=paper.paper_id,
                title=paper.title,
                old_rank=old_rank,
                new_rank=new_rank,
            ).info("Updated persisted paper rank")

        self.sqlite_store.upsert_papers(papers)
        self.json_store.save_papers(papers)
        self.json_store.save_json(build_download_candidates_payload(papers), "download_candidates.json")
        LOGGER.bind(topic=workspace.topic_config.slug, changed=changed, moved=moved).info("Completed rank repair workflow")
        return papers


def _relocate_paper_files(*, workspace: TopicWorkspace, paper: PaperRecord) -> int:
    pdf_path = Path(paper.local_pdf_path)
    artifact_dir = pdf_path.with_suffix("")
    new_pdf_path = _build_target_pdf_path(workspace=workspace, paper=paper, current_path=pdf_path)
    if new_pdf_path == pdf_path:
        return 0
    new_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf_path), str(new_pdf_path))
    old_artifact_dir = artifact_dir if artifact_dir.exists() else None
    new_artifact_dir = new_pdf_path.with_suffix("")
    if old_artifact_dir is not None:
        if new_artifact_dir.exists():
            shutil.rmtree(new_artifact_dir, ignore_errors=True)
        shutil.move(str(old_artifact_dir), str(new_artifact_dir))
    old_pdf_path = str(pdf_path)
    old_artifact_path = str(artifact_dir)
    paper.local_pdf_path = str(new_pdf_path)
    paper.parse_artifact_paths = _rewrite_path_map(paper.parse_artifact_paths, old_pdf_path=old_pdf_path, new_pdf_path=str(new_pdf_path), old_artifact_dir=old_artifact_path, new_artifact_dir=str(new_artifact_dir))
    paper.analysis_artifact_paths = _rewrite_path_map(paper.analysis_artifact_paths, old_pdf_path=old_pdf_path, new_pdf_path=str(new_pdf_path), old_artifact_dir=old_artifact_path, new_artifact_dir=str(new_artifact_dir))
    return 1


def _build_target_pdf_path(*, workspace: TopicWorkspace, paper: PaperRecord, current_path: Path) -> Path:
    rank_dir = workspace.rank_directory(paper.ccf_rank)
    target = rank_dir / build_pdf_filename(paper)
    if target == current_path:
        return target
    if target.exists():
        target = rank_dir / f"{target.stem}-{paper.paper_id}.pdf"
    return target


def _rewrite_path_map(
    paths: dict[str, str],
    *,
    old_pdf_path: str,
    new_pdf_path: str,
    old_artifact_dir: str,
    new_artifact_dir: str,
) -> dict[str, str]:
    updated: dict[str, str] = {}
    for key, value in paths.items():
        if value == old_pdf_path:
            updated[key] = new_pdf_path
        elif value.startswith(old_artifact_dir):
            updated[key] = new_artifact_dir + value[len(old_artifact_dir) :]
        else:
            updated[key] = value
    return updated
