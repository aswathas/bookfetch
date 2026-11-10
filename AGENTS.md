# bookfetch

A book-fetching system: ask for any book by name, get a verified file on disk.
One pip package, two frontends over a shared core:

- **MCP server** (`bookfetch-mcp`, stdio) — for Claude Desktop / AI chat agents
- **CLI** (`cli-anything-bookfetch`) — for CLI agents and humans

The pip package lives in `agent-harness/`.

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature>/` (spec + numbered tickets). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage` ... `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Layout

- `agent-harness/` — the pip package: core engine, source adapters, MCP server, CLI, tests
- `docs/design/` — design docs (source of truth for intent)
- `docs/agents/` — per-repo skill configuration
- `.scratch/` — issue tracker (specs + tickets)

## Dev loop

```bash
cd agent-harness
pip install -e .
python -m unittest discover -s cli_anything/bookfetch/tests -v
bookfetch-mcp                      # stdio MCP server
cli-anything-bookfetch --json ...  # one-shot CLI; bare invocation enters REPL
```
