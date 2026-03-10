"""CCF venue rank provider."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from domain.normalization import normalize_text

JS_PAIR_RE = re.compile(r'^\s*"(?P<key>.*?)"\s*:\s*"(?P<value>.*?)",?\s*$')


class LocalCcfRankProvider:
    """Load CCF venue mappings from a JSON file or a CCFrank data directory."""

    def __init__(self, mapping_path: str | Path) -> None:
        source_path = Path(mapping_path)
        self._rank_by_venue: dict[str, str] = {}
        self._rank_by_abbr: dict[str, str] = {}
        self._rank_by_canonical_path: dict[str, str] = {}
        self._canonical_by_dblp_prefix: dict[str, str] = {}

        if source_path.is_dir():
            self._load_ccfrank_directory(source_path)
        else:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            self._rank_by_venue = {normalize_text(key): value for key, value in payload.items()}

    def get_rank(self, venue: str, dblp_url: str | None = None) -> str:
        """Get the rank for a venue."""

        if dblp_url:
            rank = self._rank_from_dblp_url(dblp_url)
            if rank is not None:
                return rank

        normalized_venue = normalize_text(venue)
        if normalized_venue in self._rank_by_venue:
            return self._rank_by_venue[normalized_venue]
        if normalized_venue in self._rank_by_abbr:
            return self._rank_by_abbr[normalized_venue]
        return "Unranked"

    def _load_ccfrank_directory(self, data_dir: Path) -> None:
        rank_url = _parse_js_object_file(data_dir / "ccfRankUrl.js")
        rank_abbr = _parse_js_object_file(data_dir / "ccfRankAbbr.js")
        rank_full = _parse_js_object_file(data_dir / "ccfRankFull.js")
        rank_db = _parse_js_object_file(data_dir / "ccfRankDb.js")
        full_url = _parse_js_object_file(data_dir / "ccfFullUrl.js")
        abbr_full = _parse_js_object_file(data_dir / "ccfAbbrFull.js")

        self._rank_by_canonical_path = dict(rank_url)
        self._canonical_by_dblp_prefix = {self._normalize_dblp_prefix(key): value for key, value in rank_db.items()}

        for canonical_path, rank in rank_url.items():
            abbr = rank_abbr.get(canonical_path, "")
            full = rank_full.get(canonical_path, "")
            if full:
                self._rank_by_venue[normalize_text(full)] = rank
            if abbr:
                self._rank_by_abbr[normalize_text(abbr)] = rank

        for abbr, full in abbr_full.items():
            normalized_full = normalize_text(full)
            normalized_abbr = normalize_text(abbr)
            canonical_path = full_url.get(full)
            rank = self._rank_by_canonical_path.get(canonical_path or "", None)
            if rank and normalized_full not in self._rank_by_venue:
                self._rank_by_venue[normalized_full] = rank
            if rank and normalized_abbr and normalized_abbr not in self._rank_by_abbr:
                self._rank_by_abbr[normalized_abbr] = rank

    def _rank_from_dblp_url(self, dblp_url: str) -> str | None:
        dblp_prefix = self._normalize_dblp_prefix(_extract_dblp_prefix(dblp_url))
        canonical_path = self._canonical_by_dblp_prefix.get(dblp_prefix, dblp_prefix)
        return self._rank_by_canonical_path.get(canonical_path)

    @staticmethod
    def _normalize_dblp_prefix(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return normalized
        if normalized.startswith("http://") or normalized.startswith("https://"):
            normalized = _extract_dblp_prefix(normalized)
        return normalized.rstrip("/")


def _parse_js_object_file(path: Path) -> dict[str, str]:
    """Parse a CCFrank JavaScript object file into a Python dict."""

    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = JS_PAIR_RE.match(line)
        if not match:
            continue
        key = json.loads(f'"{match.group("key")}"')
        value = json.loads(f'"{match.group("value")}"')
        data[key] = value
    return data


def _extract_dblp_prefix(dblp_url: str) -> str:
    """Extract the DBLP venue prefix from a DBLP record URL or path."""

    parsed = urlparse(dblp_url)
    path = parsed.path if parsed.scheme else dblp_url
    if path.startswith("/rec/"):
        path = path[4:]
    path = path.rstrip("/")
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2:
        return "/" + "/".join(segments[:2])
    return "/" + "/".join(segments)
