"""Fetch BibTeX entries from DBLP record URLs."""

from __future__ import annotations

import re
from typing import Any

import httpx

BIBTEX_KEY_RE = re.compile(r"^@\w+\{([^,]+),", re.MULTILINE)


class DblpBibtexClient:
    """Resolve DBLP record URLs to BibTeX entries."""

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch_bibtex(self, dblp_url: str) -> str | None:
        """Fetch a BibTeX record from a DBLP publication URL."""

        if not dblp_url or "dblp.org/rec/" not in dblp_url:
            return None
        bib_url = dblp_url
        if bib_url.endswith(".html"):
            bib_url = bib_url[:-5]
        if not bib_url.endswith(".bib"):
            bib_url = f"{bib_url}.bib"
        response = self._client.get(bib_url)
        response.raise_for_status()
        text = response.text.strip()
        return text or None

    @staticmethod
    def extract_citation_key(bibtex: str) -> str | None:
        """Extract the citation key from a BibTeX entry."""

        match = BIBTEX_KEY_RE.search(bibtex.strip())
        return match.group(1).strip() if match else None
