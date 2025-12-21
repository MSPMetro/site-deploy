#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


HEADER_OPEN_RE = re.compile(r"^([ \t]*)header\s*\{\s*$")
HEADER_LINE_RE = re.compile(r"^([ \t]*)([^\s]+)\s+")
HEADER_CSP_RE = re.compile(r'^([ \t]*)Content-Security-Policy\s+"(.*)"\s*$')


def _quote_csp_keywords(policy: str) -> str:
    # Browsers require single quotes around CSP keywords like 'self' and 'none'.
    # Keep this minimal and deterministic: only quote known keywords when unquoted.
    keywords = (
        "self",
        "none",
        "unsafe-inline",
        "unsafe-eval",
        "strict-dynamic",
        "report-sample",
        "unsafe-hashes",
        "wasm-unsafe-eval",
    )
    out = policy
    for kw in keywords:
        out = re.sub(rf"(?<!')\b{re.escape(kw)}\b(?!')", f"'{kw}'", out)
    return out


def ensure_headers(text: str, policy_value: str, served_by_value: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    changed = False

    in_header = False
    header_indent = ""
    saw_permissions = False
    saw_served_by = False

    out: list[str] = []
    for line in lines:
        if not in_header:
            m = HEADER_OPEN_RE.match(line.rstrip("\n"))
            if m:
                in_header = True
                header_indent = m.group(1)
                saw_permissions = False
                saw_served_by = False
            out.append(line)
            continue

        # Inside a header { } block.
        m = HEADER_LINE_RE.match(line.rstrip("\n"))
        if m:
            header_indent_line = m.group(1)
            header_name = m.group(2)
            if header_name == "Content-Security-Policy":
                m_csp = HEADER_CSP_RE.match(line.rstrip("\n"))
                if m_csp:
                    current = m_csp.group(2)
                    fixed = _quote_csp_keywords(current)
                    desired = f'{header_indent_line}Content-Security-Policy "{fixed}"\n'
                    if line != desired:
                        out.append(desired)
                        changed = True
                        continue
            if header_name == "Permissions-Policy":
                if saw_permissions:
                    changed = True
                    continue
                saw_permissions = True
            if header_name == "X-Served-By":
                if saw_served_by:
                    changed = True
                    continue
                saw_served_by = True
                desired = f'{header_indent_line}X-Served-By "{served_by_value}"\n'
                if line != desired:
                    out.append(desired)
                    changed = True
                    continue
            if header_name == "X-MSPMetro-Served-By":
                changed = True
                continue

        if line.startswith(f"{header_indent}}}"):
            if not saw_permissions:
                out.append(f'{header_indent}\tPermissions-Policy "{policy_value}"\n')
                changed = True
            if not saw_served_by:
                out.append(f'{header_indent}\tX-Served-By "{served_by_value}"\n')
                changed = True
            in_header = False
            header_indent = ""
            saw_permissions = False
            saw_served_by = False
            out.append(line)
            continue

        out.append(line)

    return "".join(out), changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensure Caddy security headers include Permissions-Policy.")
    ap.add_argument("--caddyfile", default="/etc/caddy/Caddyfile")
    ap.add_argument(
        "--policy",
        default="geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        help="Permissions-Policy value (without surrounding quotes).",
    )
    ap.add_argument(
        "--served-by",
        default="{system.hostname} / {host}",
        help="Value for X-Served-By header (without surrounding quotes).",
    )
    args = ap.parse_args()

    p = Path(args.caddyfile)
    text = p.read_text(encoding="utf-8")
    new_text, changed = ensure_headers(text, args.policy, args.served_by)
    if changed:
        p.write_text(new_text, encoding="utf-8")
        print("CHANGED")
    else:
        print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
