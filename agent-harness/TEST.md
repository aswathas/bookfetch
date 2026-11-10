# Test plan

Layers:

1. **Unit** (`cli_anything/bookfetch/tests/test_core.py`) — pure logic, real captured fixtures, no network.
2. **MCP E2E** (`cli_anything/bookfetch/tests/test_e2e_mcp.py`) — real network + stdio handshake, in-process tool calls.
3. **CLI E2E** (`cli_anything/bookfetch/tests/test_full_e2e.py`) — installed command via `_resolve_cli()`, from any cwd, real artifacts.

E2E layers are gated on `BOOKFETCH_E2E=1` locally; they are mandatory in release validation (never reported as skips).

## Run

```bash
cd agent-harness
python -m unittest discover -s cli_anything/bookfetch/tests -p "test_core.py" -v
BOOKFETCH_E2E=1 python -m unittest discover -s cli_anything/bookfetch/tests -p "test_*.py" -v
python scripts/smoke_test.py        # one-command live check (for humans and agents)
```

## Evidence (recorded 2026-11-10, machine: Windows 11, Python 3.14)

### Unit — 33 passed, 0 failed

| Area | Proof |
|---|---|
| libgen parser | parses 20+ rows from a real captured `index.php/?req=dune` page; Herbert *Dune* row: ref `e7c75dc…`, 781 kB EPUB, French, 97 pages, mirror links present |
| gutenberg parser | 3+ results from real captured search page (id/title/author) |
| openlibrary parser | real captured `search.json`: `/works/` refs + `archive.org/metadata` pointers |
| standard ebooks | catalog link regex matches real captured page |
| verify | synthetic EPUB (mimetype+OPF) passes; wrong-mimetype zip, corrupt zip, HTML page, too-small bytes all rejected; `%PDF-` magic passes |
| match | author disambiguates Herbert vs comic; identical twins → ambiguous; unknown title → none |
| registry | failover order; ref→source inference (md5/works/digits/slug); failed source recorded, next source serves |
| engine rules | pdf>epub>largest; `--format` on missing ext → usage error; filename sanitization (illegal Windows chars stripped, `Last, First` → `Last`) |
| config | YAML loaded via `yaml.safe_load`; missing/corrupt → `{}`; `disabled_sources` drops sources from registry |
| redaction | `key=VXJZ89CXWMTUFYNN` → `key=<redacted>` in error text; short keys untouched |
| session | record/undo/redo; survives reload |

### MCP E2E — 5 passed (BOOKFETCH_E2E=1)

| Test | Artifact / proof |
|---|---|
| `search_books("Dune", author="Frank Herbert")` | live libgen table; Herbert row `e7c75dc…` present |
| `get_book(id=e7c75dc…, out_dir=tmp)` | **800,094-byte EPUB saved**, `PK` magic verified, container check passed, `verified: true`; second call returns `skipped: true` (idempotent) |
| `book_info(id=e7c75dc…)` | metadata via ads-page fallback (title/authors) |
| `sources_status()` | all five sources reported with state/note |
| stdio handshake | `bookfetch-mcp` spawned as a subprocess via `mcp.client.stdio`; `list_tools` returns all four tools |

### CLI E2E (installed `cli-anything-bookfetch`) — 5 passed (BOOKFETCH_E2E=1)

| Test | Artifact / proof |
|---|---|
| `--json search "Dune" --author "Frank Herbert"` | exit 0; envelope `ok: true`, meta.software `bookfetch`; candidates[0].source `libgen` |
| `--json get --id e7c75dc… --out tmp` | exit 0; file on disk, `PK` magic, >100 kB, `verified: true`; re-run → `skipped: true` |
| `--json get --id … --dry-run --out tmp` | exit 0; `dry_run: true`; **zero files written** |
| `--json get` (no args) | exit **2**; `error.code "usage"` |
| `--json sources` | exit 0; five sources |

### Fresh-shell contract check

`pip install -e .` in the user environment → both console scripts on PATH
(`cli-anything-bookfetch.exe`, `bookfetch-mcp.exe`);
`cli-anything-bookfetch --json sources` from a fresh shell returned a valid envelope (ok, data, error, meta, warnings).

### Scorer

`python scripts/score_harness.py <harness> --json` → **91.2 / grade A** (target ≥ 80).
Unmet items, both scoped to the binary-backend model and N/A for this HTTP seam (no executable is run —
the "backend" is a set of web endpoints with HTTP sessions):
- `backend: PATH resolution` (checks for `shutil.which`)
- `backend: argv list, no shell` (checks for `subprocess.run` in the backend module)
Everything that has an honest analogue (adapter module, env override, timeouts, typed errors) is implemented in `core/client.py`.

## Notes

- Fixtures under `tests/fixtures/` are real captures from the live-probe session (libgen results table,
  Gutenberg search page, Open Library JSON, Standard Ebooks catalog) — not synthetic.
- E2E downloads target a temp dir; `BOOKFETCH_OUT`/`--out` always contained, never `~/` by accident.
