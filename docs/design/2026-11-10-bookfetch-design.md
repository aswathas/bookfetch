# bookfetch — Design

Date: 2026-11-10. Status: approved (user confirmed all decisions; "lets start building").

## Intent and why

Ask for any book by name; receive a verified real file on disk. libgen.li is the richest
catalog, but its domain, layout, and anti-bot behavior rotate, and a single source is
fragile — the system must survive by falling back through other book sources. The user's
one-line mental model is "get me <book>", not "pick a mirror and parse its HTML".

Two audiences, one package:

- **MCP server** (`bookfetch-mcp`, stdio) for Claude Desktop / AI chat agents
- **CLI** (`cli-anything-bookfetch`) for CLI agents and humans

Both frontends call the same core, so behavior can never drift.

## Approaches considered

1. **Single-source HTML scraper (libgen only).** Rejected: dies with the next site
   rotation; no fallback story; the user explicitly wants "any book, any source".
2. **Two separate packages (mcp + cli).** Rejected: duplicated source logic, guaranteed drift.
3. **Chosen: one pip package, two entry points, shared source-registry core.**
   MCP server is built and proven first (phase 1), CLI second (phase 2).

## Goals

- `get <book>` returns a verified file (PDF preferred, EPUB second) into `C:\Users\aswat\Books`
- Every fallback step is visible: which source answered, which failed, and why
- Idempotent: re-running skips files that already exist
- Non-interactive one-shot mode; `--json` on every data command; `--dry-run` on mutations
- Sources in order: libgen.li → libgen-embedded mirror links → Open Library→archive.org →
  Project Gutenberg → Standard Ebooks. Anna's Archive adapter ships but self-disables
  behind DDoS-Guard (proven blocked from this network).

## Non-goals / anti-goals

- No batch downloads in v1 (one book per call)
- No lending/DRM (archive.org borrowable items are skipped; only open files)
- No format conversion
- **Anti-goal (failure even if technically "works"):** downloading the wrong book —
  match quality is first-class; ambiguous matches stop with a candidate list, no download
- **Anti-goal:** exit 0 on a corrupt/HTML/anti-bot file — artifacts are verified or the
  command fails (exit 6)
- **Anti-goal:** hanging on a dead source — per-source timeouts and health states

## Proven facts (live probes, 2026-11-10, from this machine)

### libgen.li (primary)

The site serves a Nuxt 3 SPA at `/` *and* the legacy PHP app, which is our stable seam.

- **Search:** `GET https://libgen.li/index.php/?req=<query>` (200, legacy XHTML).
  Results table `#tablelibgen`; header row:
  `ID | Time add. | Title | Series | Author(s) | Publisher | Year | Language | Pages | Size | Ext. | Mirrors`.
  Per-row links: `edition.php?id=<edition_id>` (detail), `/file.php?id=<file_id>`,
  `/get.php?md5=<md5>` (download), plus embedded mirror links (Anna's Archive md5 page,
  `libgen.pw/book/<md5>`, `libgen.me/book/<md5>`, `randombook.org/book/<md5>`).
- **Download chain (two-step anti-bot, verified end-to-end):**
  1. Prime session: `GET /index.php/` (sets cookies `res`, `objects`, `curtab`, …)
  2. `GET /get.php?md5=<md5>` → redirects to `/ads.php?md5=<md5>` interstitial
  3. Parse the one-time key from the interstitial:
     `<a href="get.php?md5=<md5>&key=<KEY>"><h2>GET</h2></a>`
  4. `GET /get.php?md5=<md5>&key=<KEY>` → redirects to CDN (`cdn3.booksdl.lc`) →
     `application/octet-stream` file bytes
- **Verified artifact:** 800,094-byte EPUB (*Dune*, Frank Herbert), valid container
  (`mimetype = application/epub+zip`, 98 entries, correct OPF title/creator).
- **Flakiness observed:** the Nuxt SPA sometimes serves `/`; always use the
  `index.php/...` legacy paths.

### Fallback sources

- **Open Library:** `api.openlibrary.org` is DNS-blocked here; the main domain works:
  `GET https://openlibrary.org/search.json?q=<query>&fields=key,title,author_name,ia,first_publish_year`.
  Results carry `ia` (Internet Archive) identifiers.
  **Download chain (verified):** `GET https://archive.org/metadata/<ia>` → file list →
  `GET https://archive.org/download/<ia>/<file>` (redirects to `*.ca.archive.org`) → bytes.
  Verified: 1.4MB *Pride and Prejudice* EPUB. Public-domain only.
