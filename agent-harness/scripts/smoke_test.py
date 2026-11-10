#!/usr/bin/env python
"""One-command smoke test for bookfetch (for humans and AI agents alike).

Usage:
    python agent-harness/scripts/smoke_test.py [--out DIR]

Checks (live network required):
    1. package imports
    2. sources_status
    3. search_books
    4. get_book by ref  -> real download + container verification

Prints one PASS/FAIL line per check, then "SMOKE TEST PASSED" (exit 0) or
"SMOKE TEST FAILED" (exit 1).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

SMOKE_REF = "e7c75dc2964ce80c19cb69140aae8614"  # real ~781 kB EPUB (Herbert, Dune)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="Download directory (default: temp dir)")
    args = ap.parse_args()

    results = []

    def check(name, fn):
        try:
            detail = fn()
            results.append((name, True, detail or ""))
            print(f"PASS  {name}  {detail or ''}")
        except Exception as e:  # noqa: BLE001
            results.append((name, False, str(e)))
            print(f"FAIL  {name}  {e}")

    def imports():
        from cli_anything.bookfetch import mcp_server

        return f"import ok ({mcp_server.__name__})"

    def status():
        from cli_anything.bookfetch import mcp_server

        j = json.loads(mcp_server.sources_status())
        if not j["ok"]:
            raise RuntimeError(j["error"]["message"])
        return f"{len(j['data']['sources'])} sources registered"

    def search():
        from cli_anything.bookfetch import mcp_server

        j = json.loads(mcp_server.search_books("Sapiens", author="Yuval Noah Harari", limit=5))
        if not j["ok"]:
            raise RuntimeError(f"{j['error']['code']}: {j['error']['message']}")
        return f"{len(j['data']['candidates'])} candidates"

    def download():
        from cli_anything.bookfetch import mcp_server

        out = args.out or tempfile.mkdtemp(prefix="bookfetch-smoke-")
        j = json.loads(mcp_server.get_book(id=SMOKE_REF, out_dir=out))
        if not j["ok"]:
            raise RuntimeError(f"{j['error']['code']}: {j['error']['message']}")
        p = Path(j["data"]["path"])
        if not p.exists():
            raise RuntimeError("file missing after download")
        raw = p.read_bytes()
        if not (raw[:4] == b"PK\x03\x04" or raw[:5] == b"%PDF-"):
            raise RuntimeError("bad container magic (not a real document)")
        return f"{p} ({p.stat().st_size} bytes, {j['data']['format']}, source={j['data']['source']})"

    check("import package", imports)
    check("sources_status", status)
    check("search_books (live)", search)
    check("get_book (live download + verify)", download)

    ok = all(r[1] for r in results)
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
