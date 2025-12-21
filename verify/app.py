from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from starlette.status import HTTP_404_NOT_FOUND


APP_TITLE: Final[str] = "MSPMetro Cable Verification"
BASE_DIR: Final[Path] = Path("/var/www/mspmetro/cables")

RE_CABLE_ID: Final[re.Pattern[str]] = re.compile(r"^MSPM-CBL-\d{4}-\d{2}-\d{2}-\d{3}$")
RE_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9A-F]{64}$")
RE_UTC_ZULU: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")


app = FastAPI(title=APP_TITLE)


class VerificationStatus:
    VERIFIED: Final[str] = "VERIFIED"
    MISMATCH: Final[str] = "MISMATCH"
    UNKNOWN: Final[str] = "UNKNOWN"


@dataclass(frozen=True)
class CableFiles:
    cable_dir: Path
    payload_txt: Path
    payload_sha256: Path
    meta_json: Path
    cable_pdf: Path


def _require_ascii_bytes(data: bytes, *, context: str) -> None:
    for i, b in enumerate(data):
        if b > 0x7F:
            raise ValueError(f"{context}: non-ASCII byte at index {i}: 0x{b:02X}")


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _safe_cable_id(cable_id: str) -> str:
    try:
        cable_id.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("cable_id must be ASCII") from exc
    if not RE_CABLE_ID.fullmatch(cable_id):
        raise ValueError("cable_id must match MSPM-CBL-YYYY-MM-DD-XXX")
    return cable_id


def _normalize_sha256_param(sha256: str) -> str:
    try:
        sha256.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("sha256 must be ASCII") from exc
    sha256_upper = sha256.upper()
    if not re.fullmatch(r"[0-9A-F]{64}", sha256_upper):
        raise ValueError("sha256 must be 64 hex chars")
    return sha256_upper


def _files_for(cable_id: str) -> CableFiles:
    cable_dir = (BASE_DIR / cable_id).resolve()
    base = BASE_DIR.resolve()
    if not cable_dir.is_relative_to(base):
        raise ValueError("invalid cable_id path")
    return CableFiles(
        cable_dir=cable_dir,
        payload_txt=cable_dir / "payload.txt",
        payload_sha256=cable_dir / "payload.sha256",
        meta_json=cable_dir / "meta.json",
        cable_pdf=cable_dir / "cable.pdf",
    )


def _read_expected_sha256(path: Path) -> str:
    data = path.read_bytes()
    _require_ascii_bytes(data, context="payload.sha256")
    text = data.decode("ascii")
    if not text.endswith("\n"):
        raise ValueError("payload.sha256 must end with newline")
    line = text[:-1]
    if not RE_SHA256.fullmatch(line):
        raise ValueError("payload.sha256 must be 64 uppercase hex chars + newline")
    return line


def _read_payload_text(path: Path) -> str:
    data = path.read_bytes()
    _require_ascii_bytes(data, context="payload.txt")
    return data.decode("ascii")


def _maybe_utc_from_meta(meta_json: Path) -> str | None:
    if not meta_json.exists():
        return None
    try:
        data = meta_json.read_bytes()
        _require_ascii_bytes(data, context="meta.json")
        meta = json.loads(data.decode("ascii"))
        if not isinstance(meta, dict):
            return None
        utc = meta.get("utc")
        if not isinstance(utc, str):
            return None
        if not RE_UTC_ZULU.fullmatch(utc):
            return None
        return utc
    except Exception:
        return None


