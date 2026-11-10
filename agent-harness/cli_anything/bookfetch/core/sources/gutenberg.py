"""Project Gutenberg adapter: HTML search + direct per-ebook downloads.

Proven live (2026-11-10): the old JSON search endpoint is dead; the HTML search works:
  GET https://www.gutenberg.org/ebooks/search/?query=<q>
  result anchors: <a href="/ebooks/<id>">Title<br>Author<br>N downloads</a>
  download: GET https://www.gutenberg.org/ebooks/<id>.epub (redirects to /cache/epub/...)
"""

from __future__ import annotations

import re
import urllib.parse

from ..errors import SourceFailedError
from ..http import Http, MAX_DOWNLOAD
from ..models import Candidate
from .base import Source

BASE = "https://www.gutenberg.org"
BLOCK_RE = re.compile(r'<a[^>]+href="(/ebooks/\d+)"[^>]*>(.*?)</a>', re.S)


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment or "")).strip()


def parse_search(html: str) -> list:
    out = []
    seen = set()
    for url, inner in BLOCK_RE.findall(html):
        eid = url.rsplit("/", 1)[-1]
        if eid in seen:
            continue
        seen.add(eid)
        t = re.search(r'class="title"[^>]*>(.*?)</span>', inner, re.S)
        if not t:
            continue  # nav/footer anchor, not a result
        s = re.search(r'class="subtitle"[^>]*>(.*?)</span>', inner, re.S)
        title = _clean(t.group(1))
        author = _clean(s.group(1)) if s else ""
        if not title:
            continue
        out.append(
            Candidate(
                source="gutenberg",
                ref=eid,
                title=title,
                authors=[author] if author else [],
                formats={"epub": 0, "pdf": 0},
            )
        )
    return out


class GutenbergSource(Source):
    name = "gutenberg"

    def __init__(self):
        super().__init__()
        self.http = Http(timeout=25)

    def search(self, query, author=None, year=None, limit=20):
        q = f"{query} {author}" if author else query
        url = f"{BASE}/ebooks/search/?query=" + urllib.parse.quote(q)
        try:
            status, final, headers, html = self.http.get(url, cap=2_000_000)
        except Exception as e:  # noqa: BLE001
            self.set_state("down", str(e))
            raise SourceFailedError(f"gutenberg: search failed: {e}") from e
        cands = parse_search(html)[:limit]
        if not cands:
            self.set_state("degraded", "no parseable results")
            raise SourceFailedError("gutenberg: no parseable results")
        self.set_state("ok", "search ok")
        return cands

    def download(self, candidate, fmt=None):
        ext = fmt if fmt in ("epub", "pdf") else "epub"
        url = f"{BASE}/ebooks/{candidate.ref}.{ext}"
        try:
            status, final, headers, data = self.http.get(url, timeout=120, cap=MAX_DOWNLOAD, binary=True)
        except Exception as e:  # noqa: BLE001
            raise SourceFailedError(f"gutenberg: download failed: {e}") from e
        self.set_state("ok", f"download ok via {final}")
        return data, ext
