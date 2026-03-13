"""Fetch BibTeX entries from DBLP record URLs."""

from __future__ import annotations

import html
import time
import re
from typing import Any

import httpx

BIBTEX_KEY_RE = re.compile(r"^@\w+\{([^,]+),", re.MULTILINE)
HTML_BIBTEX_PRE_RE = re.compile(r'<pre class="verbatim select-on-click">\s*(.*?)\s*</pre>', re.DOTALL)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/x-bibtex, text/plain, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class DblpBibtexClient:
    """Resolve DBLP record URLs to BibTeX entries."""

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0, max_retries: int = 3) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            http2=False,
        )
        self._max_retries = max_retries

    def fetch_bibtex(self, dblp_url: str) -> str | None:
        """Fetch a BibTeX record from a DBLP publication URL."""

        canonical_url = self._canonical_record_url(dblp_url)
        if canonical_url is None:
            return None

        bib_url = f"{canonical_url}.bib"
        try:
            return self._fetch_bibtex_with_retries(bib_url)
        except httpx.HTTPError:
            html_url = f"{canonical_url}.html?view=bibtex"
            return self._fetch_bibtex_from_html(html_url)

    @staticmethod
    def extract_citation_key(bibtex: str) -> str | None:
        """Extract the citation key from a BibTeX entry."""

        match = BIBTEX_KEY_RE.search(bibtex.strip())
        return match.group(1).strip() if match else None

    @staticmethod
    def sanitize_bibtex(bibtex: str) -> str:
        """Normalize fetched BibTeX so it is safe to write into refs.bib."""

        sanitized = html.unescape(bibtex.strip()).replace("\r\n", "\n").replace("\r", "\n")
        sanitized = re.sub(r"(?<!\\)&", r"\\&", sanitized)
        return sanitized

    def _fetch_bibtex_with_retries(self, bib_url: str) -> str | None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.get(bib_url)
                response.raise_for_status()
                text = response.text.strip()
                return self.sanitize_bibtex(text) if text else None
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
                last_error = exc
                if attempt + 1 >= self._max_retries:
                    break
                time.sleep(0.4 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return None

    def _fetch_bibtex_from_html(self, html_url: str) -> str | None:
        response = self._client.get(html_url)
        response.raise_for_status()
        match = HTML_BIBTEX_PRE_RE.search(response.text)
        if not match:
            return None
        return self.sanitize_bibtex(match.group(1))

    @staticmethod
    def _canonical_record_url(dblp_url: str | None) -> str | None:
        if not dblp_url or "dblp.org/rec/" not in dblp_url:
            return None
        canonical = dblp_url.strip()
        if canonical.endswith(".html"):
            canonical = canonical[:-5]
        canonical = canonical.split("?", 1)[0]
        if canonical.endswith(".bib"):
            canonical = canonical[:-4]
        return canonical
