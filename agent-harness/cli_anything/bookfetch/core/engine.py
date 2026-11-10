"""The engine: search -> score -> pick -> download -> verify -> store.

Both frontends (MCP server, CLI) call into this; nothing else decides behavior.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .config import load_config
from .errors import (
    AllSourcesFailedError,
    AmbiguousMatchError,
    NoMatchError,
    SourceFailedError,
    UsageError,
    VerificationFailedError,
)
from .match import AMBIGUITY_GAP, pick_best
from .models import Candidate, DownloadResult, Plan
from .registry import Registry, default_registry, infer_source
from .verify import verify

FORMAT_PRIORITY = ["pdf", "epub"]


def default_out_dir() -> Path:
    cfg = load_config()
    return Path(os.environ.get("BOOKFETCH_OUT") or cfg.get("out_dir") or str(Path.home() / "Books"))


def choose_format(formats: dict, requested: str | None = None) -> str | None:
    """Return the ext to fetch, or None for 'source decides' (empty formats)."""
    if not formats:
        return None
    if requested:
        if requested in formats:
            return requested
        raise UsageError(f"this book has no .{requested} (available: {', '.join(sorted(formats))})")
    for ext in FORMAT_PRIORITY:
        if ext in formats:
            return ext
    return max(formats, key=lambda e: formats.get(e) or 0)


def sanitize_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name or "book")
    name = re.sub(r"\s+", " ", name).strip()
    return name[:150] or "book"


def target_path(out_dir: Path, cand: Candidate, ext: str) -> Path:
    author = cand.authors[0] if cand.authors else ""
    if author:
        if "," in author:
            author_part = author.split(",")[0].strip()  # "Last, First" -> Last
        else:
            author_part = author.split()[0]
    else:
        author_part = ""
    base = " - ".join(p for p in (author_part, cand.title or cand.ref) if p)
    if cand.year:
        base += f" ({cand.year})"
    return out_dir / f"{sanitize_name(base)}.{ext}"


class Engine:
    def __init__(self, registry: Registry | None = None, out_dir: str | Path | None = None, session=None):
        self.registry = registry or default_registry()
        self.out_dir = Path(out_dir) if out_dir else default_out_dir()
        self.session = session

    # ---------------- search ----------------

    def search(self, query: str, author: str | None = None, year: str | None = None, limit: int = 10):
        """Return (candidates, failures). Candidates come from the first source that matches."""
        failures = []
        for src in self.registry.sources:
            if src.state == "down":
                failures.append({"source": src.name, "error": f"skipped (down: {src.note})"})
                continue
            try:
                cands = src.search(query, author=author, year=year, limit=max(limit, 20))
            except SourceFailedError as e:
                failures.append({"source": src.name, "error": str(e)})
                continue
            if cands:
                return cands[:limit], failures
        return [], failures

    # ---------------- get ----------------

    def plan_get(
        self,
        query: str | None = None,
        ref: str | None = None,
        source: str | None = None,
        author: str | None = None,
        year: str | None = None,
        fmt: str | None = None,
    ) -> Plan:
        cand, src_name = self._resolve(query, ref, source, author, year)
        ext = choose_format(cand.formats, fmt)
        src = self.registry.by_name(src_name)
        chain = list(getattr(src, "domains", [src_name]))
        return Plan(
            source=src_name,
            ref=cand.ref,
            title=cand.title,
            authors=cand.authors,
            format=ext or "auto",
            target=str(target_path(self.out_dir, cand, ext or "???")),
            mirror_chain=chain,
        )

    def _resolve(self, query, ref, source, author, year):
        """Return (candidate, source_name) for a query or an explicit ref."""
        if ref:
            src_name = infer_source(ref, source)
            src = self.registry.by_name(src_name)
            # try to enrich with metadata from the source's own search
            try:
                cands = src.search(ref if src_name in ("libgen",) else (query or ref),
                                   author=author, year=year, limit=10)
                for c in cands:
                    if c.ref == ref:
                        return c, src_name
            except (SourceFailedError, Exception):  # noqa: BLE001 - enrichment is optional
                pass
            return Candidate(source=src_name, ref=ref, title=ref), src_name
        if not query:
            raise UsageError("pass a query or --id")
        cands, failures = self.search(query, author=author, year=year, limit=20)
        if not cands:
            raise NoMatchError(f"no candidates for {query!r} from any source", failures)
        best, verdict, scored = pick_best(cands, query, author, year)
        if best is None and verdict == "none" and any(s >= 0 for s, _ in scored):
            raise NoMatchError(
                f"candidates exist but none match author {author!r}; retry without --author",
                failures,
            )
        if best is None:
            top = [c for _, c in sorted(scored, key=lambda p: -p[0])[:10]]
            raise AmbiguousMatchError(
                f"ambiguous match for {query!r}; pick one with 'get --id <ref>'", top
            )
        return best, best.source

    def get(
        self,
        query: str | None = None,
        ref: str | None = None,
        source: str | None = None,
        author: str | None = None,
        year: str | None = None,
        fmt: str | None = None,
        dry_run: bool = False,
        out_dir: str | Path | None = None,
    ) -> DownloadResult:
        if out_dir:
            self.out_dir = Path(out_dir)
        cand, src_name = self._resolve(query, ref, source, author, year)
        if dry_run:
            p = self.plan_get(query, ref, source, author, year, fmt)
            return DownloadResult(
                path=p.target, source=p.source, ref=p.ref, format=p.format, size=0,
                title=p.title, authors=p.authors, year=cand.year,
                verified=False, warnings=["dry-run: nothing downloaded"],
            )
        ext = choose_format(cand.formats, fmt)
        ordered = [self.registry.by_name(src_name)] + [
            s for s in self.registry.sources if s.name != src_name
        ]
        attempts = []
        for s in ordered:
            c = cand if s.name == src_name else self._confident_match(s, query, author, year)
            if c is None:
                attempts.append({"source": s.name, "error": "no confident re-match for fallback"})
                continue
            try:
                data, real_ext = s.download(c, ext)
            except SourceFailedError as e:
                attempts.append({"source": s.name, "error": str(e)})
                continue
            ok, reason, sniffed = verify(data, real_ext)
            if not ok:
                attempts.append({"source": s.name, "error": f"verification failed: {reason}"})
                continue
            final_ext = sniffed or real_ext or "bin"
            path = target_path(self.out_dir, c, final_ext)
            skipped = path.exists()
            if not skipped:
                self._write_atomic(path, data)
            if self.session is not None:
                self.session.record(
                    {
                        "op": "get",
                        "source": s.name,
                        "ref": c.ref,
                        "title": c.title,
                        "path": str(path),
                        "size": path.stat().st_size,
                        "skipped": skipped,
                    }
                )
            return DownloadResult(
                path=str(path),
                source=s.name,
                ref=c.ref,
                format=final_ext,
                size=path.stat().st_size,
                title=c.title,
                authors=c.authors,
                year=c.year,
                verified=True,
                skipped=skipped,
                warnings=["already existed, skipped re-download"] if skipped else [],
            )
        raise AllSourcesFailedError(
            f"all sources failed for {query or ref!r}", attempts
        )

    def _confident_match(self, src, query, author, year):
        """Re-search a fallback source and accept its top pick only when confident."""
        if not query:
            return None
        try:
            cands = src.search(query, author=author, year=year, limit=10)
        except SourceFailedError:
            return None
        best, verdict, _ = pick_best(cands, query, author, year, min_gap=AMBIGUITY_GAP)
        return best if verdict == "ok" else None

    # ---------------- info ----------------

    def book_info(self, ref: str, source: str | None = None, query: str | None = None) -> Candidate:
        src_name = infer_source(ref, source)
        src = self.registry.by_name(src_name)
        try:
            cands = src.search(ref if src_name == "libgen" else (query or ref), limit=20)
            for c in cands:
                if c.ref == ref:
                    return c
            if cands:
                return cands[0]
        except SourceFailedError:
            pass
        if src_name == "libgen" and hasattr(src, "fetch_meta"):
            meta = src.fetch_meta(ref)
            if meta is not None:
                return meta
        raise NoMatchError(f"ref {ref!r} not found on {src_name}")

    @staticmethod
    def _write_atomic(path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
