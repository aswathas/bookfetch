"""bookfetch MCP server (stdio) — the agent-facing frontend.

Tools: search_books, get_book, book_info, sources_status.
Errors come back as {"ok": false, "error": {code, message, hint}} with the same
codes as the CLI exit table, so agents can reason about them identically.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import __version__
from .core.engine import Engine
from .core.errors import CliAnythingError
from .core.registry import default_registry

mcp = FastMCP("bookfetch")


def _result(data, warnings=None) -> str:
    return json.dumps({"ok": True, "data": data, "error": None, "warnings": warnings or []},
                      indent=2, default=str)


def _error(exc: CliAnythingError) -> str:
    return json.dumps(
        {"ok": False, "data": None, "error": exc.to_dict(), "warnings": []},
        indent=2,
        default=str,
    )


@mcp.tool()
def search_books(query: str, author: str = "", year: str = "", limit: int = 10) -> str:
    """Search book sources for a title. Returns ranked candidates, each with a stable 'ref'
    (libgen md5, openlibrary key, gutenberg id, or standard-ebooks slug). The first source
    with matches wins; 'failures' lists sources that were tried and why they fell through.
    Use get_book with the chosen ref to download."""
    try:
        engine = Engine(default_registry())
        cands, failures = engine.search(
            query, author=author or None, year=year or None, limit=limit
        )
        if not cands:
            return json.dumps(
                {"ok": False, "data": None,
                 "error": {"code": "no_match",
                           "message": f"no candidates for {query!r}",
                           "hint": "try a different query or add author",
                           "failures": failures},
                 "warnings": []},
                indent=2, default=str,
            )
        return _result({"candidates": [c.to_dict() for c in cands], "failures": failures})
    except CliAnythingError as exc:
        return _error(exc)


@mcp.tool()
def get_book(
    query: str = "",
    id: str = "",
    source: str = "",
    author: str = "",
    year: str = "",
    format: str = "",
    out_dir: str = "",
    dry_run: bool = False,
) -> str:
    """Download a verified book file. Pass either query (with optional author/year to
    disambiguate) or id (the stable ref from search_books; source is inferred: 32-hex
    md5 = libgen, /works/ = openlibrary, digits = gutenberg). Format priority is
    pdf -> epub -> best available; pass format to force one. The file is verified
    (container magic) before being saved to out_dir (default: ~/Books). Returns the
    saved path, source, size, and metadata. Rerunning with the same input skips
    re-download if the file already exists."""
    try:
        from .core.errors import UsageError

        if not query and not id:
            raise UsageError("pass query or id")
        engine = Engine(default_registry(), out_dir=out_dir or None)
        result = engine.get(
            query=query or None,
            ref=id or None,
            source=source or None,
            author=author or None,
            year=year or None,
            fmt=format or None,
            dry_run=dry_run,
            out_dir=out_dir or None,
        )
        return _result(result.to_dict())
    except CliAnythingError as exc:
        return _error(exc)


@mcp.tool()
def book_info(id: str, source: str = "", query: str = "") -> str:
    """Full metadata for one book: pass its ref (id). For non-libgen sources, also pass
    query (the title) so the ref can be located in that source's search results."""
    try:
        engine = Engine(default_registry())
        cand = engine.book_info(id, source=source or None, query=query or None)
        return _result(cand.to_dict())
    except CliAnythingError as exc:
        return _error(exc)


@mcp.tool()
def sources_status() -> str:
    """Health of each book source (ok / degraded / down) with the last note. Run this
    after a failed get_book to see why a source fell through."""
    registry = default_registry()
    return _result(
        {
            "sources": [st.to_dict() for st in registry.status()],
            "version": __version__,
        }
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
