"""Typed errors with a single exit-code mapping (mapped nowhere else)."""

from __future__ import annotations

HINTS = {
    "usage": "check the command syntax (--help)",
    "no_match": "try a different query, add --author, or check spelling",
    "ambiguous": "run 'search <query>' and retry with 'get --id <ref>'",
    "source_failed": "one source failed; the engine tries the next",
    "sources_failed": "all sources failed or matched nothing; check network and 'sources check'",
    "verification_failed": "bytes arrived but are not a valid document (anti-bot page?)",
}


class CliAnythingError(Exception):
    """Base error for the harness. code maps to a JSON error.code and an exit code."""

    code = "error"
    exit_code = 5

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint or HINTS.get(self.code)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "hint": self.hint}


class UsageError(CliAnythingError):
    code = "usage"
    exit_code = 2


class NoMatchError(CliAnythingError):
    code = "no_match"
    exit_code = 4

    def __init__(self, message: str, failures: list | None = None):
        super().__init__(message)
        self.failures = failures or []

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["failures"] = self.failures
        return d


class AmbiguousMatchError(CliAnythingError):
    code = "ambiguous"
    exit_code = 4

    def __init__(self, message: str, candidates: list):
        super().__init__(message)
        self.candidates = candidates

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["candidates"] = [c.to_dict() if hasattr(c, "to_dict") else c for c in self.candidates]
        return d


class SourceFailedError(CliAnythingError):
    """A single source could not serve the request. The engine catches this and falls through."""

    code = "source_failed"
    exit_code = 5


class AllSourcesFailedError(CliAnythingError):
    code = "sources_failed"
    exit_code = 5

    def __init__(self, message: str, failures: list):
        super().__init__(message)
        self.failures = failures

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["failures"] = self.failures
        return d


class VerificationFailedError(CliAnythingError):
    code = "verification_failed"
    exit_code = 6
