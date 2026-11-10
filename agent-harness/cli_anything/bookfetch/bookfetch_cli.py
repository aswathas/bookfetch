"""Command-line interface for bookfetch (cli-anything contract).

Envelope on stdout for --json:
  {"ok": bool, "data": ..., "error": {...}|null, "meta": {...}, "warnings": [...]}
Exit codes: 0 ok, 2 usage, 4 no/ambiguous match, 5 sources failed, 6 verification failed.
"""

from __future__ import annotations

import json

import click

from . import __version__
from .core.engine import Engine
from .core.errors import CliAnythingError, UsageError
from .core.registry import default_registry
from .utils.repl_skin import run_repl
from .utils.session import Session

SOFTWARE = "bookfetch"


def _meta(ctx) -> dict:
    return {
        "software": SOFTWARE,
        "version": __version__,
        "session": str(ctx.obj["session"].path),
    }


def _envelope(ctx, data, error=None, warnings=None) -> dict:
    if error is None:
        return {"ok": True, "data": data, "error": None, "meta": _meta(ctx), "warnings": warnings or []}
    return {"ok": False, "data": None, "error": error, "meta": _meta(ctx), "warnings": []}


def _emit(ctx, data, text: str | None = None, warnings: list | None = None):
    if ctx.obj["json"] or text is None:
        click.echo(json.dumps(_envelope(ctx, data, warnings=warnings), indent=2, default=str))
    else:
        click.echo(text)


def _fail(ctx, exc: CliAnythingError) -> int:
    err = exc.to_dict()
    if ctx.obj["json"]:
        click.echo(json.dumps(_envelope(ctx, None, error=err), indent=2, default=str))
    else:
        click.echo(f"error: {err['message']}", err=True)
        if err.get("hint"):
            click.echo(f"hint: {err['hint']}", err=True)
    return exc.exit_code


def _engine(ctx, out_dir=None) -> Engine:
    return Engine(default_registry(), out_dir=out_dir, session=ctx.obj["session"])


def _print_candidates(cands, failures=None) -> str:
    lines = ["#", "ref", "source", "title", "author", "year", "fmt", "size"]
    rows = ["|".join(lines)]
    for i, c in enumerate(cands, 1):
        fmts = ",".join(sorted(c.formats)) or "?"
        size = c.formats.get(fmts.split(",")[0], 0) if c.formats else 0
        size_s = f"{size // 1024}KB" if size else "?"
        rows.append(
            f"{i}|{c.ref[:12]}|{c.source}|{c.title[:40]}|"
            f"{(c.authors[0] if c.authors else '')[:25]}|{c.year}|{fmts}|{size_s}"
        )
    if failures:
        rows.append("")
        for f in failures:
            rows.append(f"  [{f['source']}] {f['error'][:100]}")
    return "\n".join(rows)


