# Change inventory

One row per changed file.

| File | What changed | Why | How tested |
|---|---|---|---|
| `agent-harness/cli_anything/bookfetch/code_mode.py` | New module: `run_code()` runs caller Python in a sandboxed subprocess (separate process, temp working dir, allow-listed env, 60 s timeout, process group killed on timeout); `BOOTSTRAP` preloads `bookfetch` (Engine) and `sources` (Registry) | The server must be able to run code so callers pay only for the fields they print | `tests/test_code_mode.py` — 5 tests, all pass; live MCP call returned 44 bytes for a search that used to cost 17660 bytes |
| `agent-harness/cli_anything/bookfetch/mcp_server.py` | Added the `bookfetch_code` tool, registered only when the transport is stdio; unregistered `search_books`, `get_book`, `book_info` (functions kept); module docstring rewritten | Cut schema cost (3192 -> 2220 bytes) and result cost (~4400 -> ~11 tokens per search); refuse code execution when the server is served over HTTP | `tools/list` over stdio -> `sources_status` + `bookfetch_code` only; `claude mcp list` -> Connected; full unit suite 48 pass / 10 skipped |
| `agent-harness/cli_anything/bookfetch/tests/test_code_mode.py` | New: 5 sandbox tests (stdout, stderr, environment allow-list, temp working dir removed, timeout kill) | The fence is the security boundary; it needs a check | `python -m unittest cli_anything.bookfetch.tests.test_code_mode -v` -> 5 ok |
| `agent-harness/cli_anything/bookfetch/tests/test_e2e_mcp.py` | Tool-list assertion now expects `bookfetch_code` + `sources_status` and asserts the three old tools are gone; new `test_bookfetch_code` E2E case | The registered tool set changed | Runs only with `BOOKFETCH_E2E=1` (network) |
| `agent-harness/setup.py` | Removed the `cli-anything-bookfetch` console script, kept `bookfetch-mcp` | MCP-only install, as asked | Diff inspection; `python -m cli_anything.bookfetch.bookfetch_cli` still runs |
| `agent-harness/README.md` | MCP section rewritten for code mode; CLI section switched to `python -m` invocation | The documented interface must match what ships | Read-back |
| `docs/reviews/decision-log.md` | New: D1–D5 | Commit discipline requires one record per real choice | Read-back |
| `docs/reviews/change-inventory.md` | New: this table | Commit discipline requires one row per changed file | Read-back |
| `docs/reviews/prompts.md` | New: the prompts that shaped the work | Commit discipline requires the prompt record | Read-back |
| `BUILDLOG.md` | New: what shipped when and where | Commit discipline requires the build log | Read-back |
| `docs/design/2026-11-10-bookfetch-design.md` | Added a code-mode section | The design doc would otherwise not describe the shipped frontend | Read-back |
| `C:\Users\ADMIN\.claude.json` (outside the repo) | The `bookfetch` MCP entry now runs `python.exe -m cli_anything.bookfetch.mcp_server`; the previous path was quadruple-escaped and pointed at a console script that did not exist | The MCP server refused to start (`CONNECTION_CLOSED`) | `claude mcp list` -> bookfetch Connected; `initialize` -> `bookfetch 1.30.0` |

## Follow-up: live test round (2026-11-21)

| File | What changed | Why | How tested |
|---|---|---|---|
| `agent-harness/cli_anything/bookfetch/mcp_server.py` | `bookfetch_code` gained a `timeout` argument, clamped to 10–600 s; the timeout message reports the actual limit | A 17 MB download was killed by the fixed 60 s wall during the live test | Live MCP call with `timeout=600`; a 3.4 MB PDF downloaded and verified in 45 s with the default |
| `agent-harness/cli_anything/bookfetch/code_mode.py` | After the process-group kill, `communicate()` is bounded by 10 s and falls back to `proc.kill()`; the child inserts the package root on `sys.path`; over-long output is cut with a `[truncated at N characters]` marker | A failed tree kill could block the caller forever with no answer; `-I` ignores `PYTHONPATH`, so a checkout that is not installed could leave the child unable to import the engine; a silent prefix looks like complete output | `python -m unittest discover` -> 49 pass, 11 skipped |
