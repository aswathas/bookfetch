"""Shared HTTP helper: cookie-scoped sessions, timeouts, caps, typed failures."""

from __future__ import annotations

import http.cookiejar
import re
import urllib.error
import urllib.request

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MAX_DOWNLOAD = 2 * 1024 * 1024 * 1024  # 2 GB cap on any file

_KEY_RE = re.compile(r"(key=)[A-Za-z0-9]{6,}")


def redact_secrets(text: str) -> str:
    """Mask one-time download keys (e.g. libgen's key= tokens) so they never leak into logs or errors."""
    return _KEY_RE.sub(r"\1<redacted>", text or "")


class HttpError(Exception):
    def __init__(self, message: str, code: int | None = None, url: str = "", body: bytes = b""):
        super().__init__(redact_secrets(message))
        self.code = code
        self.url = redact_secrets(url)
        self.body = body


class Http:
    """One cookie jar per instance; one instance per source (or per domain)."""

    def __init__(self, timeout: int = 25):
        self.timeout = timeout
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def get(
        self,
        url: str,
        *,
        timeout: int | None = None,
        cap: int = 2_000_000,
        binary: bool = False,
        referer: str | None = None,
        headers: dict | None = None,
    ):
        """Return (status, final_url, response_headers, data). data is bytes if binary else str."""
        h = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as r:
                data = r.read(cap)
                if binary:
                    return r.status, r.url, dict(r.headers), data
                return r.status, r.url, dict(r.headers), data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read(200_000)
            except Exception:  # noqa: BLE001
                pass
            raise HttpError(f"HTTP {e.code} for {url}", code=e.code, url=url, body=body) from e
        except urllib.error.URLError as e:
            raise HttpError(f"request failed for {url}: {e.reason}", url=url) from e
        except TimeoutError as e:
            raise HttpError(f"timeout for {url}", url=url) from e
