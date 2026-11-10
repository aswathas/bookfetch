"""Source adapters: one per backend, the only place that knows each site's quirks."""

from __future__ import annotations

from .annasarchive import AnnasArchiveSource
from .base import Source
from .gutenberg import GutenbergSource
from .libgen import LibgenSource
from .openlibrary import OpenLibrarySource
from .standardebooks import StandardEbooksSource

__all__ = [
    "Source",
    "LibgenSource",
    "OpenLibrarySource",
    "GutenbergSource",
    "StandardEbooksSource",
    "AnnasArchiveSource",
]
