"""Anna's Archive adapter: search only, self-disabling behind DDoS-Guard.

Proven live (2026-11-10): annas-archive.gl loads (200) but /search answers 403 with a
DDoS-Guard JS challenge from this network, so headless search is unusable here. The
adapter detects the challenge, marks itself degraded, and the engine falls through.
On networks where search works, md5 links are extracted best-effort.
"""

from __future__ import annotations

import re
import urllib.parse

from ..errors import SourceFailedError
from ..http import Http
from ..models import Candidate
from .base import Source

BASE = "https://annas-archive.gl"


class AnnasArchiveSource(Source):
    name = "annasarchive"

    def __init__(self):
        super().__init__()
        self.http = Http(timeout=25)

    def search(self, query, author=None, year=None, limit=20):
        url = f"{BASE}/search?query=" + urllib.parse.quote(query)
        try:
            status, final, headers, html = self.http.get(url, cap=2_000_000)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "11001" in msg or "getaddrinfo" in msg:
                self.set_state("down", "dns failure for annas-archive.gl")
            elif "403" in msg:
                body = getattr(e, "body", b"") or b""
                if b"ddos-guard" in body.lower() or b"DDoS-Guard" in body:
                    self.set_state("degraded", "ddos-guard js challenge (headless blocked)")
                else:
                    self.set_state("degraded", "403 on search")
            else:
                self.set_state("down", msg)
            raise SourceFailedError(f"annasarchive: search unavailable: {self.note or msg}") from e
        cands = []
        for m in re.finditer(r'href="[^"]*/md5/([a-f0-9]{32})[^"]*"[^>]*>(.*?)</a>', html, re.S):
            title = re.sub(r"<[^>]+>", " ", m.group(2))
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) < 3:
                continue
            cands.append(Candidate(source=self.name, ref=m.group(1), title=title, formats={}))
            if len(cands) >= limit:
                break
        if not cands:
            self.set_state("degraded", "search page returned but no md5 links parsed")
            raise SourceFailedError("annasarchive: no parseable results")
        self.set_state("ok", "search ok")
        return cands

    def download(self, candidate, fmt=None):
        raise SourceFailedError(
            "annasarchive: direct download not implemented (book pages are behind the same guard)"
        )