@click.group(invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output.")
@click.option("--session", "session_path", type=click.Path(), default=None, help="Override the session file.")
@click.pass_context
def cli(ctx, json_output, session_path):
    """Fetch any book by name from libgen and open-access fallbacks."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output
    ctx.obj["session"] = Session(SOFTWARE, path=session_path)
    if ctx.invoked_subcommand is None:
        run_repl(cli, ctx.obj)


@cli.command()
@click.argument("query")
@click.option("--author", default=None, help="Author to disambiguate.")
@click.option("--year", default=None, help="Publication year to disambiguate.")
@click.option("--limit", default=10, show_default=True, help="Max candidates.")
@click.pass_context
def search(ctx, query, author, year, limit):
    """Search book sources; the first source with matches wins."""
    try:
        cands, failures = _engine(ctx).search(query, author=author, year=year, limit=limit)
    except CliAnythingError as exc:
        raise SystemExit(_fail(ctx, exc))
    if not cands:
        _emit(ctx, {"candidates": [], "failures": failures},
              text="no candidates from any source", warnings=[f["source"] for f in failures])
        raise SystemExit(4)
    _emit(ctx, {"candidates": [c.to_dict() for c in cands], "failures": failures},
          text=_print_candidates(cands, failures))


@cli.command("get")
@click.argument("query", required=False)
@click.option("--id", "ref", default=None, help="Stable ref from search (md5 for libgen).")
@click.option("--source", default=None, help="Source for --id (inferred when omitted).")
@click.option("--author", default=None, help="Author to disambiguate the query.")
@click.option("--year", default=None, help="Year to disambiguate the query.")
@click.option("--format", "fmt", default=None, help="Force a format (pdf, epub, ...).")
@click.option("--out", "out_dir", type=click.Path(), default=None, help="Output directory.")
@click.option("--dry-run", is_flag=True, help="Resolve the plan without downloading.")
@click.pass_context
def get(ctx, query, ref, source, author, year, fmt, out_dir, dry_run):
    """Fetch a book: search, pick, download, verify, save."""
    if not query and not ref:
        raise SystemExit(_fail(ctx, UsageError("pass a query or --id")))
    engine = _engine(ctx, out_dir=out_dir)
    try:
        result = engine.get(query=query, ref=ref, source=source, author=author, year=year,
                            fmt=fmt, dry_run=dry_run, out_dir=out_dir)
    except CliAnythingError as exc:
        raise SystemExit(_fail(ctx, exc))
    if dry_run:
        _emit(ctx, {"dry_run": True, **result.to_dict()},
              text=f"plan: {result.source} {result.ref} -> {result.path} (format {result.format})")
        return
    _emit(ctx, result.to_dict(),
          text=f"saved: {result.path} ({result.size} bytes, {result.format}, source={result.source})"
          + (" [skipped, already existed]" if result.skipped else ""))


@cli.command()
@click.argument("ref")
@click.option("--source", default=None, help="Source for the ref (inferred when omitted).")
@click.option("--query", default=None, help="Query text used to find the ref on non-libgen sources.")
@click.pass_context
def info(ctx, ref, source, query):
    """Show full metadata for one book ref."""
    engine = _engine(ctx)
    try:
        cand = engine.book_info(ref, source=source, query=query)
    except CliAnythingError as exc:
        raise SystemExit(_fail(ctx, exc))
    _emit(ctx, cand.to_dict(),
          text=f"{cand.title} — {', '.join(cand.authors)} ({cand.year}) [{cand.source}:{cand.ref}]")


@cli.command()
@click.argument("check", required=False)
@click.pass_context
def sources(ctx, check):
    """List sources and their health. 'sources check' probes each one live."""
    registry = default_registry()
    if check:
        for s in registry.sources:
            try:
                s.search("test", limit=1)
            except CliAnythingError:
                pass
            except Exception as e:  # noqa: BLE001
                s.set_state("down", str(e)[:120])
    statuses = [st.to_dict() for st in registry.status()]
    rows = [f"{st['name']:<16}{st['state']:<10}{st['note'][:60]}" for st in statuses]
    _emit(ctx, {"sources": statuses}, text="\n".join(rows))


@cli.command()
@click.pass_context
def history(ctx):
    """List recorded downloads."""
    _emit(ctx, {"history": ctx.obj["session"].history()})


@cli.command()
@click.pass_context
def undo(ctx):
    """Undo the last recorded operation (bookkeeping only; files are kept)."""
    entry = ctx.obj["session"].undo()
    if entry is None:
        raise SystemExit(_fail(ctx, UsageError("nothing to undo")))
    _emit(ctx, {"undone": entry}, text=f"undone: {entry.get('op')} {entry.get('path', entry.get('title', ''))}")


@cli.command()
@click.pass_context
def redo(ctx):
    """Redo the last undone operation (bookkeeping only)."""
    entry = ctx.obj["session"].redo()
    if entry is None:
        raise SystemExit(_fail(ctx, UsageError("nothing to redo")))
    _emit(ctx, {"redone": entry}, text=f"redone: {entry.get('op')} {entry.get('path', entry.get('title', ''))}")


def main():
    try:
        cli(obj={})
    except SystemExit:
        raise
    except CliAnythingError as exc:  # noqa: BLE001 - last-resort mapping
        raise SystemExit(exc.exit_code)


if __name__ == "__main__":
    main()
