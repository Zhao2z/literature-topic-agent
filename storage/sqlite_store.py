"""SQLite persistence for paper records and jobs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from domain.models import PaperRecord, ProcessingJob


class SQLiteStore:
    """Store normalized papers and processing jobs in SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    topic_slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    venue_type TEXT NOT NULL,
                    ccf_rank TEXT NOT NULL,
                    dblp_url TEXT NOT NULL,
                    doi TEXT,
                    bibtex TEXT,
                    citations INTEGER,
                    keyword_matches_json TEXT NOT NULL,
                    download_candidates_json TEXT NOT NULL DEFAULT '[]',
                    landing_url TEXT,
                    pdf_url TEXT,
                    download_source TEXT,
                    local_pdf_path TEXT,
                    sections_json TEXT NOT NULL,
                    summary_short TEXT,
                    summary_structured_json TEXT,
                    rank_score REAL NOT NULL,
                    processing_priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT,
                    download_failure_code TEXT,
                    timestamps_json TEXT NOT NULL
                )
                """
            )
            self._ensure_column(connection, "papers", "download_candidates_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "papers", "download_source", "TEXT")
            self._ensure_column(connection, "papers", "download_failure_code", "TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    job_id TEXT PRIMARY KEY,
                    topic_slug TEXT NOT NULL,
                    total_papers INTEGER NOT NULL,
                    processed_counts_json TEXT NOT NULL,
                    eta_seconds INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert_papers(self, papers: list[PaperRecord]) -> None:
        """Insert or update paper rows."""

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO papers (
                    paper_id, topic_slug, title, authors_json, venue, year, venue_type, ccf_rank,
                    dblp_url, doi, bibtex, citations, keyword_matches_json, download_candidates_json, landing_url, pdf_url,
                    download_source, local_pdf_path, sections_json, summary_short, summary_structured_json, rank_score,
                    processing_priority, status, last_error, download_failure_code, timestamps_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    topic_slug=excluded.topic_slug,
                    title=excluded.title,
                    authors_json=excluded.authors_json,
                    venue=excluded.venue,
                    year=excluded.year,
                    venue_type=excluded.venue_type,
                    ccf_rank=excluded.ccf_rank,
                    dblp_url=excluded.dblp_url,
                    doi=excluded.doi,
                    bibtex=excluded.bibtex,
                    citations=excluded.citations,
                    keyword_matches_json=excluded.keyword_matches_json,
                    download_candidates_json=excluded.download_candidates_json,
                    landing_url=excluded.landing_url,
                    pdf_url=excluded.pdf_url,
                    download_source=excluded.download_source,
                    local_pdf_path=excluded.local_pdf_path,
                    sections_json=excluded.sections_json,
                    summary_short=excluded.summary_short,
                    summary_structured_json=excluded.summary_structured_json,
                    rank_score=excluded.rank_score,
                    processing_priority=excluded.processing_priority,
                    status=excluded.status,
                    last_error=excluded.last_error,
                    download_failure_code=excluded.download_failure_code,
                    timestamps_json=excluded.timestamps_json
                """,
                [self._paper_to_row(paper) for paper in papers],
            )

    def save_job(self, job: ProcessingJob) -> None:
        """Insert or update a processing job."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_jobs (
                    job_id, topic_slug, total_papers, processed_counts_json, eta_seconds, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    topic_slug=excluded.topic_slug,
                    total_papers=excluded.total_papers,
                    processed_counts_json=excluded.processed_counts_json,
                    eta_seconds=excluded.eta_seconds,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                (
                    job.job_id,
                    job.topic_slug,
                    job.total_papers,
                    json.dumps(job.processed_counts.model_dump()),
                    job.eta_seconds,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )

    @staticmethod
    def _paper_to_row(paper: PaperRecord) -> tuple[object, ...]:
        return (
            paper.paper_id,
            paper.topic_slug,
            paper.title,
            json.dumps(paper.authors, ensure_ascii=False),
            paper.venue,
            paper.year,
            paper.venue_type,
            paper.ccf_rank,
            paper.dblp_url,
            paper.doi,
            paper.bibtex,
            paper.citations,
            json.dumps(paper.keyword_matches, ensure_ascii=False),
            json.dumps([candidate.model_dump() for candidate in paper.download_candidates], ensure_ascii=False),
            paper.landing_url,
            paper.pdf_url,
            paper.download_source,
            paper.local_pdf_path,
            json.dumps(paper.sections, ensure_ascii=False),
            paper.summary_short,
            json.dumps(paper.summary_structured, ensure_ascii=False) if paper.summary_structured else None,
            paper.rank_score,
            paper.processing_priority,
            paper.status.value,
            paper.last_error,
            paper.download_failure_code,
            json.dumps(paper.timestamps.model_dump(mode="json"), ensure_ascii=False),
        )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
