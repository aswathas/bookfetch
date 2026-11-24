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

## D6 — The code tool's timeout is a parameter, not a constant
- Date: 2026-11-21
- Prompt: "run pototemod mode serparete l analyse and test this , for now lets test our bookfetch myself , lets download this essential for ai mathematics book by oreily"
- Context: the live test downloaded a 3.4 MB PDF in 45 s through code mode, but the 17 MB Mathematics for Machine Learning PDF was killed by the fixed 60 s wall, twice, once at 60 s and once at 300 s.
- Options:
  - Keep the fixed 60 s wall — a large book can never be fetched through the tool, which is the tool's main use.
  - Raise the wall to a large constant — still wrong for a slow mirror, and the caller still cannot choose.
  - Make the timeout an argument, clamped to 10–600 s — the caller pays for the wait it actually needs, and the cap keeps one call from hanging the server.
- Chosen: the argument. Default stays 60 s so a runaway script still dies quickly; a download can ask for up to 600 s.
- Evidence: live MCP call `bookfetch_code(code=..., timeout=600)`; a 3.4 MB PDF verified (`%PDF-1.5`, 3444468 bytes) through the tool with the default timeout.
- Consequence: the tool schema grew by 116 bytes (1823 bytes total).

## D7 — The sandbox fence limits the environment, not the filesystem
- Date: 2026-11-21
- Prompt: "but am going to run everything local only?"
- Context: review of the fence found that the allow-listed environment stops the child reading API keys from the environment, but the child still runs as this user and can read any file this user can read, including `~/.aws`, SSH keys and browser profiles.
- Options:
  - Claim the sandbox is a security boundary — it is not, and saying so would be wrong.
  - Say it plainly in the tool docstring, which is what the agent reads before writing code — the honest place for the limit.
- Chosen: state the limit in the tool docstring. The engine's own download path is unchanged; the tool is for local use only.
- Evidence: the docstring now says the fence limits what the environment leaks, not what the filesystem holds, and says to treat book-source strings as data.
- Consequence: a caller who pastes untrusted text into the tool is the weak point, not the network.

## D8 — The sandbox child gets a closed stdin
- Date: 2026-11-21
- Prompt: "test the code mode adn"
- Decision it produced: D8.
- Context: the code-mode test matrix failed. Every call through the MCP server hung until the 60 s wall and returned nothing, while the identical code run standalone took 0.2 s. An isolated probe with three subprocess variants inside the server showed the plain call and the `-I` call both hanging, and only the one with `stdin=subprocess.DEVNULL` returning immediately.
- Options:
  - Leave the child inheriting stdin and treat it as an MCP quirk — the tool would be unusable through its only client.
  - Close the child's stdin — the child has no use for the protocol pipe, and a script that read it could corrupt the JSON-RPC stream.
- Chosen: `stdin=subprocess.DEVNULL` on the child.
- Evidence: probe results above; the nine-case matrix through the real server now returns in 0.2 s per case; `test_child_stdin_is_closed` reads stdin and gets 0 bytes; 50 unit tests pass.
- Consequence: the tool works through a real MCP client for the first time. Before this, only the standalone path had ever worked.

## D9 — The sandbox uses a Windows Job Object, not a PID walk
- Date: 2026-11-21
- Prompt: "test the code mode adn" (the second-opinion review reported ten findings)
- Context: the review found that killing the process tree by PID does not reach descendants whose own parent already exited, and that Windows' CIM `ParentProcessId` filter does not find them either, so a script could leave a background process running past the call. A supervisor process was tried first and did not close the gap. A Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` does: every descendant dies when the job handle closes.
- Options:
  - Sweep orphans by parent PID through PowerShell — does not work, the CIM filter does not match a reparented orphan.
  - Supervisor process that outlives the script — the supervisor's own children still survive it.
  - Job Object — one handle, every descendant dies, works whether the script exits early or is killed.
- Chosen: the Job Object, with `taskkill /T` kept as the timeout path and POSIX using a process group.
- Evidence: `AssignProcessToJobObject` returns True on this box; a child placed in the job is dead after the handle closes; `test_background_descendant_does_not_survive` passes and no `bookfetch-code-*` directory leaks.
- Consequence: a script can no longer outlive the call by spawning a background process.

## D10 — The code tool refuses at call time unless the server was started on stdio
- Date: 2026-11-21
- Prompt: "test the code mode adn"
- Context: the HTTP guard read `BOOKFETCH_MCP_TRANSPORT` at import time, but the transport is chosen when the server runs. A launcher that sets the transport at run time (`fastmcp run ... --transport http`) would have served code execution over HTTP with no authentication.
- Options:
  - Keep the import-time check — the guard and the decision can disagree.
  - Move the check to call time — the tool is always registered but refuses unless the server was started by `main()` on stdio.
  - Drop the guard — no.
- Chosen: the call-time check. `main()` sets the flag when it serves stdio; any other launcher leaves it unset and the tool refuses.
- Evidence: with `BOOKFETCH_MCP_TRANSPORT=streamable-http` the tool is not registered at all; calling the tool on a server that was not started on stdio returns `[refused] code mode runs only on the local stdio transport`.
- Consequence: the guard follows the transport actually in use.

## D11 — The tool's own docstring no longer claims the environment is safe
- Date: 2026-11-21
- Prompt: "test the code mode adn"
- Context: the review showed `HOME` and `USERPROFILE` stay in the child environment and the filesystem is not fenced, so a script can read `~/.claude/.credentials.json` and print it into the agent's context. The docstring said "allow-listed environment (no API keys)", which reads as a guarantee the fence does not give.
- Options:
  - Fence the filesystem — the child needs to read the book sources and write downloads, and the same user can read those files from anywhere.
  - Drop the misleading claim — the environment allow-list stops secrets in environment variables from being handed over; it is not a filesystem boundary.
- Chosen: the honest wording. The docstring now says the fence limits what the environment leaks, not what the filesystem holds, and says the script can read any file this user can read.
- Evidence: the docstring text in `mcp_server.py` and the module docstring in `code_mode.py`.
- Consequence: a caller who puts a secret in the code, or lets untrusted book metadata steer the code, is the weak point. Both are now named in the tool's own description, where the agent reads them before writing code.
