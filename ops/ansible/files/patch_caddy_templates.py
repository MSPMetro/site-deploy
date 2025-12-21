#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


TARGET_RE = re.compile(r"^([ \t]*)(file_server|reverse_proxy)\b")


def _count_braces(line: str) -> tuple[int, int]:
    # Caddyfiles in this repo do not embed braces in strings; keep this simple.
    opens = line.count("{")
    closes = line.count("}")
    return opens, closes


def _indent_more(base: str) -> str:
    if "\t" in base:
        return base + "\t"
    return base + "    "


def _block_has_templates(lines: list[str], start: int, end: int, indent: str) -> bool:
    needle = f"{indent}templates"
    for i in range(start, end):
        if lines[i].startswith(needle):
            return True
    return False


def ensure_templates(text: str, between_open: str, between_close: str, mime: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    changed = False
    block_stack: list[int] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        m = TARGET_RE.match(line.rstrip("\n"))
        if m and block_stack:
            indent = m.group(1)
            block_start = block_stack[-1]
            if not _block_has_templates(lines, block_start + 1, i, indent):
                indent2 = _indent_more(indent)
                snippet = [
                    f"{indent}templates {{\n",
                    f"{indent2}between {between_open} {between_close}\n",
                    f"{indent2}mime {mime}\n",
                    f"{indent}}}\n",
                ]
                lines[i:i] = snippet
                changed = True
                i += len(snippet)
                continue

        opens, closes = _count_braces(line)
        # Track nesting to identify the current enclosing block for targets.
        for _ in range(opens):
            block_stack.append(i)
        for _ in range(closes):
            if block_stack:
                block_stack.pop()

        i += 1

    return "".join(lines), changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensure Caddy templates handler is enabled for MSPMetro ([[ ... ]] delimiters).")
    ap.add_argument("--caddyfile", default="/etc/caddy/Caddyfile")
    ap.add_argument("--between-open", default="[[")
    ap.add_argument("--between-close", default="]]")
    ap.add_argument("--mime", default="text/html")
    args = ap.parse_args()

    p = Path(args.caddyfile)
    text = p.read_text(encoding="utf-8")
    new_text, changed = ensure_templates(text, args.between_open, args.between_close, args.mime)
    if changed:
        p.write_text(new_text, encoding="utf-8")
        print("CHANGED")
    else:
        print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
