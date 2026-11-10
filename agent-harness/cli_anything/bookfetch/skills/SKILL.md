---
name: cli-anything-bookfetch
description: Fetch any book by name from libgen and open-access fallbacks — verified files on disk, via CLI or MCP.
---

# cli-anything-bookfetch

Ask for any book by name; get a verified file (PDF preferred, EPUB second) saved to `~/Books`
(override with `--out` / `BOOKFETCH_OUT` / `config.yaml`).

```bash
cli-anything-bookfetch --json search "Dune" --author "Frank Herbert"
cli-anything-bookfetch --json get --id <ref>            # deterministic (ref from search)
cli-anything-bookfetch get "Dune" --author "Frank Herbert" --format epub
cli-anything-bookfetch get "Dune" --author "Frank Herbert" --dry-run
cli-anything-bookfetch --json info <ref>
cli-anything-bookfetch --json sources [check]
cli-anything-bookfetch                                    # REPL
```

Rules:

- Every data command supports `--json`; `get` supports `--dry-run`.
- Ambiguous matches exit 4 with a numbered candidate list and download **nothing** —
  pick one with `get --id <ref>` (libgen refs are 32-hex md5s; openlibrary `/works/…`; gutenberg numeric).
- Exit codes: 0 ok, 2 usage, 4 no/ambiguous match, 5 all sources failed, 6 verification failed.
- Files are container-verified before saving; an anti-bot HTML page is a verification failure, never a "book".
- `sources check` probes each source live; after a failed `get`, run it to see why a source fell through.
- Session history: `~/.cli-anything/bookfetch/session.json` (`history`, `undo`, `redo`).

MCP: the same engine is exposed as a stdio server — run `bookfetch-mcp`;
tools: `search_books`, `get_book`, `book_info`, `sources_status`.
