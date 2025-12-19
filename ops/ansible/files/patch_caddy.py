#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def find_block(text: str, site: str) -> tuple[int, int]:
    start_token = f"{site} {{"
    start = text.find(start_token)
    if start == -1:
        raise SystemExit(f"site block not found: {site}")

    i = start + len(start_token)
    depth = 1
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                # include trailing newline if present
                end = i + 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                return start, end
        i += 1

    raise SystemExit(f"unterminated block for site: {site}")


def ensure_handle_wrapped_static(block: str) -> str:
    if "\thandle {\n\t\ttry_files {path} {path}/ /index.html\n\t\tfile_server\n\t}\n" in block:
        return block

    # Only touch the common pattern this repo already uses.
    needle = "\ttry_files {path} {path}/ /index.html\n\tfile_server\n"
    if needle not in block:
        return block

    return block.replace(
        needle,
        "\thandle {\n\t\ttry_files {path} {path}/ /index.html\n\t\tfile_server\n\t}\n",
    )


def ensure_ssr_routes(
    block: str,
    ui_port: int,
    backend_port: int,
) -> str:
    if "handle_path /ui" in block and "path /api/v1/" in block:
        return block

    # Insert SSR routes immediately before the static handler (preferred), otherwise before try_files.
    insert_before = "\thandle {\n"
    idx = block.find(insert_before)
    if idx == -1:
        idx = block.find("\ttry_files {path} {path}/ /index.html\n")
    if idx == -1:
        return block

    snippet = (
        "\n"
        "\thandle_path /ui* {\n"
        f"\t\treverse_proxy 127.0.0.1:{ui_port}\n"
        "\t}\n"
        "\n"
        "\t@v1 {\n"
        "\t\tpath /api/v1/*\n"
        "\t}\n"
        "\thandle @v1 {\n"
        f"\t\treverse_proxy 127.0.0.1:{backend_port}\n"
        "\t}\n"
        "\n"
    )

    # Avoid double insert on partial state.
    if "handle_path /ui" not in block and "path /api/v1" not in block:
        return block[:idx] + snippet + block[idx:]

    # If one exists, only insert the missing part(s).
    insert = ""
    if "handle_path /ui" not in block:
        insert += (
            "\n"
            "\thandle_path /ui* {\n"
            f"\t\treverse_proxy 127.0.0.1:{ui_port}\n"
            "\t}\n"
            "\n"
        )
    if "path /api/v1" not in block:
        insert += (
            "\t@v1 {\n"
            "\t\tpath /api/v1/*\n"
            "\t}\n"
            "\thandle @v1 {\n"
            f"\t\treverse_proxy 127.0.0.1:{backend_port}\n"
            "\t}\n"
            "\n"
        )
    return block[:idx] + insert + block[idx:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caddyfile", default="/etc/caddy/Caddyfile")
    ap.add_argument("--site", required=True, help="site label, e.g. edge.eur.mspmetro.com")
    ap.add_argument("--ui-port", type=int, required=True)
    ap.add_argument("--backend-port", type=int, required=True)
    args = ap.parse_args()

    p = Path(args.caddyfile)
    text = p.read_text(encoding="utf-8")
    start, end = find_block(text, args.site)
    block = text[start:end]

    new_block = ensure_handle_wrapped_static(block)
    new_block = ensure_ssr_routes(new_block, ui_port=args.ui_port, backend_port=args.backend_port)

    if new_block != block:
        p.write_text(text[:start] + new_block + text[end:], encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

