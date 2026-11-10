"""Unit tests: pure logic, real captured fixtures, no network."""

import io
import json
import os
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

from cli_anything.bookfetch.core import config
from cli_anything.bookfetch.core.engine import Engine, choose_format, sanitize_name, target_path
from cli_anything.bookfetch.core.errors import SourceFailedError, UsageError
from cli_anything.bookfetch.core.match import pick_best
from cli_anything.bookfetch.core.models import Candidate
from cli_anything.bookfetch.core.registry import Registry, default_registry, infer_source
from cli_anything.bookfetch.core.sources.base import Source
from cli_anything.bookfetch.core.sources.gutenberg import parse_search
from cli_anything.bookfetch.core.sources.libgen import parse_results, parse_size
from cli_anything.bookfetch.core.sources.openlibrary import parse_docs
from cli_anything.bookfetch.core.sources.standardebooks import LINK_RE
from cli_anything.bookfetch.core.verify import verify
from cli_anything.bookfetch.utils.session import Session

FIX = Path(__file__).parent / "fixtures"
HERBERT_MD5 = "e7c75dc2964ce80c19cb69140aae8614"


def load(name: str, binary: bool = False):
    p = FIX / name
    return p.read_bytes() if binary else p.read_text(encoding="utf-8", errors="replace")


class LibgenParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cands = parse_results(load("libgen_results.html"))

    def test_parses_many_rows(self):
        self.assertGreaterEqual(len(self.cands), 10)

    def test_herbert_dune_row(self):
        row = next(c for c in self.cands if c.ref == HERBERT_MD5)
        self.assertIn("Dune", row.title)
        self.assertTrue(any("herbert" in a.lower() for a in row.authors))
        self.assertEqual(row.formats.get("epub"), 781 * 1024)
        self.assertEqual(row.language, "French")
        self.assertEqual(row.pages, 97)
        self.assertTrue(row.mirrors)  # external mirror links captured

    def test_refs_are_md5(self):
        import re

        for c in self.cands:
            self.assertRegex(c.ref, r"[a-f0-9]{32}")

    def test_parse_size(self):
        self.assertEqual(parse_size("781 kB"), 781 * 1024)
        self.assertEqual(parse_size("26 MB"), 26 * 1024**2)
        self.assertEqual(parse_size("1.5 GB"), int(1.5 * 1024**3))
        self.assertEqual(parse_size("weird"), 0)


class GutenbergParseTests(unittest.TestCase):
    def test_parses_results(self):
        cands = parse_search(load("gut_search.html"))
        self.assertGreaterEqual(len(cands), 3)
        for c in cands:
            self.assertRegex(c.ref, r"\d+")
            self.assertTrue(c.title)


class OpenLibraryParseTests(unittest.TestCase):
    def test_parses_docs(self):
        data = json.loads(load("ol_search.json"))
        cands = parse_docs(data)
        self.assertGreaterEqual(len(cands), 1)
        for c in cands:
            self.assertTrue(c.ref.startswith("/works/"))
            self.assertTrue(c.mirrors[0].startswith("https://archive.org/metadata/"))
            self.assertTrue(c.title)


class StandardEbooksParseTests(unittest.TestCase):
    def test_link_regex(self):
        html = load("se_catalog.html")
        links = {m.group(1) for m in LINK_RE.finditer(html)}
        self.assertTrue(any("/ebooks/" in l and l.count("/") >= 2 for l in links))


