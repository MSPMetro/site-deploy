#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


class HashError(RuntimeError):
    pass


RE_SHA256 = re.compile(r"^[0-9A-F]{64}$")
RE_UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")
RE_ID = re.compile(r"^MSPM-CBL-\d{4}-\d{2}-\d{2}-\d{3}$")


@dataclass(frozen=True)
class PayloadHeader:
    cable_id: str
    utc: str
    issuer: str


def _fail(msg: str) -> None:
    raise HashError(msg)


def _sha256_upper(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _require_ascii_bytes(data: bytes, *, context: str) -> None:
    for i, b in enumerate(data):
        if b > 0x7F:
            _fail(f"{context}: non-ASCII byte at index {i}: 0x{b:02X}")


def _validate_payload_bytes(payload: bytes) -> None:
    _require_ascii_bytes(payload, context="payload.txt")
    if b"\r" in payload:
        _fail("payload.txt: CR characters are not allowed (must use \\n)")
    if b"\t" in payload:
        _fail("payload.txt: tabs are not allowed")
    if b"  " in payload:
        _fail("payload.txt: multiple consecutive spaces are not allowed")


def _parse_payload_header(payload_text: str) -> PayloadHeader:
    lines = payload_text.split("\n")
    if len(lines) < 6:
        _fail("payload.txt: too short")
    if lines[0] != "MSPM CABLE":
        _fail("payload.txt: missing 'MSPM CABLE' header line")

    def get(prefix: str) -> str:
        for line in lines[1:10]:
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        _fail(f"payload.txt: missing header field {prefix.strip()}")

    cable_id = get("ID: ")
    utc = get("UTC: ")
    issuer = get("ISSUER: ")

    if not RE_ID.fullmatch(cable_id):
        _fail("payload.txt: invalid ID field")
    if not RE_UTC_ZULU.fullmatch(utc):
        _fail("payload.txt: invalid UTC field")
    if issuer != "MSPMetro Cables":
        _fail("payload.txt: ISSUER must be exactly 'MSPMetro Cables'")

    return PayloadHeader(cable_id=cable_id, utc=utc, issuer=issuer)


def _require_ascii_str(value: str, *, context: str) -> None:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise HashError(f"{context}: must be ASCII") from exc


def _write_text_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_hash_files(*, cable_dir: Path, title: str) -> dict[str, str]:
    payload_path = cable_dir / "payload.txt"
    pdf_path = cable_dir / "cable.pdf"

    if not payload_path.exists():
        _fail("missing payload.txt")
    if not pdf_path.exists():
        _fail("missing cable.pdf")

    payload_bytes = payload_path.read_bytes()
    _validate_payload_bytes(payload_bytes)
    payload_text = payload_bytes.decode("ascii")

    header = _parse_payload_header(payload_text)

    _require_ascii_str(title, context="title")
    if "\n" in title or "\r" in title or "\t" in title:
        _fail("title: must be single-line ASCII with no tabs")
    if "  " in title:
        _fail("title: must not contain multiple consecutive spaces")

    payload_sha256 = _sha256_upper(payload_bytes)
    pdf_sha256 = _sha256_upper(pdf_path.read_bytes())

    if not RE_SHA256.fullmatch(payload_sha256):
        _fail("internal: payload sha256 malformed")
    if not RE_SHA256.fullmatch(pdf_sha256):
        _fail("internal: pdf sha256 malformed")

    fp16 = payload_sha256[:16]

    meta = {
        "id": header.cable_id,
        "utc": header.utc,
        "title": title,
        "issuer": header.issuer,
        "payload_sha256": payload_sha256,
        "pdf_sha256": pdf_sha256,
        "fp16": fp16,
    }
    meta_bytes = (json.dumps(meta, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")

    _write_text_atomic((cable_dir / "payload.sha256"), (payload_sha256 + "\n").encode("ascii"))
    _write_text_atomic((cable_dir / "pdf.sha256"), (pdf_sha256 + "\n").encode("ascii"))
    _write_text_atomic((cable_dir / "meta.json"), meta_bytes)

    return {"payload_sha256": payload_sha256, "pdf_sha256": pdf_sha256, "fp16": fp16}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Compute deterministic hashes and meta.json for a cable directory.")
    ap.add_argument("--dir", required=True, help="Cable directory containing payload.txt and cable.pdf")
    ap.add_argument("--title", required=True, help="Cable title (ASCII, single line)")
    args = ap.parse_args(argv)

    try:
        cable_dir = Path(args.dir)
        if not cable_dir.exists() or not cable_dir.is_dir():
            _fail("dir must exist and be a directory")
        result = write_hash_files(cable_dir=cable_dir, title=args.title)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