def _render_page(
    *,
    status: str,
    cable_id: str,
    provided_sha256: str,
    expected_sha256: str | None,
    utc: str | None,
    payload: str | None,
    payload_download_href: str,
    pdf_download_href: str | None,
) -> HTMLResponse:
    expected_display = expected_sha256 if expected_sha256 is not None else "(unknown)"
    utc_display = utc if utc is not None else "(unknown)"
    payload_display = payload if payload is not None else "(payload unavailable)"

    body = "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "  <head>",
            "    <meta charset=\"utf-8\" />",
            f"    <title>{APP_TITLE}</title>",
            "  </head>",
            "  <body>",
            f"    <h1>Status: {_escape_html(status)}</h1>",
            "    <div>",
            f"      <div>Cable ID: <code>{_escape_html(cable_id)}</code></div>",
            f"      <div>Expected: <code>{_escape_html(expected_display)}</code></div>",
            f"      <div>Provided: <code>{_escape_html(provided_sha256)}</code></div>",
            f"      <div>UTC: <code>{_escape_html(utc_display)}</code></div>",
            "    </div>",
            "    <div>",
            f"      <div><a href=\"{_escape_html(payload_download_href)}\">Download payload.txt</a></div>",
            *(
                [f"      <div><a href=\"{_escape_html(pdf_download_href)}\">Download cable.pdf</a></div>"]
                if pdf_download_href
                else []
            ),
            "    </div>",
            "    <h2>payload.txt</h2>",
            f"    <pre>{_escape_html(payload_display)}</pre>",
            "  </body>",
            "</html>",
            "",
        ]
    )
    return HTMLResponse(content=body)


@app.get("/c/v/{cable_id}/{sha256}", response_class=HTMLResponse)
def verify_cable(cable_id: str, sha256: str, request: Request) -> HTMLResponse:
    try:
        cable_id = _safe_cable_id(cable_id)
        provided_sha256 = _normalize_sha256_param(sha256)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid parameters")

    files = _files_for(cable_id)

    payload_href = str(request.url_for("download_payload", cable_id=cable_id, sha256=provided_sha256))
    pdf_href = (
        str(request.url_for("download_pdf", cable_id=cable_id, sha256=provided_sha256))
        if files.cable_pdf.exists()
        else None
    )

    if not files.cable_dir.exists():
        return _render_page(
            status=VerificationStatus.UNKNOWN,
            cable_id=cable_id,
            provided_sha256=provided_sha256,
            expected_sha256=None,
            utc=None,
            payload=None,
            payload_download_href=payload_href,
            pdf_download_href=pdf_href,
        )

    if not files.payload_sha256.exists():
        return _render_page(
            status=VerificationStatus.UNKNOWN,
            cable_id=cable_id,
            provided_sha256=provided_sha256,
            expected_sha256=None,
            utc=_maybe_utc_from_meta(files.meta_json),
            payload=None,
            payload_download_href=payload_href,
            pdf_download_href=pdf_href,
        )

    try:
        expected_sha256 = _read_expected_sha256(files.payload_sha256)
    except Exception:
        return _render_page(
            status=VerificationStatus.UNKNOWN,
            cable_id=cable_id,
            provided_sha256=provided_sha256,
            expected_sha256=None,
            utc=_maybe_utc_from_meta(files.meta_json),
            payload=None,
            payload_download_href=payload_href,
            pdf_download_href=pdf_href,
        )

    payload_text: str | None = None
    if files.payload_txt.exists():
        try:
            payload_text = _read_payload_text(files.payload_txt)
        except Exception:
            payload_text = None

    status = VerificationStatus.VERIFIED if provided_sha256 == expected_sha256 else VerificationStatus.MISMATCH
    utc = _maybe_utc_from_meta(files.meta_json)

    return _render_page(
        status=status,
        cable_id=cable_id,
        provided_sha256=provided_sha256,
        expected_sha256=expected_sha256,
        utc=utc,
        payload=payload_text,
        payload_download_href=payload_href,
        pdf_download_href=pdf_href,
    )


@app.get("/c/v/{cable_id}/{sha256}/payload.txt")
def download_payload(cable_id: str, sha256: str) -> FileResponse:
    try:
        cable_id = _safe_cable_id(cable_id)
        _normalize_sha256_param(sha256)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid parameters")

    files = _files_for(cable_id)
    if not files.payload_txt.exists():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="not found")
    return FileResponse(path=str(files.payload_txt), media_type="text/plain; charset=us-ascii", filename="payload.txt")


@app.get("/c/v/{cable_id}/{sha256}/cable.pdf")
def download_pdf(cable_id: str, sha256: str) -> FileResponse:
    try:
        cable_id = _safe_cable_id(cable_id)
        _normalize_sha256_param(sha256)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid parameters")

    files = _files_for(cable_id)
    if not files.cable_pdf.exists():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="not found")
    return FileResponse(path=str(files.cable_pdf), media_type="application/pdf", filename="cable.pdf")
