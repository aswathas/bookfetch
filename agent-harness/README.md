# cli-anything-bookfetch

Ask for any book by name, get a **verified file on disk**. One pip package, two frontends over a shared core:

- **MCP server** — `bookfetch-mcp` (stdio), for Claude Desktop / AI chat agents
- **CLI** — `cli-anything-bookfetch`, for CLI agents and humans (REPL on bare invocation)

Sources in failover order: **libgen.li** (primary, with mirror-domain failover) →
**Open Library / archive.org** → **Project Gutenberg** → **Standard Ebooks** →
**Anna's Archive** (self-disables behind DDoS-Guard). Format priority: **PDF → EPUB → best available**,
overridable with `--format`. Files land in `~/Books` as `Author - Title (Year).ext` (configurable).

## Install

```bash
pip install -e .        # or: pip install cli-anything-bookfetch
```

## CLI

```bash
cli-anything-bookfetch                              # REPL
cli-anything-bookfetch --json search "Dune" --author "Frank Herbert"
cli-anything-bookfetch --json get --id <ref>        # deterministic download
cli-anything-bookfetch get "Dune" --author "Frank Herbert" --format epub
cli-anything-bookfetch get "Dune" --author "Frank Herbert" --dry-run
cli-anything-bookfetch --json info <ref>
cli-anything-bookfetch --json sources [check]
cli-anything-bookfetch history | undo | redo
```

`--json` on every data command. Every command works one-shot; nothing prompts in one-shot mode.
`--author` is a **hard constraint**: candidates with no author match are disqualified, so a
wrong book can never win on title similarity alone. Ambiguous matches exit 4 with a numbered
candidate list and download nothing — retry with `get --id <ref>`.

## MCP

```json
{
  "mcpServers": {
    "bookfetch": { "command": "bookfetch-mcp" }
  }
}
```

Tools: `search_books(query, author?, year?, limit?)`, `get_book(query? | id?, source?, author?, year?, format?, out_dir?, dry_run?)`,
`book_info(id, source?, query?)`, `sources_status()`. Errors return
`{"ok": false, "error": {code, message, hint}}` with the same codes as the CLI.

## JSON envelope / exit codes

```json
{"ok": true, "data": {}, "error": null, "meta": {"software": "bookfetch", "version": "0.1.0", "session": "..."}, "warnings": []}
```

| Exit | Meaning |
|---|---|
| 0 | verified file delivered (or dry-run plan printed) |
| 2 | usage error |
| 4 | no match, or ambiguous (candidate list, nothing downloaded) |
| 5 | all sources failed (per-source failure report in the error) |
| 6 | verification failed (bytes were not a valid document) |

## Config

Optional `config.yaml` at `$BOOKFETCH_CONFIG`, else `$CLI_ANYTHING_HOME/bookfetch/config.yaml`
(`CLI_ANYTHING_HOME` defaults to `~/.cli-anything`):

```yaml
out_dir: C:\Books
disabled_sources: [standardebooks]
```

Env overrides: `BOOKFETCH_OUT` (output dir), `CLI_ANYTHING_BOOKFETCH_BASE` (libgen search base URL),
`CLI_ANYTHING_BOOKFETCH_LIBGEN_DOMAINS` (comma list of download domains).

## Security notes

- One-time libgen `key=` tokens are **redacted from every error message and log line**
- Artifacts are container-verified (PDF magic / EPUB mimetype+OPF / zip family) before being saved —
  an anti-bot HTML page fails verification (exit 6), it is never written as a "book"
- 25s page / 120s download timeouts, 2 GB cap, cookie jars per source, no shell anywhere
- YAML config parsed with `yaml.safe_load`; HTML parsed with pinned regexes (no eval, no XML parsing of untrusted input)

## Tests

```bash
python -m unittest discover -s cli_anything/bookfetch/tests -v            # unit, no network
BOOKFETCH_E2E=1 python -m unittest discover -s cli_anything/bookfetch/tests -p "test_*.py" -v   # + live network E2E
```

See `TEST.md` for the plan and recorded evidence. Design: `../docs/design/2026-11-10-bookfetch-design.md`.

## Limits

- Anna's Archive search is blocked by DDoS-Guard from this network; the adapter degrades gracefully (the adapter still parses md5 links on networks where it works)
- Standard Ebooks is a small curated catalog and the site has intermittent SSL; it is the lowest-priority source
- One book per call (no batch), no lending/DRM, no format conversion
