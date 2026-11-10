"""Open Library adapter: search.json on the main domain + archive.org file chain.

Proven live (2026-11-10): api.openlibrary.org is DNS-blocked from this network, but
https://openlibrary.org/search.json works. Files come from archive.org:
  GET https://archive.org/metadata/<ia>  -> file list
  GET https://archive.org/download/<ia>/<file> -> bytes
Public-domain items only (no lending/DRM).
"""

from __future__ import annotations

import json
import urllib.parse

from ..errors import SourceFailedError
from ..http import Http, MAX_DOWNLOAD
from ..models import Candidate
from .base import Source

PREFER = ["pdf", "epub"]


def parse_docs(data: dict) -> list:
    cands = []
    for d in data.get("docs", []):
        ia = [i for i in (d.get("ia") or []) if not i.startswith("isbn_")]
        if not ia:
            continue
        cands.append(
            Candidate(
                source="openlibrary",
                ref=d.get("key", ""),
                title=d.get("title", ""),
                authors=list(d.get("author_name") or []),
                year=str(d.get("first_publish_year") or ""),
                formats={},
                mirrors=[f"https://archive.org/metadata/{ia[0]}"],
            )
        )
    return cands


class OpenLibrarySource(Source):
    name = "openlibrary"

    def __init__(self):
        super().__init__()
        self.http = Http(timeout=25)

    def search(self, query, author=None, year=None, limit=20):
        q = query if not author else f"{query} {author}"
        url = (
            "https://openlibrary.org/search.json?q="
            + urllib.parse.quote(q)
            + f"&limit={limit}&fields=key,title,author_name,ia,first_publish_year"
        )
        try:
            status, final, headers, body = self.http.get(url, cap=1_500_000)
            data = json.loads(body)
        except Exception as e:  # noqa: BLE001
            self.set_state("down", str(e))
            raise SourceFailedError(f"openlibrary: search failed: {e}") from e
        cands = parse_docs(data)
        if not cands:
            self.set_state("degraded", "search ok but no items with archive files")
        else:
            self.set_state("ok", "search ok")
        return cands

    def download(self, candidate, fmt=None):
        if not candidate.mirrors:
            raise SourceFailedError("openlibrary: candidate has no archive.org pointer")
        ia = candidate.mirrors[0].rstrip("/").rsplit("/", 1)[-1]
        try:
            status, final, headers, body = self.http.get(
                f"https://archive.org/metadata/{ia}", cap=1_500_000
            )
            meta = json.loads(body)
        except Exception as e:  # noqa: BLE001
            raise SourceFailedError(f"openlibrary: archive metadata failed: {e}") from e
        files = [f for f in meta.get("files", []) if f.get("name", "").lower().endswith((".pdf", ".epub"))]
        if not files:
            raise SourceFailedError(f"openlibrary: no pdf/epub files for {ia} (lending-only?)")
        preferred = list(PREFER)
        if fmt and fmt in PREFER:
            preferred = [fmt] + [p for p in PREFER if p != fmt]
        files.sort(key=lambda f: (preferred.index(f["name"].lower().rsplit(".", 1)[-1])
                                  if f["name"].lower().rsplit(".", 1)[-1] in preferred else 99,
                                  int(f.get("size", "999999999"))))
        target = files[0]
        fname = target["name"]
        ext = fname.rsplit(".", 1)[-1].lower()
        url = f"https://archive.org/download/{ia}/{urllib.parse.quote(fname)}"
        try:
            status, final, headers, data = self.http.get(url, timeout=120, cap=MAX_DOWNLOAD, binary=True)
        except Exception as e:  # noqa: BLE001
            raise SourceFailedError(f"openlibrary: download failed: {e}") from e
        self.set_state("ok", f"download ok via archive.org ({ia})")
        return data, ext
