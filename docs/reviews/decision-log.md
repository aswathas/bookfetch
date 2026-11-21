# Decision log

One entry per real choice. Oldest first.

## D1 — Fix the broken MCP wiring by pointing at `python -m`, not by reinstalling
- Date: 2026-11-21
- Prompt: "connect bookfetch mcp"
- Context: `/mcp` reported `Couldn't reconnect to bookfetch: CONNECTION_CLOSED`. The configured command was `.venv\Scripts\bookfetch-mcp.exe`, and the venv (created by uv) had no console scripts at all — only `python.exe`, `pythonw.exe` and the activate scripts. `pip install -e` could not repair it because the venv has no setuptools and PyPI DNS is blocked on this machine.
- Options:
  - Reinstall the console script — blocked: no setuptools in the venv, no package index reachable.
  - Fetch a fresh copy from GitHub — unnecessary: the local source tree is intact and imports cleanly.
  - Point the MCP entry at `python.exe -m cli_anything.bookfetch.mcp_server` — works with the editable install that is already present.
- Chosen: the `python -m` entry, because it uses the install that already works and removes the missing-exe class of failure entirely.
- Evidence: `initialize` over stdio returned `{"serverInfo":{"name":"bookfetch","version":"1.30.0"}}`; `claude mcp list` -> `bookfetch: ... - ✔ Connected`.
- Consequence: the MCP server no longer depends on a generated `.exe`. The console-script entry point stays in `setup.py` for normal installs.

## D2 — Build our own code mode instead of using Claude Code's Code Mode
- Date: 2026-11-21
- Prompt: "i can understand taht we dont have official anthropic code mode , but lets crate our own code mode use /ultracave"
- Context: Claude Code 2.1.329 does ship an experimental Code Mode, but this machine cannot use it: `ANTHROPIC_BASE_URL` points at the MiniMax gateway, `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=TRUE`, and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. Anthropic's own "code execution with MCP" exists only on the Claude API. The user wanted the token saving anyway, in a form that works here.
- Options:
  - Claude Code Code Mode — unavailable on this box, three separate blockers.
  - Anthropic API programmatic tool calling — needs a first-party Anthropic account and a host app we do not run.
  - Ship code mode inside the bookfetch MCP server — works in every MCP client, at the cost of the server running caller-supplied code.
- Chosen: ship it inside the MCP server, because it is the only option that both works here and travels to other clients.
- Evidence: `verify_render.py` was not used; the code-mode path was measured directly against the running server (see the change inventory).
- Consequence: the bookfetch server now has the ability to execute Python. That capability is fenced (D4) and refused when the server is served over HTTP.

## D3 — One code tool replaces three plain tools; `sources_status` stays
- Date: 2026-11-21
- Prompt: "yes lets do this" (approving the diagram note `bookfetch-code-mode.md`)
- Context: the four plain tools cost 3192 bytes of schema in every session, and a `search_books` result cost 17660 bytes (~4400 tokens). The goal was to cut both.
- Options:
  - Keep all four tools and add the code tool — schema cost stays at ~800 tokens per session and the agent has two ways to do the same thing.
  - Replace `search_books`, `get_book` and `book_info` with one code tool — schema drops to 2220 bytes total (~555 tokens).
  - Add a field-selection parameter to the existing tools — safe, but not code mode and no single-tool shape.
- Chosen: replace the three, keep `sources_status` as a plain fallback tool so an agent that cannot write code still has one button.
- Evidence: `tools/list` after the change -> `sources_status` 513 bytes, `bookfetch_code` 1707 bytes, total 2220 bytes. A live `bookfetch_code` search for "dune" returned 44 bytes of output against 17660 bytes from the old `search_books`.
- Consequence: `search_books`, `get_book` and `book_info` remain as plain Python functions in `mcp_server.py` (the E2E tests still call them) but are no longer registered as MCP tools.

## D4 — Fence the code execution, and refuse it over HTTP
- Date: 2026-11-21
- Prompt: "but am going to run everything local only?"
- Context: the server executes caller-supplied code. The user confirmed the setup is local-only. `mcp_server.main()` already supports an HTTP transport (`BOOKFETCH_MCP_TRANSPORT=streamable-http`, port 8931), which would turn local code execution into a network-reachable one.
- Options:
  - No fence — unacceptable: the process would run with the user's full environment and the user's privileges.
  - Fence, and allow it on every transport — the HTTP mode would expose code execution to the network.
  - Fence, and register the code tool only on the stdio transport — the code tool is not offered at all when the server is served over HTTP.
- Chosen: the third. Fence: separate process, temporary working directory, allow-listed environment (`PATH`, `SYSTEMROOT`, `COMSPEC`, `TEMP`, `TMP`, `HOME`, `USERPROFILE`), 60 second timeout, process group killed on timeout, network still allowed because the book sources need it.
- Evidence: `tests/test_code_mode.py` — stdout captured, stderr captured without raising, no API keys in the child environment, working directory removed after the run, infinite loop killed at the timeout.
- Consequence: downloads still happen, but only to the `out_dir` the script names. Untrusted text from a book source is data, never an instruction.

## D5 — MCP-only install: drop the CLI console script
- Date: 2026-11-21
- Prompt: "lets use only mcp"
- Context: `setup.py` declared two console scripts. The user wanted MCP as the only interface, and the CLI entry point had in any case never been generated in the uv venv.
- Options:
  - Keep both entry points — the CLI stays installable but unused.
  - Keep only `bookfetch-mcp` — the package installs one way, the CLI module still runs with `python -m cli_anything.bookfetch.bookfetch_cli`.
- Chosen: keep only `bookfetch-mcp`. The CLI module and its tests stay; the README documents the module invocation.
- Evidence: `setup.py` diff shows one console script; README CLI section rewritten to `python -m ...`.
- Consequence: `pip install` no longer puts `cli-anything-bookfetch` on PATH.
