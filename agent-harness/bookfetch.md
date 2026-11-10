# bookfetch harness notes

## Backend

The harness shells out to `bookfetch`. Resolution order:

1. `CLI_ANYTHING_BOOKFETCH_BIN`
2. `bookfetch` on `PATH`
3. the literal name `bookfetch`

## Commands

| Command | Purpose |
|---------|---------|
| `run <args...>` | Execute `bookfetch` with arbitrary arguments |
| `status` | Show backend resolution and session summary |
| `history` | List recorded operations |
| `undo` / `redo` | Move through the session history |

## Session

Stored at `~/.cli-anything/bookfetch/session.json` (override with `CLI_ANYTHING_HOME`
or `--session`). Writes are atomic and lock-guarded.
