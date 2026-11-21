"""Code mode sandbox tests (no network: the engine is never called)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cli_anything.bookfetch.code_mode import run_code  # noqa: E402


class SandboxTest(unittest.TestCase):
    def test_stdout_is_returned(self):
        res = run_code("print('hello')")
        self.assertEqual(res["stdout"].strip(), "hello")
        self.assertFalse(res["timed_out"])
        self.assertEqual(res["exit_code"], 0)

    def test_stderr_is_captured_not_raised(self):
        res = run_code("raise SystemExit('boom')")
        self.assertTrue(res["stderr"].strip())
        self.assertNotEqual(res["exit_code"], 0)

    def test_environment_is_allow_listed(self):
        res = run_code("import os; print(sorted(os.environ))")
        keys = eval(res["stdout"].strip())
        for leaked in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN"):
            self.assertNotIn(leaked, keys)

    def test_working_directory_is_temporary_and_removed(self):
        res = run_code("import os; print(os.getcwd())")
        workdir = res["stdout"].strip()
        self.assertTrue(workdir.endswith("bookfetch-code-") or "bookfetch-code-" in workdir)
        self.assertFalse(Path(workdir).exists())

    def test_timeout_kills_the_script(self):
        res = run_code("while True:\n    pass\n", timeout=5)
        self.assertTrue(res["timed_out"])
        self.assertIsNotNone(res["exit_code"])


if __name__ == "__main__":
    unittest.main()
