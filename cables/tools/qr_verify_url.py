#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


RE_CABLE_ID = re.compile(r"^MSPM-CBL-\d{4}-\d{2}-\d{2}-\d{3}$")
RE_SHA256 = re.compile(r"^[0-9A-F]{64}$")


class QRError(RuntimeError):
    pass


def _fail(msg: str) -> None:
    raise QRError(msg)


def _ensure_ascii(text: str, *, context: str) -> None:
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise QRError(f"{context}: must be ASCII") from exc


def _normalize_inputs(cable_id: str, sha256: str) -> tuple[str, str]:
    _ensure_ascii(cable_id, context="cable_id")
    _ensure_ascii(sha256, context="sha256")

    if not RE_CABLE_ID.fullmatch(cable_id):
        _fail("cable_id must match MSPM-CBL-YYYY-MM-DD-XXX")

    sha256_upper = sha256.upper()
    if not RE_SHA256.fullmatch(sha256_upper):
        _fail("sha256 must be 64 hex chars")

    return cable_id, sha256_upper


def build_verification_url(cable_id: str, sha256: str) -> str:
    cable_id, sha256 = _normalize_inputs(cable_id, sha256)
    url = f"https://www.mspmetro.com/c/v/{cable_id}/{sha256}"
    _ensure_ascii(url, context="url")
    return url


def generate_qr(*, content: str, ec_level: str, out_path: Path, fmt: str) -> None:
    _ensure_ascii(content, context="url")
    if ec_level not in {"M", "Q"}:
        _fail("error correction level must be M or Q")
    if fmt not in {"png", "svg"}:
        _fail("format must be png or svg")

    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_Q
    except Exception as exc:  # pragma: no cover
        raise QRError("missing dependency: qrcode (run `make -C cables setup`)") from exc

    error_correction = ERROR_CORRECT_M if ec_level == "M" else ERROR_CORRECT_Q

    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=8,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "png":
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(out_path)
        return

    if fmt == "svg":
        from qrcode.image.svg import SvgImage

        img = qr.make_image(image_factory=SvgImage)
        img.save(out_path)
        return

    _fail("unreachable")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate a QR code for MSPMetro cable verification URL.")
    ap.add_argument("--cable-id", required=True, help="Cable ID (MSPM-CBL-YYYY-MM-DD-XXX)")
    ap.add_argument("--sha256", required=True, help="SHA-256 hex (64 chars; case-insensitive input)")
    ap.add_argument("--ec", choices=["M", "Q"], default="M", help="Error correction level (M or Q).")
    ap.add_argument("--format", choices=["png", "svg"], default="png", help="Output format.")
    ap.add_argument("--out", required=True, help="Output path (.png or .svg).")
    args = ap.parse_args(argv)

    try:
        url = build_verification_url(args.cable_id, args.sha256)
        out_path = Path(args.out)
        generate_qr(content=url, ec_level=args.ec, out_path=out_path, fmt=args.format)
    except QRError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

