# Build log

What shipped, when, and where.

## 2026-11-21 — Code mode for bookfetch

**Where:** `agent-harness/cli_anything/bookfetch/`

The MCP server gained a `bookfetch_code` tool. It runs caller-supplied Python
with the bookfetch engine preloaded (`bookfetch` is the Engine, `sources` is the
Registry) and returns only what the script prints. The three plain tools
(`search_books`, `get_book`, `book_info`) are no longer registered as MCP tools;
`search_books`, `get_book` and `book_info` remain as plain functions in
`mcp_server.py` for the tests.

**Measured, live, same query ("dune"):**

| | Before | After |
|---|---|---|
| Tool schema, per session | 3192 bytes (~800 tokens) | 2220 bytes (~555 tokens) |
| One search result | 17660 bytes (~4400 tokens) | 44 bytes (~11 tokens) |

**The fence:** separate process, temporary working directory, allow-listed
environment (`PATH`, `SYSTEMROOT`, `COMSPEC`, `TEMP`, `TMP`, `HOME`,
`USERPROFILE`), 60 second timeout, process group killed on timeout, output
capped at 20000 characters. Network access stays open because the book sources
need it. The code tool is not registered when the server is served over HTTP
(`BOOKFETCH_MCP_TRANSPORT=streamable-http`).

**Checks:** `python -m unittest discover -s agent-harness/cli_anything/bookfetch/tests -t agent-harness`
-> 48 pass, 10 skipped (network E2E). `tests/test_code_mode.py` -> 5 pass.
`claude mcp list` -> bookfetch Connected.

**Also fixed:** the MCP entry in `C:\Users\ADMIN\.claude.json` pointed at a
console script that did not exist and was quadruple-escaped. It now runs
`python.exe -m cli_anything.bookfetch.mcp_server`.

**Decision record:** `docs/reviews/decision-log.md` (D1–D5).
**Design:** `C:\Users\ADMIN\.commandcode\plans\bookfetch-code-mode.md`, also in
`docs/design/2026-11-10-bookfetch-design.md`.
