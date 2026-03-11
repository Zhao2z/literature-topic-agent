"""Core domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


class PaperStatus(str, Enum):
    """Lifecycle states for a paper record."""

    DISCOVERED = "discovered"
    RANKED = "ranked"
    DOWNLOADED = "downloaded"
    PARSED = "parsed"
    ANALYZED = "analyzed"
    SUMMARIZED = "summarized"
    EXPORTED = "exported"
    FAILED = "failed"


class RankingWeights(BaseModel):
    """Ranking factor weights."""

    ccf_rank: float = 0.35
    recency: float = 0.3
    citations: float = 0.2
    keyword_match: float = 0.15

    @model_validator(mode="after")
    def validate_weights(self) -> "RankingWeights":
        """Ensure weights are non-negative and meaningful."""

        if any(value < 0 for value in self.model_dump().values()):
            raise ValueError("ranking weights must be non-negative")
        total = sum(self.model_dump().values())
        if total <= 0:
            raise ValueError("ranking weights must sum to a positive value")
        return self


class YearRange(BaseModel):
    """Year constraints for topic discovery."""

    start: int | None = None
    end: int | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "YearRange":
        """Validate year ordering."""

        if self.start and self.end and self.start > self.end:
            raise ValueError("year_range.start must be <= year_range.end")
        return self


class TopicConfig(BaseModel):
    """Configuration for a literature topic."""

    topic_name: str
    slug: str
    keyword_groups: list[list[str]]
    year_range: YearRange = Field(default_factory=YearRange)
    max_candidate_count: int = 200
    ranking_weights: RankingWeights = Field(default_factory=RankingWeights)
    initial_parse_limit: int = 20
    update_cron: str = "0 7 * * *"

    @field_validator("keyword_groups")
    @classmethod
    def validate_keyword_groups(cls, value: list[list[str]]) -> list[list[str]]:
        """Ensure keyword groups are present and non-empty."""

        if not value:
            raise ValueError("keyword_groups must not be empty")
        normalized = []
        for group in value:
            cleaned = [item.strip() for item in group if item.strip()]
            if not cleaned:
                raise ValueError("keyword group entries must not be empty")
            normalized.append(cleaned)
        return normalized


class PaperTimestamps(BaseModel):
    """Timestamps associated with a paper lifecycle."""

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    discovered_at: datetime = Field(default_factory=utc_now)
    downloaded_at: datetime | None = None
    parsed_at: datetime | None = None
    analyzed_at: datetime | None = None
    summarized_at: datetime | None = None
    exported_at: datetime | None = None


class DownloadCandidate(BaseModel):
    """A candidate download URL for a paper."""

    source: str
    url: str
    priority: int


class PaperRecord(BaseModel):
    """Normalized paper metadata and processing state."""

    paper_id: str
    topic_slug: str
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str = ""
    year: int
    venue_type: str = "unknown"
    ccf_rank: str = "Unranked"
    dblp_url: str = ""
    doi: str | None = None
    bibtex: str | None = None
    citations: int | None = None
    keyword_matches: list[str] = Field(default_factory=list)
    download_candidates: list[DownloadCandidate] = Field(default_factory=list)
    landing_url: str | None = None
    pdf_url: str | None = None
    download_source: str | None = None
    local_pdf_path: str | None = None
    sections: dict[str, str] = Field(default_factory=dict)
    section_metadata: dict[str, Any] = Field(default_factory=dict)
    parse_warnings: list[str] = Field(default_factory=list)
    parse_artifact_paths: dict[str, str] = Field(default_factory=dict)
    llm_analysis: dict[str, Any] | None = None
    classification: dict[str, Any] = Field(default_factory=dict)
    analysis_warnings: list[str] = Field(default_factory=list)
    analysis_artifact_paths: dict[str, str] = Field(default_factory=dict)
    analysis_model: str | None = None
    summary_short: str | None = None
    summary_structured: dict[str, Any] | None = None
    rank_score: float = 0.0
    processing_priority: int = 0
    status: PaperStatus = PaperStatus.DISCOVERED
    last_error: str | None = None
    download_failure_code: str | None = None
    timestamps: PaperTimestamps = Field(default_factory=PaperTimestamps)

    @field_validator("title")
    @classmethod
    def title_must_exist(cls, value: str) -> str:
        """Ensure title is present."""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be empty")
        return cleaned


class JobStageCounts(BaseModel):
    """Counters by processing stage."""

    discovered: int = 0
    ranked: int = 0
    downloaded: int = 0
    parsed: int = 0
    analyzed: int = 0
    summarized: int = 0
    exported: int = 0
    failed: int = 0


class ProcessingJob(BaseModel):
    """Track progress for a processing run."""

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    topic_slug: str
    total_papers: int = 0
    processed_counts: JobStageCounts = Field(default_factory=JobStageCounts)
    eta_seconds: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DblpRawRecord(BaseModel):
    """Raw DBLP metadata used before normalization."""

    title: str
    authors: list[str]
    venue: str
    year: int
    dblp_url: str
    doi: str | None = None
    ee_url: str | None = None
    bibtex: str | None = None
    venue_type: str = "unknown"
