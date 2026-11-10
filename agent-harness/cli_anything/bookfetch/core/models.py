"""Domain model: one candidate, one result, one source status."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """One book edition found by one source."""

    source: str
    ref: str  # stable id: libgen md5, openlibrary key, gutenberg id, SE slug
    title: str = ""
    authors: list = field(default_factory=list)
    year: str = ""
    language: str = ""
    pages: int = 0
    formats: dict = field(default_factory=dict)  # ext -> size bytes (0/absent = unknown)
    mirrors: list = field(default_factory=list)  # extra download URLs / metadata links
    detail_url: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "ref": self.ref,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "language": self.language,
            "pages": self.pages,
            "formats": self.formats,
            "mirrors": self.mirrors,
            "detail_url": self.detail_url,
        }


@dataclass
class DownloadResult:
    path: str
    source: str
    ref: str
    format: str
    size: int
    title: str = ""
    authors: list = field(default_factory=list)
    year: str = ""
    verified: bool = False
    skipped: bool = False
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "source": self.source,
            "ref": self.ref,
            "format": self.format,
            "size": self.size,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "verified": self.verified,
            "skipped": self.skipped,
            "warnings": self.warnings,
        }


@dataclass
class SourceStatus:
    name: str
    state: str  # ok | degraded | down | unknown
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "note": self.note}


@dataclass
class Plan:
    """Resolved plan for a get (used by --dry-run)."""

    source: str
    ref: str
    title: str
    authors: list
    format: str  # concrete ext or "auto"
    target: str
    mirror_chain: list

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "ref": self.ref,
            "title": self.title,
            "authors": self.authors,
            "format": self.format,
            "target": self.target,
            "mirror_chain": self.mirror_chain,
        }
