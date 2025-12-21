#!/usr/bin/env python3
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from md2latex import ensure_ascii as md_ensure_ascii, reject_raw_html as md_reject_raw_html


MICROCODE_DELIM = " | "

RE_CABLE_ID = re.compile(r"^MSPM-CBL-\d{4}-\d{2}-\d{2}-\d{3}$")
RE_UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")
RE_SHA256_UPPER = re.compile(r"^[0-9A-F]{64}$")
RE_SIG = re.compile(r"^[A-Z0-9]+-[A-Z0-9-]+$")

RE_FRONTMATTER_KV = re.compile(r"^([a-z_]+):[ \t]*(.+?)[ \t]*$")

RE_SECTION_HEADING = re.compile(r"^##[ \t]+([A-Z]+)[ \t]*$")
RE_BULLET = re.compile(r"^-[ \t]+(.+)$")

REQUIRED_SECTIONS = ["SUMMARY", "FACTS", "ASSESSMENT", "OUTLOOK"]


class LintError(RuntimeError):
    pass


@dataclass(frozen=True)
class CableSource:
    cable_id: str
    utc: str
    title: str
    sig: str
    sections: dict[str, list[str]]


def _fail(message: str) -> None:
    raise LintError(message)


def ensure_ascii(text: str, *, context: str) -> None:
    try:
        md_ensure_ascii(text, context=context)
    except Exception as exc:
        _fail(str(exc))


def lint_microcode_line(microcode: str) -> None:
    if "\n" in microcode or "\r" in microcode:
        _fail("microcode: must be a single line (no newlines)")

    ensure_ascii(microcode, context="microcode")

    parts = microcode.split(MICROCODE_DELIM)
    if len(parts) != 4:
        _fail(f"microcode: expected 4 fields separated by {MICROCODE_DELIM!r}")

    cable_id = parts[0]
    if not RE_CABLE_ID.fullmatch(cable_id):
        _fail("microcode: invalid cable id")

    if not parts[1].startswith("UTC:"):
        _fail("microcode: missing UTC field")
    utc = parts[1][4:]
    if not RE_UTC_ZULU.fullmatch(utc):
        _fail("microcode: UTC must be Zulu (YYYY-MM-DDTHH:MMZ)")

    if not parts[2].startswith("SHA256:"):
        _fail("microcode: missing SHA256 field")
    sha256 = parts[2][7:]
    if not RE_SHA256_UPPER.fullmatch(sha256):
        if re.search(r"[a-f]", sha256):
            _fail("microcode: lowercase hex present in SHA256")
        _fail("microcode: SHA256 must be 64 uppercase hex chars")

    if not parts[3].startswith("SIG:"):
        _fail("microcode: missing SIG field")
    sig = parts[3][4:]
    if not RE_SIG.fullmatch(sig):
        _fail("microcode: SIG must match <ALG>-<KEYID> with uppercase ASCII")


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    if not lines or lines[0].strip() != "---":
        _fail("frontmatter: missing opening --- line")

    data: dict[str, str] = {}
    i = 1
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if line.strip() == "---":
            return data, lines[i + 1 :]
        if not line.strip():
            i += 1
            continue
        match = RE_FRONTMATTER_KV.fullmatch(line)
        if not match:
            _fail(f"frontmatter: invalid line: {line!r}")
        key, value = match.group(1), match.group(2)
        data[key] = value
        i += 1

    _fail("frontmatter: missing closing --- line")


def parse_and_lint_cable_markdown(markdown: str) -> CableSource:
    ensure_ascii(markdown, context="markdown")

    if "```" in markdown:
        _fail("markdown: fenced code blocks are not allowed")

    try:
        md_reject_raw_html(markdown, context="markdown")
    except Exception as exc:
        _fail(str(exc))

    lines = markdown.splitlines(keepends=True)
    frontmatter, body_lines = _split_frontmatter(lines)

    for required_key in ("cable_id", "utc", "title", "sig"):
        if required_key not in frontmatter:
            _fail(f"frontmatter: missing {required_key}")
        ensure_ascii(frontmatter[required_key], context=f"frontmatter.{required_key}")

    cable_id = frontmatter["cable_id"]
    utc = frontmatter["utc"]
    title = frontmatter["title"]
    sig = frontmatter["sig"]

    if not RE_CABLE_ID.fullmatch(cable_id):
        _fail("frontmatter.cable_id: must match MSPM-CBL-YYYY-MM-DD-XXX")
    if not RE_UTC_ZULU.fullmatch(utc):
        _fail("frontmatter.utc: must be Zulu (YYYY-MM-DDTHH:MMZ)")
    if not RE_SIG.fullmatch(sig):
        _fail("frontmatter.sig: must match <ALG>-<KEYID> with uppercase ASCII")

    sections: dict[str, list[str]] = {}
    current: str | None = None

    for raw_line in body_lines:
        line = raw_line.rstrip("\n")
        heading_match = RE_SECTION_HEADING.fullmatch(line)
        if heading_match:
            current = heading_match.group(1)
            if current in sections:
                _fail(f"markdown: duplicate section heading {current}")
            sections[current] = []
            continue

        if current is None:
            if line.strip():
                _fail("markdown: content found before first required section heading")
            continue

        sections[current].append(line)

    for name in REQUIRED_SECTIONS:
        if name not in sections:
            _fail(f"markdown: missing required section {name}")

    actual_order = [s for s in sections.keys() if s in REQUIRED_SECTIONS]
    if actual_order != REQUIRED_SECTIONS:
        _fail(f"markdown: required sections must be in order: {', '.join(REQUIRED_SECTIONS)}")

    summary_text = _normalize_section_to_text(sections["SUMMARY"])
    if not summary_text.strip():
        _fail("markdown: SUMMARY must not be empty")

    return CableSource(cable_id=cable_id, utc=utc, title=title, sig=sig, sections=sections)


def _normalize_section_to_text(lines: list[str]) -> str:
    chunks: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            chunks.append("")
            continue
        bullet_match = RE_BULLET.fullmatch(stripped)
        if bullet_match:
            chunks.append(bullet_match.group(1).strip())
        else:
            chunks.append(stripped)
    return "\n".join(chunks).strip()


def lint_path(path: Path) -> None:
    if path.is_dir():
        for file_path in sorted(path.rglob("*.md")):
            lint_path(file_path)
        return

    markdown = path.read_text(encoding="utf-8")
    parse_and_lint_cable_markdown(markdown)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Lint MSPMetro cable Markdown and MicroCode.")
    parser.add_argument("path", nargs="?", help="Cable Markdown file or a directory to scan.")
    parser.add_argument("--microcode", help="Lint a MicroCode line directly.")
    args = parser.parse_args(argv)

    try:
        if args.microcode is not None:
            lint_microcode_line(args.microcode)
        if args.path:
            lint_path(Path(args.path))
    except LintError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