- **Project Gutenberg:** JSON search endpoint is dead (404); HTML search works:
  `GET https://www.gutenberg.org/ebooks/search/?q=<query>`.
  **Download (verified):** `GET https://www.gutenberg.org/ebooks/<id>.epub` →
  `/cache/epub/<id>/pg<id>.epub`. Verified: 136,756-byte EPUB. Public-domain only.
- **Standard Ebooks:** reachable (home 200) but intermittent SSL timeouts; machine-readable
  surface is OPDS (`/feeds/opds/new-releases`, `/opensearch`) plus per-book EPUB pages.
  Small curated catalog; lowest priority.
- **Anna's Archive:** `annas-archive.gl` web loads (200) but `/search` returns 403
  DDoS-Guard JS challenge → headless search unusable from this network. Adapter ships,
  detects the challenge, and degrades (skips with a reason) instead of failing the query.
  Its md5-page links embedded in libgen rows are attempted as mirror links and may also
  403 — same graceful-skip behavior.

## Architecture

```
agent-harness/                        # pip package "cli-anything-bookfetch"
└── cli_anything/bookfetch/
    ├── core/
    │   ├── client.py                 # backend resolution: endpoints, env overrides, timeouts
    │   ├── config.py                 # optional YAML config (yaml.safe_load): out_dir, disabled_sources
    │   ├── errors.py                 # typed errors → exit codes (one mapping site)
    │   ├── models.py                 # Book, Candidate, DownloadResult, SourceStatus
    │   ├── registry.py               # ordered Source registry + health + failover
    │   ├── match.py                  # candidate scoring: title+author(+year) → best/ambiguous
    │   ├── verify.py                 # magic bytes + EPUB/PDF container validation
    │   ├── session.py                # download log, atomic writes (reuses scaffold Session)
    │   └── sources/
    │       ├── base.py               # Source ABC: name, search(), download(md5_or_url), health()
    │       ├── libgen.py             # legacy PHP: search + two-step key download
    │       ├── mirror_links.py       # tier-2: links embedded in libgen rows
    │       ├── openlibrary.py        # search.json + archive.org chain
    │       ├── gutenberg.py          # HTML search + /ebooks/<id>.epub
    │       ├── standardebooks.py     # OPDS + per-book EPUB
    │       └── annasarchive.py       # search (ddos-guard detect → degrade)
    ├── mcp_server.py                 # stdio MCP: search_books, get_book, book_info, sources_status
    ├── bookfetch_cli.py              # CLI: search, get, info, sources (+ --json/--dry-run, REPL)
    ├── __main__.py
    └── tests/
        ├── test_core.py              # pure logic: parsers, match, verify, registry (no network)
        ├── test_e2e_mcp.py           # real network: MCP tool calls → verified file
        └── test_e2e_cli.py           # installed command: --json search/get → verified file
```

### Domain model

- **Source** — a named backend with `search(query, author, year) → [Candidate]`,
  `download(candidate) → bytes`, and a health state (`ok` / `degraded` / `down`).
- **Candidate** — one book edition from one source: `source`, `ref` (stable id: libgen md5,
  OL key, GUT id), `title`, `authors`, `year`, `language`, `formats: {ext: size}`, `mirrors: [url]`.
- **Book** — the chosen candidate after scoring.
- **DownloadResult** — `path`, `source`, `bytes`, `verified: true|false`, `format`, metadata.
- **Query** — `text`, optional `author`, optional `year`, optional `format`
  (default priority `pdf → epub → largest`).

### The get flow

```
query → for source in registry (healthy first, in fixed order):
          candidates = source.search(query)
          scored     = match.score(candidates, query)
          if scored.best is unambiguous:
             pick format per priority (pdf → epub → largest; --format overrides)
             bytes = source.download(candidate, format)   # libgen: two-step key chain
             ok    = verify(bytes, ext)                   # magic + container
             if ok and target file absent: write atomically, log to session
             return DownloadResult
          else:
          record "ambiguous at <source>" and continue? NO — see below
```