class VerifyTests(unittest.TestCase):
    def _epub(self, mimetype: str = "application/epub+zip") -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mimetype", mimetype)
            z.writestr("content.opf", "<package xmlns='http://www.idpf.org/2007/opf'/>")
            z.writestr("META-INF/container.xml", "<container/>")
        data = buf.getvalue()
        return data + b"\x00" * max(0, 2048 - len(data))

    def test_valid_epub(self):
        ok, reason, ext = verify(self._epub())
        self.assertTrue(ok, reason)
        self.assertEqual(ext, "epub")

    def test_epub_wrong_mimetype(self):
        ok, reason, ext = verify(self._epub("text/html"))
        self.assertFalse(ok)

    def test_corrupt_zip(self):
        data = b"PK\x03\x04" + b"\x00" * 2048
        ok, reason, ext = verify(data)
        self.assertFalse(ok)

    def test_valid_pdf(self):
        data = b"%PDF-1.4\n" + b"\x00" * 2048
        ok, reason, ext = verify(data)
        self.assertTrue(ok, reason)
        self.assertEqual(ext, "pdf")

    def test_html_page_rejected(self):
        data = b"<!DOCTYPE html><html><body><script>anti-bot</script></body></html>" + b"x" * 2048
        ok, reason, ext = verify(data)
        self.assertFalse(ok)
        self.assertIn("HTML", reason)

    def test_too_small(self):
        ok, reason, ext = verify(b"%PDF-1.4 short")
        self.assertFalse(ok)


class MatchTests(unittest.TestCase):
    def _cands(self):
        return [
            Candidate("libgen", "a", title="Le cycle de Dune 1",
                      authors=["Frank Herbert - Le cycle de Dune - 1"], year="1965", language="French"),
            Candidate("libgen", "b", title="Dune The Official Comic Book",
                      authors=["Macchio, Ralph (sc.)", "Sienkiewicz, Bill (des.)"], year="1984", language="English"),
        ]

    def test_author_disambiguates(self):
        best, verdict, _ = pick_best(self._cands(), "Dune", author="Frank Herbert")
        self.assertEqual(verdict, "ok")
        self.assertEqual(best.ref, "a")

    def test_identical_twin_is_ambiguous(self):
        cands = [
            Candidate("libgen", "a", title="Dune", authors=["Frank Herbert"], year="1965"),
            Candidate("libgen", "b", title="Dune", authors=["Frank Herbert"], year="1965"),
        ]
        best, verdict, _ = pick_best(cands, "Dune", author="Frank Herbert")
        self.assertEqual(verdict, "ambiguous")
        self.assertIsNone(best)

    def test_no_match(self):
        best, verdict, _ = pick_best(self._cands(), "completely unknown title zzz")
        self.assertEqual(verdict, "none")

    def test_explicit_author_disqualifies_wrong_book(self):
        cands = [
            Candidate("libgen", "a", title="Holo Sapiens 1", authors=["Crawford, Dean"],
                      year="2013", language="English"),
        ]
        best, verdict, _ = pick_best(cands, "Sapiens", author="Yuval Noah Harari")
        self.assertEqual(verdict, "none")
        self.assertIsNone(best)

    def test_explicit_author_selects_right_book(self):
        cands = [
            Candidate("libgen", "junk", title="Yuval Noah Harari - Downloaden Sapiens PDF",
                      authors=["Yuval Noah Harari"], language="English"),
            Candidate("libgen", "wrong", title="Holo Sapiens 1", authors=["Crawford, Dean"],
                      year="2013", language="English"),
            Candidate("libgen", "right", title="Sapiens: A Brief History of Humankind",
                      authors=["Harari, Yuval Noah"], year="2015", language="English"),
        ]
        best, verdict, _ = pick_best(cands, "Sapiens", author="Yuval Noah Harari")
        self.assertEqual(verdict, "ok")
        self.assertEqual(best.ref, "right")


