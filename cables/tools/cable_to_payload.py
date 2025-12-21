#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

from lint_cable import LintError, REQUIRED_SECTIONS, parse_and_lint_cable_markdown


class PayloadError(RuntimeError):
    pass


RE_TAB = re.compile(r"\t")
RE_MULTI_SPACE = re.compile(r"[ ]{2,}")

RE_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
RE_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
RE_MD_CODE = re.compile(r"`([^`]+)`")
RE_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
RE_MD_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _fail(msg: str) -> None:
    raise PayloadError(msg)


def _ensure_no_tabs(text: str) -> None:
    if RE_TAB.search(text):
        _fail("tabs are not allowed")


def _strip_inline_markdown(text: str) -> str:
    text = RE_MD_IMAGE.sub(lambda m: f"{m.group(1)} ({m.group(2)})".strip(), text)
    text = RE_MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = RE_MD_CODE.sub(lambda m: m.group(1), text)
    text = RE_MD_BOLD.sub(lambda m: m.group(1), text)
    text = RE_MD_ITALIC.sub(lambda m: m.group(1), text)
    return text


def _normalize_spaces(text: str) -> str:
    if "\t" in text:
        _fail("tabs are not allowed")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ ]+", " ", text)
    return text.strip()


def _wrap(text: str, *, width: int, initial: str = "", subsequent: str = "") -> list[str]:
    wrapper = textwrap.TextWrapper(
        width=width,
        expand_tabs=False,
        replace_whitespace=False,
        drop_whitespace=True,
        break_long_words=False,
        break_on_hyphens=False,
        initial_indent=initial,
        subsequent_indent=subsequent,
    )
    return wrapper.wrap(text)


def _canonicalize_paragraph(text: str, *, width: int) -> list[str]:
    text = _strip_inline_markdown(text)
    text = _normalize_spaces(text)
    if not text:
        return []
    return _wrap(text, width=width)


def _canonicalize_bullet(text: str, *, width: int) -> list[str]:
    text = _strip_inline_markdown(text)
    text = _normalize_spaces(text)
    if not text:
        return []
    # Subsequent indent is a single ASCII space to satisfy "single spaces only".
    return _wrap(text, width=width, initial="- ", subsequent=" ")


def _parse_section_lines(lines: list[str]) -> list[tuple[str, str]]:
    """
    Returns a list of ("p", text) or ("b", text) blocks.
    """
    blocks: list[tuple[str, str]] = []
    paragraph_buf: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_buf
        if not paragraph_buf:
            return
        blocks.append(("p", " ".join(s.strip() for s in paragraph_buf).strip()))
        paragraph_buf = []

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_paragraph()
            continue
        if line.startswith("- "):
            flush_paragraph()
            blocks.append(("b", line[2:].strip()))
            continue
        paragraph_buf.append(line)

    flush_paragraph()
    return blocks


def markdown_to_payload(markdown: str, *, wrap_width: int = 72) -> str:
    _ensure_no_tabs(markdown)

    try:
        source = parse_and_lint_cable_markdown(markdown)
    except LintError as exc:
        raise PayloadError(str(exc)) from exc

    out_lines: list[str] = []
    out_lines.append("MSPM CABLE")
    out_lines.append(f"ID: {source.cable_id}")
    out_lines.append(f"UTC: {source.utc}")
    out_lines.append("ISSUER: MSPMetro Cables")
    out_lines.append("")

    for section in REQUIRED_SECTIONS:
        # The linter guarantees the headings are present; keep canonical output strict.
        if section.upper() != section:
            _fail("heading must be uppercase")
        out_lines.append(section)

        blocks = _parse_section_lines(source.sections[section])
        emitted_any = False
        for kind, text in blocks:
            if kind == "p":
                lines = _canonicalize_paragraph(text, width=wrap_width)
            elif kind == "b":
                lines = _canonicalize_bullet(text, width=wrap_width)
            else:
                _fail("unknown block kind")
            if lines:
                out_lines.extend(lines)
                emitted_any = True
        if not emitted_any:
            _fail(f"section {section} is empty")

        out_lines.append("")

    payload = "\n".join(out_lines).rstrip("\n") + "\n"
    if RE_MULTI_SPACE.search(payload):
        _fail("output contains multiple consecutive spaces")
    if "\t" in payload:
        _fail("output contains tabs")
    try:
        payload.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PayloadError("output must be ASCII") from exc
    return payload


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Convert Cable Markdown into canonical payload.txt (ASCII, wrapped).")
    ap.add_argument("input_md", help="Input Cable Markdown file.")
    ap.add_argument(
        "-o",
        "--out",
        dest="out_path",
        help="Output payload.txt path (default: stdout).",
    )
    args = ap.parse_args(argv)

    try:
        md_path = Path(args.input_md)
        markdown = md_path.read_text(encoding="utf-8")
        payload = markdown_to_payload(markdown)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.out_path:
        Path(args.out_path).write_text(payload, encoding="ascii", newline="\n")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

