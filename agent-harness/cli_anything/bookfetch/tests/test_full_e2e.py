"""E2E (installed CLI command, real network): set BOOKFETCH_E2E=1 to run."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[3]
HERBERT_MD5 = "e7c75dc2964ce80c19cb69140aae8614"  # real 781 kB EPUB captured during probing


def _resolve_cli():
    override = os.environ.get("CLI_ANYTHING_CLI")
    if override:
        return [override]
    exe = shutil.which("cli-anything-bookfetch")
    if exe:
        return [exe]
    if os.environ.get("CLI_ANYTHING_FORCE_INSTALLED"):
        raise RuntimeError("cli-anything-bookfetch not on PATH; run `pip install -e .` first")
    return [sys.executable, "-m", "cli_anything.bookfetch"]


@unittest.skipUnless(os.environ.get("BOOKFETCH_E2E"), "network E2E (set BOOKFETCH_E2E=1)")
class CliE2E(unittest.TestCase):
    def run_cli(self, *args, tmpdir=None):
        env = dict(os.environ, PYTHONPATH=str(HARNESS_ROOT))
        if tmpdir:
            env["BOOKFETCH_OUT"] = tmpdir
        return subprocess.run([*_resolve_cli(), *args], capture_output=True, text=True, env=env)

    def test_search_json(self):
        proc = self.run_cli("--json", "search", "Dune", "--author", "Frank Herbert", "--limit", "5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        j = json.loads(proc.stdout)
        self.assertTrue(j["ok"])
        self.assertGreater(len(j["data"]["candidates"]), 0)
        self.assertEqual(j["data"]["candidates"][0]["source"], "libgen")
        self.assertEqual(j["meta"]["software"], "bookfetch")

    def test_get_by_id_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli("--json", "get", "--id", HERBERT_MD5, "--out", tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            j = json.loads(proc.stdout)
            self.assertTrue(j["ok"], j)
            self.assertTrue(j["data"]["verified"])
            p = Path(j["data"]["path"])
            self.assertTrue(p.exists())
            raw = p.read_bytes()
            self.assertTrue(raw[:4] == b"PK\x03\x04" or raw[:5] == b"%PDF-")
            self.assertGreater(p.stat().st_size, 100_000)
            # re-run: same input, same end state (skip)
            proc2 = self.run_cli("--json", "get", "--id", HERBERT_MD5, "--out", tmp)
            j2 = json.loads(proc2.stdout)
            self.assertTrue(j2["data"]["skipped"])

    def test_dry_run_downloads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli("--json", "get", "--id", HERBERT_MD5, "--dry-run", "--out", tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            j = json.loads(proc.stdout)
            self.assertTrue(j["data"]["dry_run"])
            self.assertFalse(list(Path(tmp).iterdir()), "dry-run must not write files")

    def test_usage_error_exit_code(self):
        proc = self.run_cli("--json", "get")
        self.assertEqual(proc.returncode, 2)
        j = json.loads(proc.stdout)
        self.assertFalse(j["ok"])
        self.assertEqual(j["error"]["code"], "usage")

    def test_sources_json(self):
        proc = self.run_cli("--json", "sources")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        j = json.loads(proc.stdout)
        self.assertTrue(j["ok"])
        self.assertEqual(len(j["data"]["sources"]), 5)


if __name__ == "__main__":
    unittest.main()
