# AGENT GUIDE — bookfetch

**For AI agents** (ChatGPT, Gemini, Claude, or any coding agent) given this repo:
this file tells you exactly how to install, test, and use the system. Read it top to bottom.

## What this is

A book-fetching system: give it a book title (+ author) and it downloads a **real,
container-verified file** (PDF preferred, then EPUB) from libgen.li, with open-access
fallbacks (Open Library/archive.org → Gutenberg → Standard Ebooks → Anna's Archive).

Two frontends, one shared core:

- **CLI**: `cli-anything-bookfetch` (REPL on bare invocation, `--json` on every data command)
- **MCP stdio server**: `bookfetch-mcp` (tools: `search_books`, `get_book`, `book_info`, `sources_status`)

## Install

```bash
pip install -e agent-harness
```

## Fastest test (one command, needs live network)

```bash
python agent-harness/scripts/smoke_test.py
```

Expected: four `PASS` lines + `SMOKE TEST PASSED`, exit code 0. If it fails, the failing
line says which check — report that line verbatim.

## Use the CLI (one-shot)

```bash
cli-anything-bookfetch --json search "Sapiens" --author "Yuval Noah Harari"
cli-anything-bookfetch --json get "Sapiens" --author "Yuval Noah Harari"
cli-anything-bookfetch --json get --id <ref>          # deterministic (ref from search)
cli-anything-bookfetch --json sources
```

Every command prints a JSON envelope:

```json
{"ok": true, "data": {...}, "error": null, "meta": {...}, "warnings": []}
```

On failure: `ok: false`, `error: {code, message, hint}`, non-zero exit.
Codes: `usage`(2), `no_match`(4), `ambiguous`(4), `sources_failed`(5), `verification_failed`(6).

## Use the MCP tools WITHOUT a stdio bridge (code interpreter / sandbox / phone chat)

The MCP tools are plain Python functions — call them in-process, no server needed:

```python
from cli_anything.bookfetch import mcp_server
import json

out = json.loads(mcp_server.search_books(query="Sapiens", author="Yuval Noah Harari", limit=5))
if out["ok"]:
    print([c["ref"] for c in out["data"]["candidates"]])

book = json.loads(mcp_server.get_book(id="<ref>", out_dir="/tmp/books"))
print(book["data"]["path"], book["data"]["size"], book["data"]["format"])
```

## The download workflow (follow this when asked to "download book X")

1. `search_books(query, author)` → candidates, each with a stable `ref`
   (libgen refs are 32-hex md5s).
2. If `ok: false` and `error.code == "ambiguous"`: the top candidates are in
   `error.candidates` — pick the one that matches the user's intent and call
   `get_book(id=<ref>)`. **Never guess when ambiguous; the list is there for a reason.**
3. `get_book(...)` → `data.path` is the verified file on disk.
4. **Verify before claiming success**: file exists, size > 0, first bytes are
   `PK\x03\x04` (EPUB/ZIP) or `%PDF-` (PDF). `data.verified` must be `true`.
5. Re-running the same get is idempotent (`data.skipped: true`) — files are not re-downloaded.

## Ground rules

- `--author` is a hard constraint: candidates with no author match are disqualified.
- Downloads of large PDFs can take minutes; libgen has built-in mirror-domain failover —
  be patient, don't retry-loop.
- Anna's Archive self-disables behind DDoS-Guard on some networks; that is normal.
- Files are written to `~/Books` by default; override with `--out` (CLI) or `out_dir` (MCP).
