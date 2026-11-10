"""Source ABC: the contract every backend adapter implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import SourceStatus


class Source(ABC):
    name = "base"

    def __init__(self):
        self.state = "unknown"
        self.note = ""

    def status(self) -> SourceStatus:
        return SourceStatus(self.name, self.state, self.note)

    def set_state(self, state: str, note: str = ""):
        self.state = state
        self.note = note

    @abstractmethod
    def search(self, query: str, author: str | None = None, year: str | None = None, limit: int = 20):
        """Return [Candidate]. Raise SourceFailedError when the source cannot serve the query."""

    @abstractmethod
    def download(self, candidate, fmt: str | None = None):
        """Return (bytes, ext). Raise SourceFailedError when the file cannot be fetched."""
