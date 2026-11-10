"""Standard Ebooks adapter: catalog search + derived per-book EPUB URL.

Proven live (2026-11-10): catalog pages at /ebooks?query=<q> carry links of the form
/ebooks/<author-slug>/<title-slug>; downloads sit at
/ebooks/<slug>/downloads/<slug with '/' replaced by '_'>.epub (verified pattern from the
book page). Small curated public-domain catalog; site has intermittent SSL issues, so it
ships as the lowest-priority source.
"""

from __future__ import annotations

import re
import urllib.parse

from ..errors import SourceFailedError
from ..http import Http, MAX_DOWNLOAD
from ..models import Candidate
from .base import Source

BASE = "https://standardebooks.org"
LINK_RE = re.compile(r'href="(/ebooks/[^"?]+)"')


def _title_from_slug(slug: str) -> tuple:
    parts = slug.strip("/").split("/")
    author = parts[0].replace("-", " ").title() if parts else ""
    title = parts[1].replace("-", " ").title() if len(parts) > 1 else ""
    return title, author


class StandardEbooksSource(Source):
    name = "standardebooks"

    def __init__(self):
        super().__init__()
        self.set_state("degraded", "lowest priority; intermittent SSL from some networks")
        self.http = Http(timeout=25)

    def search(self, query, author=None, year=None, limit=20):
        q = f"{query} {author}" if author else query
        url = f"{BASE}/ebooks?query=" + urllib.parse.quote(q)
        try:
            status, final, headers, html = self.http.get(url, cap=2_000_000)
        except Exception as e:  # noqa: BLE001
            self.set_state("down", str(e))
            raise SourceFailedError(f"standardebooks: search failed: {e}") from e
        seen = set()
        cands = []
        for m in LINK_RE.finditer(html):
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            title, author = _title_from_slug(slug)
            cands.append(
                Candidate(
                    source=self.name,
                    ref=slug,
                    title=title,
                    authors=[author] if author else [],
                    formats={"epub": 0},
                )
            )
            if len(cands) >= limit:
                break
        if not cands:
            raise SourceFailedError("standardebooks: no catalog entries matched")
        self.set_state("ok", "search ok")
        return cands

    def download(self, candidate, fmt=None):
        slug = candidate.ref
        derived = f"{BASE}/ebooks/{slug}/downloads/{slug.replace('/', '_')}.epub"
        try:
            status, final, headers, data = self.http.get(derived, timeout=120, cap=MAX_DOWNLOAD, binary=True)
            self.set_state("ok", f"download ok via derived URL")
            return data, "epub"
        except Exception as e:  # noqa: BLE001
            derived_err = e
        # fallback: scrape the book page for an .epub link
        try:
            status, final, headers, html = self.http.get(f"{BASE}/ebooks/{slug}", cap=2_000_000)
        except Exception as e:  # noqa: BLE001
            raise SourceFailedError(
                f"standardebooks: derived URL failed ({derived_err}) and book page failed ({e})"
            ) from e
        links = [h for h in re.findall(r'href="([^"]+)"', html)
                 if h.endswith(".epub") and "advanced" not in h and "kepub" not in h]
        if not links:
            raise SourceFailedError("standardebooks: no epub link on book page")
        url = links[0] if links[0].startswith("http") else BASE + links[0]
        try:
            status, final, headers, data = self.http.get(url, timeout=120, cap=MAX_DOWNLOAD, binary=True)
        except Exception as e:  # noqa: BLE001
            raise SourceFailedError(f"standardebooks: download failed: {e}") from e
        self.set_state("ok", f"download ok via book-page link")
        return data, "epub"
