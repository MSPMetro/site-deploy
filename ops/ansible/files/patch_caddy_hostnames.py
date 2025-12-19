#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def normalize_hostname(h: str) -> str:
    h = h.strip()
    if not h:
        raise ValueError("empty hostname")
    # Normalize Caddy labels: no trailing dot.
    return h[:-1] if h.endswith(".") else h


def find_site_line(lines: list[str], primary: str) -> int:
    primary = normalize_hostname(primary)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.endswith("{"):
            continue
        # Ignore comments.
        if stripped.startswith("#"):
            continue
        # Match primary in the comma-separated label list before '{'.
        left = stripped[: -len("{")].strip()
        labels = [s.strip() for s in left.split(",") if s.strip()]
        if primary in labels:
            return i
    raise SystemExit(f"site block not found for primary label: {primary}")


def ensure_hostnames(line: str, add: list[str]) -> str:
    stripped = line.strip()
    if not stripped.endswith("{"):
        return line
    prefix_ws = line[: len(line) - len(line.lstrip(" \t"))]
    left = stripped[: -len("{")].strip()
    labels = [s.strip() for s in left.split(",") if s.strip()]

    want = []
    seen = set()
    for h in labels + [normalize_hostname(a) for a in add]:
        if h not in seen:
            seen.add(h)
            want.append(h)

    return f"{prefix_ws}{', '.join(want)} {{\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caddyfile", default="/etc/caddy/Caddyfile")
    ap.add_argument("--site", required=True, help="existing primary site label, e.g. edge.eur.mspmetro.com")
    ap.add_argument("--add", action="append", default=[], help="hostname to add to that site block (repeatable)")
    args = ap.parse_args()

    if not args.add:
        return 0

    p = Path(args.caddyfile)
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    idx = find_site_line(lines, args.site)
    new_line = ensure_hostnames(lines[idx], args.add)
    if new_line != lines[idx]:
        lines[idx] = new_line
        p.write_text("".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

