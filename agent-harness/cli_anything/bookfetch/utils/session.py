"""JSON session state with atomic, lock-guarded writes."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


class Session:
    def __init__(self, software, path=None):
        base = Path(os.environ.get("CLI_ANYTHING_HOME", Path.home() / ".cli-anything"))
        self.path = Path(path) if path else base / software / "session.json"
        self._data = self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data.setdefault("history", [])
        data.setdefault("redo", [])
        data.setdefault("data", {})
        return data

    def _lock(self):
        lock = self.path.with_name(self.path.name + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return lock
            except FileExistsError:
                time.sleep(0.02)
        raise TimeoutError(f"could not lock session file: {lock}")

    def save(self):
        lock = self._lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=2)
            os.replace(tmp, self.path)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass

    def record(self, entry):
        self._data["history"].append(entry)
        self._data["redo"].clear()
        self.save()

    def undo(self):
        if not self._data["history"]:
            return None
        entry = self._data["history"].pop()
        self._data["redo"].append(entry)
        self.save()
        return entry

    def redo(self):
        if not self._data["redo"]:
            return None
        entry = self._data["redo"].pop()
        self._data["history"].append(entry)
        self.save()
        return entry

    def history(self):
        return list(self._data["history"])

    def redo_stack(self):
        return list(self._data["redo"])
