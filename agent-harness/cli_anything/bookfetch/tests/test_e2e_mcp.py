"""E2E (real network + MCP stdio): set BOOKFETCH_E2E=1 to run."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[3]
HERBERT_MD5 = "e7c75dc2964ce80c19cb69140aae8614"  # real 781 kB EPUB captured during probing


def _ok(out: str) -> dict:
    j = json.loads(out)
    assert j["ok"], f"tool returned not-ok: {j}"
    return j


@unittest.skipUnless(os.environ.get("BOOKFETCH_E2E"), "network E2E (set BOOKFETCH_E2E=1)")
class McpToolE2E(unittest.TestCase):
    def test_search_books(self):
        from cli_anything.bookfetch import mcp_server

        j = _ok(mcp_server.search_books("Dune", author="Frank Herbert", limit=5))
        cands = j["data"]["candidates"]
        self.assertGreater(len(cands), 0)
        self.assertTrue(any(c["ref"] == HERBERT_MD5 for c in cands))

    def test_get_book_by_id(self):
        from cli_anything.bookfetch import mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            j = _ok(mcp_server.get_book(id=HERBERT_MD5, out_dir=tmp))
            data = j["data"]
            self.assertTrue(data["verified"])
            p = Path(data["path"])
            self.assertTrue(p.exists())
            raw = p.read_bytes()
            self.assertTrue(raw[:4] == b"PK\x03\x04" or raw[:5] == b"%PDF-", "bad container magic")
            self.assertIn("epub", data["format"].lower())
            # idempotency: second call skips the download
            j2 = _ok(mcp_server.get_book(id=HERBERT_MD5, out_dir=tmp))
            self.assertTrue(j2["data"]["skipped"])

    def test_sources_status(self):
        from cli_anything.bookfetch import mcp_server

        j = _ok(mcp_server.sources_status())
        names = {s["name"] for s in j["data"]["sources"]}
        self.assertEqual(names, {"libgen", "openlibrary", "gutenberg", "standardebooks", "annasarchive"})

    def test_book_info(self):
        from cli_anything.bookfetch import mcp_server

        j = _ok(mcp_server.book_info(id=HERBERT_MD5))
        self.assertEqual(j["data"]["ref"], HERBERT_MD5)
        self.assertTrue(j["data"]["title"])


@unittest.skipUnless(os.environ.get("BOOKFETCH_E2E"), "network E2E (set BOOKFETCH_E2E=1)")
class McpStdioHandshake(unittest.TestCase):
    def test_stdio_tools_list(self):
        import asyncio

        import mcp.client.stdio as s
        from mcp import ClientSession, StdioServerParameters

        async def run():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "cli_anything.bookfetch.mcp_server"],
                env={**os.environ, "PYTHONPATH": str(HARNESS_ROOT)},
            )
            async with s.stdio_client(params) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return [t.name for t in tools.tools]

        names = asyncio.run(run())
        for n in ("search_books", "get_book", "book_info", "sources_status"):
            self.assertIn(n, names)


if __name__ == "__main__":
    unittest.main()
