"""Download interfaces."""

from __future__ import annotations

from typing import Protocol

from domain.models import PaperRecord
from topic.workspace import TopicWorkspace


class AbstractPaperDownloader(Protocol):
    """Download paper assets into the workspace."""

    def download_papers(
        self,
        papers: list[PaperRecord],
        workspace: TopicWorkspace,
        limit: int | None = None,
    ) -> int:
        """Download paper files and return the number of successful downloads."""
