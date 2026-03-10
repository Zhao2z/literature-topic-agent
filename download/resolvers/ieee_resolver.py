"""IEEE candidate rules."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from domain.models import DownloadCandidate, PaperRecord


class IeeeResolver:
    """Build IEEE direct PDF candidates."""

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        article_number = _extract_article_number(paper.landing_url) or _extract_article_number(paper.pdf_url)
        if not article_number:
            return []
        return [
            DownloadCandidate(
                source="ieee_stamp",
                url=f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={article_number}",
                priority=60,
            ),
            DownloadCandidate(
                source="ieee_stamp_alt",
                url=f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={article_number}",
                priority=55,
            ),
        ]


def _extract_article_number(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.netloc != "ieeexplore.ieee.org":
        return None
    match = re.search(r"/document/(\d+)/?", parsed.path)
    if match:
        return match.group(1)
    match = re.search(r"arnumber=(\d+)", parsed.query)
    if match:
        return match.group(1)
    return None
