"""Backend resolution: the one module that knows where the book sources live.

Resolution order (explicit override -> env var -> built-in default):

  libgen search base:  CLI_ANYTHING_BOOKFETCH_BASE  ->  https://libgen.li
  libgen download domains:  CLI_ANYTHING_BOOKFETCH_LIBGEN_DOMAINS (comma list)
                           ->  built-in mirror list (tried in order)

Every source adapter imports its endpoints and timeouts from here; no adapter
hardcodes an address.
"""

from __future__ import annotations

import os

from .errors import SourceFailedError

ENV_BASE = "CLI_ANYTHING_BOOKFETCH_BASE"
ENV_DOMAINS = "CLI_ANYTHING_BOOKFETCH_LIBGEN_DOMAINS"

DEFAULT_LIBGEN_BASE = "https://libgen.li"
DEFAULT_LIBGEN_DOMAINS = ["libgen.li", "libgen.pw", "libgen.me", "ww38.libgen.lc"]

PAGE_TIMEOUT = 25  # seconds for search/metadata pages
DOWNLOAD_TIMEOUT = 120  # seconds for file bodies


def libgen_base() -> str:
    base = (os.environ.get(ENV_BASE) or DEFAULT_LIBGEN_BASE).rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise SourceFailedError(f"{ENV_BASE} must be an http(s) URL, got {base!r}")
    return base


def libgen_download_domains() -> list:
    raw = os.environ.get(ENV_DOMAINS)
    if raw:
        domains = [d.strip() for d in raw.split(",") if d.strip()]
        if not domains:
            raise SourceFailedError(f"{ENV_DOMAINS} resolved to an empty list")
        return domains
    return list(DEFAULT_LIBGEN_DOMAINS)


def page_session(timeout: int = PAGE_TIMEOUT):
    """Fresh cookie-scoped session for one source domain."""
    from .http import Http

    return Http(timeout=timeout)
