"""Ordered source registry: failover order + health states."""

from __future__ import annotations

from .config import load_config
from .errors import UsageError
from .sources import (
    AnnasArchiveSource,
    GutenbergSource,
    LibgenSource,
    OpenLibrarySource,
    StandardEbooksSource,
)


class Registry:
    def __init__(self, sources):
        self.sources = list(sources)

    def status(self) -> list:
        return [s.status() for s in self.sources]

    def by_name(self, name: str):
        for s in self.sources:
            if s.name == name:
                return s
        known = ", ".join(s.name for s in self.sources)
        raise UsageError(f"unknown source: {name} (known: {known})")


def default_registry(disabled=None) -> Registry:
    """Registry in failover order; config's disabled_sources are dropped."""
    if disabled is None:
        disabled = frozenset(load_config().get("disabled_sources") or [])
    sources = [
        LibgenSource(),
        OpenLibrarySource(),
        GutenbergSource(),
        StandardEbooksSource(),
        AnnasArchiveSource(),
    ]
    return Registry([s for s in sources if s.name not in disabled])


def infer_source(ref: str, name: str | None = None):
    """Resolve a --id reference to a source name when the user didn't pass --source."""
    if name:
        return name
    import re

    if re.fullmatch(r"[a-f0-9]{32}", ref or ""):
        return "libgen"
    if (ref or "").startswith("/works/"):
        return "openlibrary"
    if (ref or "").isdigit():
        return "gutenberg"
    if re.fullmatch(r"[a-z0-9-]+/[a-z0-9-]+", ref or ""):
        return "standardebooks"
    raise UsageError(
        f"cannot infer source for id {ref!r}; pass --source (libgen|openlibrary|gutenberg|standardebooks|annasarchive)"
    )
