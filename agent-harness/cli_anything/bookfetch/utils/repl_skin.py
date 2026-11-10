"""Minimal shared REPL wrapper for the bookfetch harness."""

from __future__ import annotations

import shlex

import click


def run_repl(group, obj):
    click.echo(f"bookfetch CLI")
    click.echo("type 'help' for commands, 'exit' to quit")
    while True:
        try:
            line = input("bookfetch> ")
        except (EOFError, KeyboardInterrupt):
            click.echo()
            return
        line = line.strip()
        if not line:
            continue
        if line in {"exit", "quit"}:
            return
        if line in {"help", "?"}:
            click.echo(group.get_help(click.Context(group)))
            continue
        try:
            group.main(args=shlex.split(line), standalone_mode=False)
        except SystemExit:
            pass
        except click.ClickException as exc:
            exc.show()
        except Exception as exc:  # noqa: BLE001 - REPL must not die on user input
            click.echo(f"error: {exc}", err=True)
