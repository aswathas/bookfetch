"""Code mode: run caller-written Python against the bookfetch engine.

The script runs in a separate process with the engine preloaded as `bookfetch`
and the source registry as `sources`. Only what the script prints comes back, so
the caller pays for the fields it asked for instead of the whole catalogue.

Sandbox: separate process, temporary working directory, allow-listed
environment (no API keys), hard timeout, process group killed on timeout,
stdin closed (the parent's stdin is the MCP protocol pipe; a child reading it
would hang, and could corrupt the stream).
Downloads still happen, but only where the script asks (out_dir).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The directory holding the `cli_anything` package. The child runs isolated
# (-I ignores PYTHONPATH), so a checkout that is not installed would otherwise
# leave the child unable to import the engine.
_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])

BOOTSTRAP = """\
import sys
sys.path.insert(0, {root!r})

from cli_anything.bookfetch.core.engine import Engine
from cli_anything.bookfetch.core.registry import default_registry

sources = default_registry()
bookfetch = Engine(sources)
""".format(root=_PACKAGE_ROOT)

# Environment the script may see. Anything else (API keys, tokens) stays out.
_ENV_KEEP = ("PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE")

MAX_OUTPUT = 20000


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except OSError:
            proc.kill()


def run_code(code: str, timeout: int = 60) -> dict:
    """Run code in a sandboxed subprocess.

    Returns {"stdout", "stderr", "timed_out", "exit_code"}.
    Output longer than MAX_OUTPUT is cut, and the cut is marked.
    """
    workdir = tempfile.mkdtemp(prefix="bookfetch-code-")
    env = {k: v for k, v in os.environ.items() if k in _ENV_KEEP}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", BOOTSTRAP + code],
        cwd=workdir, env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        **kwargs,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            # The tree kill did not take. Never block the caller on a stuck pipe.
            proc.kill()
            out, err = "", ""
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {
        "stdout": _cap(out),
        "stderr": _cap(err),
        "timed_out": timed_out,
        "exit_code": proc.returncode,
    }


def _cap(text: str) -> str:
    """Cut over-long output and say so, rather than returning a silent prefix."""
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n[truncated at {MAX_OUTPUT} characters]"