**Ambiguity rule (settled):** if the *first healthy source* (libgen) returns candidates,
ambiguity is terminal for the query — no download, exit with the numbered candidate list
(exit 4) so the user can `get --id`. Fallback to the next source happens only when a source
returns **zero** candidates or fails. Rationale: later sources can't resolve ambiguity
better than the primary's own catalog; a wrong-book download is the anti-goal.

**Deterministic path:** `get --id <ref>` (optionally `--source`) skips search and scoring.

### libgen download detail (only source with anti-bot)

Session cookie jar per source instance. `prime()` once per process. On interstitial:
parse `key` (regex `get\.php\?md5=<md5>&key=([A-Za-z0-9]+)`), refetch with key, follow to
CDN. If the key anchor is missing → `SourceFailed("no key issued")` → registry marks
libgen degraded and falls to mirrors. Timeouts: 25s page, 120s file. Output cap: 2GB.

### Verification (verify.py)

- PDF: `%PDF-` magic at byte 0 (or ≤1024 with comment prefix), size ≥ 10KB
- EPUB: `PK\x03\x04` magic, `mimetype` entry == `application/epub+zip`, has `*.opf`
- Other (docx/mobi/cbz/zip family): `PK` magic, non-empty, size ≥ 100KB for zips >1 entry
- Everything else (html/text/unknown): **fail** — this is the anti-bot-file detector

### Error taxonomy → exit codes (mapped in one place)

| Code | Meaning | When |
|---|---|---|
| 0 | success | verified file delivered (or dry-run printed) |
| 2 | usage error | bad args |
| 4 | ambiguous / no match | candidate list printed, nothing downloaded |
| 5 | all sources failed | per-source failure report printed |
| 6 | verification failed | bytes received but not a valid document |

### MCP tools (phase 1 surface)

1. `search_books(query, author?, year?, limit=10)` → `[Candidate]`
2. `get_book(id?, query?, author?, year?, format?, out_dir?)` → `DownloadResult`
3. `book_info(id)` → full candidate metadata
4. `sources_status()` → per-source health + last probe note

Tool errors return structured `{ok: false, error: {code, message, hint}}` with the same
codes as the CLI exit table.

### CLI surface (phase 2)

```
cli-anything-bookfetch [--json] [--session PATH] <command>
  search <query> [--author A] [--year Y] [--limit N]
  get <query|--id REF> [--source S] [--format F] [--out DIR] [--dry-run]
  info <id> [--source S]
  sources [check]
  history | undo | redo        # scaffold session commands
```
Bare invocation → REPL (scaffold repl_skin). `get --dry-run` prints the resolved plan
(source order, match, target path) without downloading.

## Testing and proof

- **Unit (no network):** parsers fed captured real HTML/JSON fixtures (saved from probes),
  match scoring, verify against synthetic + real magic bytes, registry failover order,
  session atomicity.
- **E2E MCP (real network, release run):** stdio client calls `search_books("Dune")`,
  asserts candidates; calls `get_book` for a small book, asserts file exists, magic
  verified, metadata matches.
- **E2E CLI (installed command):** `cli-anything-bookfetch --json search ...`, `get ...`
  from any cwd; artifact verified; re-run shows skip-existing (idempotency).
- **Scorer:** `python scripts/score_harness.py agent-harness` ≥ 80.
- Evidence recorded in `agent-harness/TEST.md`.

## Phases

1. **Phase 1 (MCP first):** core + registry + all six source adapters + MCP server;
   prove with real MCP tool calls; unit tests green.
2. **Phase 2 (CLI):** cli-anything frontend on the same core; prove with the installed
   command; scorer ≥ 80; README/SKILL.md/TEST.md finalized.

## Builder calls (mine, overridable)

- Candidate scoring weights: exact-title-token match > substring; author match doubles;
  year within ±3 adds a bonus; language==English small bonus.
- Per-source page timeout 25s, download 120s; registry probe on first use + `sources check`.
- `out_dir` default `C:\Users\aswat\Books`; filename `Author - Title (Year).<ext>`
  (year omitted if unknown), Windows-illegal chars stripped.
- Session file `~/.cli-anything/bookfetch/session.json` (scaffold default).
- Standard Ebooks treated as `degraded` by default (SSL flake observed) but attempted last.