class RegistryTests(unittest.TestCase):
    def test_default_order(self):
        reg = default_registry()
        self.assertEqual([s.name for s in reg.sources],
                         ["libgen", "openlibrary", "gutenberg", "standardebooks", "annasarchive"])

    def test_infer_source(self):
        self.assertEqual(infer_source("e7c75dc2964ce80c19cb69140aae8614"), "libgen")
        self.assertEqual(infer_source("/works/OL893414W"), "openlibrary")
        self.assertEqual(infer_source("11"), "gutenberg")
        self.assertEqual(infer_source("author/title"), "standardebooks")
        with self.assertRaises(UsageError):
            infer_source("???")

    def test_search_falls_through_on_source_failure(self):
        class Stub(Source):
            def __init__(self, name, cands=None, exc=None):
                super().__init__()
                self.name = name
                self._cands = cands or []
                self._exc = exc

            def search(self, query, author=None, year=None, limit=20):
                if self._exc:
                    raise self._exc
                return self._cands

            def download(self, candidate, fmt=None):
                raise SourceFailedError("stub")

        ok_cand = Candidate("second", "ref-2", title="Some Book", authors=["X"])
        reg = Registry([Stub("first", exc=SourceFailedError("first is down")), Stub("second", cands=[ok_cand])])
        engine = Engine(reg)
        cands, failures = engine.search("some book")
        self.assertEqual([c.ref for c in cands], ["ref-2"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["source"], "first")


class EngineRulesTests(unittest.TestCase):
    def test_choose_format_prefers_pdf(self):
        self.assertEqual(choose_format({"epub": 2, "pdf": 1}), "pdf")
        self.assertEqual(choose_format({"epub": 2}), "epub")
        self.assertIsNone(choose_format({}))
        with self.assertRaises(UsageError):
            choose_format({"epub": 1}, requested="pdf")

    def test_target_path_sanitizes(self):
        p = target_path(Path("out"), Candidate("s", "r", title="Bad:Title/?*<>", authors=["O'Neil, A."]), "epub")
        self.assertNotIn(":", p.name)
        self.assertNotIn("?", p.name)
        self.assertTrue(p.name.endswith(".epub"))
        self.assertTrue(p.name.startswith("O'Neil"))

    def test_sanitize_name_fallback(self):
        self.assertEqual(sanitize_name("???"), "book")


class ConfigTests(unittest.TestCase):
    def _write(self, tmp):
        p = Path(tmp) / "config.yaml"
        p.write_text("out_dir: /tmp/books\ndisabled_sources:\n  - gutenberg\n", encoding="utf-8")
        return p

    def test_loads_yaml_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.dict(os.environ, {"BOOKFETCH_CONFIG": str(self._write(tmp))}):
                cfg = config.load_config()
        self.assertEqual(cfg.get("out_dir"), "/tmp/books")
        self.assertEqual(cfg.get("disabled_sources"), ["gutenberg"])

    def test_missing_config_is_empty(self):
        with unittest.mock.patch.dict(os.environ, {"BOOKFETCH_CONFIG": "/nonexistent/bookfetch/config.yaml"}):
            self.assertEqual(config.load_config(), {})

    def test_corrupt_config_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.yaml"
            p.write_text("out_dir: [unclosed", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"BOOKFETCH_CONFIG": str(p)}):
                self.assertEqual(config.load_config(), {})

    def test_registry_honors_disabled_sources(self):
        from cli_anything.bookfetch.core.registry import default_registry

        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.dict(os.environ, {"BOOKFETCH_CONFIG": str(self._write(tmp))}):
                reg = default_registry()
        self.assertNotIn("gutenberg", [s.name for s in reg.sources])
        self.assertIn("libgen", [s.name for s in reg.sources])


class RedactionTests(unittest.TestCase):
    def test_redacts_key_token(self):
        from cli_anything.bookfetch.core.http import redact_secrets

        out = redact_secrets("https://libgen.li/get.php?md5=abc123&key=VXJZ89CXWMTUFYNN")
        self.assertNotIn("VXJZ89CXWMTUFYNN", out)
        self.assertIn("key=<redacted>", out)

    def test_short_keys_pass_through(self):
        from cli_anything.bookfetch.core.http import redact_secrets

        self.assertEqual(redact_secrets("key=abc"), "key=abc")


class SessionTests(unittest.TestCase):
    def make_session(self, tmp):
        return Session("bookfetch", path=Path(tmp) / "session.json")

    def test_record_undo_redo(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(tmp)
            session.record({"op": "get", "path": "/x.pdf"})
            self.assertEqual(len(session.history()), 1)
            self.assertEqual(session.undo()["op"], "get")
            self.assertEqual(len(session.history()), 0)
            self.assertEqual(session.redo()["op"], "get")
            self.assertEqual(len(session.history()), 1)

    def test_undo_on_empty_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.make_session(tmp).undo())

    def test_state_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            Session("bookfetch", path=path).record({"op": "get"})
            self.assertEqual(len(Session("bookfetch", path=path).history()), 1)


if __name__ == "__main__":
    unittest.main()
