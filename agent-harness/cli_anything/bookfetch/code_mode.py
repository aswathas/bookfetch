"""Code mode: run caller-written Python against the bookfetch engine.

The script runs in a separate process with the engine preloaded as `bookfetch`
and the source registry as `sources`. Only what the script prints comes back, so
the caller pays for the fields it asked for instead of the whole catalogue.

Sandbox: separate process, temporary working directory, allow-listed
environment, hard timeout, whole process tree killed, stdin closed (the parent's
stdin is the MCP protocol pipe; a child reading it would hang, and could
corrupt the stream).

The fence limits what the environment leaks, not what the filesystem holds. The
child runs as this user and can read any file this user can read, credentials
included. The environment allow-list exists so secrets sitting in environment
variables are not handed over for free. It is not a filesystem boundary.

On Windows the script is placed in a Job Object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Every descendant the script creates dies
when the job handle closes, so a script that leaves a background process
behind cannot outlive the call. On POSIX the script leads its own process group
and the group is killed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

# The directory holding the `cli_anything` package. The child runs isolated
# (-I ignores PYTHONPATH), so a checkout that is not installed would otherwise
# leave the child unable to import the engine.
_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])

# Prepended to the caller's script so the engine is in scope.
_BOOTSTRAP = """\
import sys
sys.path.insert(0, {root!r})

from cli_anything.bookfetch.core.engine import Engine
from cli_anything.bookfetch.core.registry import default_registry

sources = default_registry()
bookfetch = Engine(sources)
""".format(root=_PACKAGE_ROOT)

# Environment the script may see. Anything else (API keys, tokens) stays out.
_ENV_KEEP = (
    "PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
    "PYTHONUNBUFFERED",
)

MAX_OUTPUT = 20000
_GRACE = 5

_JOB_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _WindowsJob:
    """A Windows Job Object that kills every process in it when closed."""

    def __init__(self):
        self.handle = None
        self._kernel32 = None

    def create(self):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        class _BasicLimit(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(f"Counter{i}", ctypes.c_uint64) for i in range(6)]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimit),
                        ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_LIMIT_KILL_ON_JOB_CLOSE
        # JobObjectExtendedLimitInformation == 9
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(err)

        self._kernel32 = kernel32
        self.handle = handle

    def assign(self, proc: subprocess.Popen) -> bool:
        import ctypes

        try:
            return bool(self._kernel32.AssignProcessToJobObject(
                self.handle, wintypes_cast(proc._handle)))
        except Exception:
            return False

    def close(self) -> None:
        if self.handle is not None:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def wintypes_cast(value):
    import ctypes
    return ctypes.c_void_p(int(value))


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and everything it started."""
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


def _drain(stream, sink: list, cap: int) -> None:
    """Read a pipe into a bounded buffer. Never let a chatty script grow memory.

    The pipes are binary on purpose, and read1() is used rather than read():
    read(n) blocks until n bytes arrive or the pipe reaches EOF, so a small
    print would sit unread while a surviving descendant held the pipe open.
    """
    read = 0
    try:
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            if read < cap:
                room = cap - read
                sink.append(chunk[:room])
                read += len(chunk[:room])
    except (ValueError, OSError):
        pass
    finally:
        try:
            stream.close()
        except (ValueError, OSError):
            pass


def run_code(code: str, timeout: int = 60) -> dict:
    """Run code in a sandboxed subprocess.

    Returns {"stdout", "stderr", "timed_out", "exit_code"}.
    Output longer than MAX_OUTPUT is cut, and the cut is marked.
    """
    workdir = tempfile.mkdtemp(prefix="bookfetch-code-")
    script_path = os.path.join(workdir, "script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(_BOOTSTRAP + code)

    env = {k: v for k, v in os.environ.items() if k in _ENV_KEEP}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    job = None
    try:
        if os.name == "nt":
            job = _WindowsJob()
            try:
                job.create()
            except Exception:
                job = None

        proc = subprocess.Popen(
            [sys.executable, "-I", script_path],
            cwd=workdir, env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **kwargs,
        )

        if job is not None and not job.assign(proc):
            # Nested jobs are not always allowed. The tree kill below still works
            # for the common case; descendants that outlive the script are the
            # known gap, and the job handle is closed either way.
            job.close()
            job = None

        out_chunks: list = []
        err_chunks: list = []
        readers = [
            # One byte over the cap, so a truncated stream is distinguishable
            # from one that happened to end exactly at the limit.
            threading.Thread(target=_drain, args=(proc.stdout, out_chunks, MAX_OUTPUT + 1), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, err_chunks, MAX_OUTPUT + 1), daemon=True),
        ]
        for r in readers:
            r.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                proc.wait(timeout=_GRACE)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=_GRACE)
                except subprocess.TimeoutExpired:
                    pass

        # Closing the job kills every descendant, which closes the pipes and
        # lets the readers reach EOF.
        if job is not None:
            job.close()
            job = None

        for r in readers:
            r.join(timeout=_GRACE)

        exit_code = proc.returncode
        shutil.rmtree(workdir, ignore_errors=True)
        return {
            "stdout": _cap(b"".join(out_chunks).decode("utf-8", "replace")),
            "stderr": _cap(b"".join(err_chunks).decode("utf-8", "replace")),
            "timed_out": timed_out,
            "exit_code": exit_code,
        }
    finally:
        if job is not None:
            job.close()
        shutil.rmtree(workdir, ignore_errors=True)


def _cap(text: str) -> str:
    """Cut over-long output and say so, rather than returning a silent prefix."""
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n[truncated at {MAX_OUTPUT} characters]"
