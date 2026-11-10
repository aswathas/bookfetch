"""libgen.li adapter: legacy PHP surface + two-step key download + mirror-domain failover.

Proven live (2026-11-10):
  search:   GET https://libgen.li/index.php/?req=<query>  -> legacy XHTML table #tablelibgen
  download: GET /get.php?md5=<md5>      -> 302 to /ads.php?md5=<md5> interstitial
            parse one-time key anchor   -> GET /get.php?md5=<md5>&key=<KEY> -> CDN -> bytes
"""

from __future__ import annotations

import re
import urllib.parse

from ..client import (
    DOWNLOAD_TIMEOUT,
    PAGE_TIMEOUT,
    libgen_base,
    libgen_download_domains,
    page_session,
)
from ..errors import SourceFailedError
from ..http import Http, MAX_DOWNLOAD
from ..models import Candidate
from .base import Source

SIZE_UNITS = {"kb": 1024, "kB": 1024, "mb": 1024**2, "GB": 1024**3, "B": 1}


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def parse_size(text: str) -> int:
    m = re.search(r"([\d.]+)\s*([kKmMgG]?[bB]?)", text or "")
    if not m:
        return 0
    num = float(m.group(1))
    unit = (m.group(2) or "B").lower()
    factor = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}.get(unit, 1)
    return int(num * factor)


def parse_results(html: str, base: str | None = None) -> list:
    """Parse the legacy #tablelibgen rows into Candidates."""
    base = base or libgen_base()
    out = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        if "md5=" not in row:
            continue
        cells = [c for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 8:
            continue
        hrefs = re.findall(r'href="([^"]+)"', row)
        md5 = None
        for h in hrefs:
            if "md5=" in h:
                md5 = h.split("md5=", 1)[1].split("&", 1)[0]
                break
        if not md5 or not re.fullmatch(r"[a-f0-9]{32}", md5):
            continue
        m = re.search(r">([^<>]{2,})<", cells[0])
        title = m.group(1).strip() if m else strip_tags(cells[0])
        authors = [a.strip() for a in strip_tags(cells[1]).split(";") if a.strip()]
        publisher = strip_tags(cells[2])
        year_raw = strip_tags(cells[3])
        year = year_raw.split()[0] if year_raw[:1].isdigit() else ""
        language = strip_tags(cells[4])
        pages = int(re.search(r"\d+", strip_tags(cells[5])).group(0)) if re.search(r"\d+", strip_tags(cells[5])) else 0
        size = parse_size(strip_tags(cells[6]))
        ext = strip_tags(cells[7]).lower()
        mirrors = [h for h in hrefs if h.startswith("http")]
        detail = next((base + "/" + h for h in hrefs if "edition.php" in h), "")
        out.append(
            Candidate(
                source="libgen",
                ref=md5,
                title=title,
                authors=authors,
                year=year,
                language=language,
                pages=pages,
                formats={ext: size} if ext else {},
                mirrors=mirrors,
                detail_url=detail,
            )
        )
    return out


class LibgenSource(Source):
    name = "libgen"

    def __init__(self, domains: list | None = None):
        super().__init__()
        self.domains = domains or libgen_download_domains()
        self._http = {dom: page_session() for dom in self.domains}
        self._primed = set()

    def _prime(self, dom: str):
        if dom in self._primed:
            return
        try:
            self._http[dom].get(f"https://{dom}/index.php/", cap=1_000_000)
            self._primed.add(dom)
        except Exception as e:  # noqa: BLE001 - prime failure is a domain-level failure
            raise SourceFailedError(f"libgen({dom}): session prime failed: {e}") from e

    def search(self, query, author=None, year=None, limit=20):
        dom = self.domains[0]
        self._prime(dom)
        base = libgen_base()
        # Author-targeted query first (surfaces the right book in big catalogs),
        # plain query as fallback.
        texts = [f"{query} {author}", query] if author else [query]
        cands = []
        for text in texts:
            url = f"{base}/index.php/?req=" + urllib.parse.quote(text)
            try:
                status, final, headers, html = self._http[dom].get(url, referer=base + "/", cap=2_000_000)
            except Exception as e:  # noqa: BLE001
                self.set_state("down", str(e))
                raise SourceFailedError(f"libgen: search failed: {e}") from e
            cands = parse_results(html, base)
            if cands:
                break
        if not cands:
            self.set_state("degraded", "no results table found (site layout change?)")
            raise SourceFailedError("libgen: no results table found (site layout change?)")
        self.set_state("ok", f"search ok via {dom}")
        return cands[:limit]

    def fetch_meta(self, md5: str):
        """Metadata for one md5 from the ads page (works without a search hit)."""
        dom = self.domains[0]
        try:
            self._prime(dom)
            status, final, headers, body = self._http[dom].get(
                f"https://{dom}/ads.php?md5={md5}", cap=500_000, referer=f"https://{dom}/"
            )
        except Exception:  # noqa: BLE001
            return None

        def grab(label: str) -> str:
            m = re.search(label + r":\s*([^<]*)", body)
            return m.group(1).strip() if m else ""

        title = grab("Title")
        if not title:
            return None
        authors = [a.strip() for a in grab("Author(s)").split(";") if a.strip()]
        year_raw = grab("Year")
        year = year_raw.split()[0] if year_raw[:1].isdigit() else ""
        language = grab("Language")
        return Candidate(
            source="libgen",
            ref=md5,
            title=title,
            authors=authors,
            year=year,
            language=language,
            detail_url=f"https://{dom}/md5.php?md5={md5}",
        )

    def _download_from(self, dom: str, md5: str, fmt: str | None):
        base = f"https://{dom}"
        self._prime(dom)
        http = self._http[dom]
        status, final, headers, body = http.get(
            f"{base}/get.php?md5={md5}", cap=500_000, binary=True, referer=base + "/"
        )
        if len(body) > 100_000 and (body[:4] == b"PK\x03\x04" or body[:5] == b"%PDF-"):
            return body, self._ext_from(headers, final, fmt)
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        m = re.search(r"get\.php\?md5=" + re.escape(md5) + r"&key=([A-Za-z0-9]+)", text)
        if not m:
            raise SourceFailedError(f"libgen({dom}): no key issued (anti-bot interstitial or blocked)")
        status, final, headers, data = http.get(
            f"{base}/get.php?md5={md5}&key={m.group(1)}",
            timeout=120,
            cap=MAX_DOWNLOAD,
            binary=True,
            referer=base + "/",
        )
        return data, self._ext_from(headers, final, fmt)

    @staticmethod
    def _ext_from(headers: dict, final_url: str, fmt: str | None) -> str:
        disp = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
        m = re.search(r'filename="?([^";]+)"?', disp)
        if m:
            ext = m.group(1).rsplit(".", 1)[-1].lower()
            if len(ext) <= 5:
                return ext
        m = re.search(r"\.([A-Za-z0-9]{2,5})(?:\?|$)", final_url or "")
        if m:
            return m.group(1).lower()
        return fmt or ""

    def download(self, candidate, fmt=None):
        md5 = candidate.ref
        failures = []
        for dom in self.domains:
            try:
                data, ext = self._download_from(dom, md5, fmt)
                if len(data) < 1024:
                    raise SourceFailedError(f"libgen({dom}): suspiciously small response ({len(data)} bytes)")
                self.set_state("ok", f"download ok via {dom}")
                return data, ext
            except SourceFailedError as e:
                failures.append(str(e))
            except Exception as e:  # noqa: BLE001
                failures.append(f"libgen({dom}): {e}")
        raise SourceFailedError("libgen: all download domains failed: " + " | ".join(failures))
