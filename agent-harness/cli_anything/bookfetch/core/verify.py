"""Artifact verification: prove the bytes are a real document, not an anti-bot page."""

from __future__ import annotations

import io
import zipfile

MIN_SIZE = 1024
ZIP_FAMILY = {"epub", "docx", "docm", "xlsx", "zip", "cbz", "fb2"}


def verify(data: bytes, ext: str | None = None):
    """Return (ok, reason, detected_ext).

    If ext is None/empty the container is sniffed. A mismatch between the declared
    ext and the sniffed container still passes when the sniffed container is valid
    (naming follows the sniff).
    """
    if len(data) < MIN_SIZE:
        return False, f"file too small ({len(data)} bytes)", None

    if data[:5] == b"%PDF-" or b"%PDF-" in data[:1024]:
        return True, "pdf magic ok", "pdf"

    if data[:4] == b"PK\x03\x04":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            names = zf.namelist()
        except zipfile.BadZipFile:
            return False, "corrupt zip container", None
        if "mimetype" in names:
            try:
                mt = zf.read("mimetype").strip()
            except Exception:  # noqa: BLE001
                mt = b""
            if mt == b"application/epub+zip":
                if any(n.endswith(".opf") for n in names):
                    return True, "epub container ok", "epub"
                return False, "epub without opf", "epub"
            return False, f"zip with unexpected mimetype {mt!r}", None
        if any(n.endswith(".opf") for n in names):
            return True, "zip with opf (treated as epub)", "epub"
        if ext in ZIP_FAMILY or ext in (None, "", "unknown"):
            return True, "zip-family container ok", ext or "zip"
        return False, f"zip container but declared ext is .{ext}", ext

    if data[:7] == b"AT&Form":
        return True, "djvu magic ok", "djvu"

    head = data[:200]
    if b"<html" in head.lower() or b"<!doctype" in head.lower() or b"<script" in head.lower():
        return False, "received an HTML page (anti-bot interstitial), not a file", None
    if head[:1] == b"{":
        return False, "received JSON, not a file", None
    return False, "no known document magic found", None
