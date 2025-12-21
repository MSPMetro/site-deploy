#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path("/var/www/mspmetro/cables")


def sha256_upper(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def main() -> int:
    cable_id = "MSPM-CBL-2025-12-20-001"
    utc = "2025-12-20T14:30Z"

    cable_dir = BASE / cable_id
    cable_dir.mkdir(parents=True, exist_ok=True)

    payload = (
        "CABLE_ID:MSPM-CBL-2025-12-20-001\n"
        "UTC:2025-12-20T14:30Z\n"
        "SUMMARY:Sample payload for local verification.\n"
        "FACTS:Example only.\n"
        "END\n"
    ).encode("ascii")

    expected = sha256_upper(payload)
    (cable_dir / "payload.txt").write_bytes(payload)
    (cable_dir / "payload.sha256").write_text(expected + "\n", encoding="ascii")
    (cable_dir / "meta.json").write_text(json.dumps({"utc": utc}, indent=2) + "\n", encoding="ascii")

    # Optional: copy a PDF if one exists from the cables build pipeline.
    repo_pdf = Path(__file__).resolve().parents[2] / "cables" / "build" / "pdf" / f"{cable_id}.pdf"
    if repo_pdf.exists():
        (cable_dir / "cable.pdf").write_bytes(repo_pdf.read_bytes())

    print(f"OK: created {cable_dir}")
    print(f"SHA256: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

