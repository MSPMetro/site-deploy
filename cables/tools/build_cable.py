#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from lint_cable import (
    CableSource,
    LintError,
    MICROCODE_DELIM,
    REQUIRED_SECTIONS,
    lint_microcode_line,
    parse_and_lint_cable_markdown,
)

from aztec import AztecError, render_aztec_png, write_aztec_png


CANONICAL_BASE_URL = "https://www.mspmetro.com/cables"

RE_SAFE_ASCII = re.compile(r"^[\x09\x0A\x0D\x20-\x7E]+$")


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuiltCable:
    cable_id: str
    utc: str
    title: str
    canonical_url: str
    sha256: str
    microcode: str
    summary: str
    html_path: str
    pdf_path: str
    aztec_payload: str


def _fail(message: str) -> None:
    raise BuildError(message)


def compute_sha256_hex_upper(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def canonical_url_for_id(cable_id: str) -> str:
    return f"{CANONICAL_BASE_URL}/{cable_id}"


def microcode_line(*, cable_id: str, utc: str, sha256: str, sig: str) -> str:
    line = f"{cable_id}{MICROCODE_DELIM}UTC:{utc}{MICROCODE_DELIM}SHA256:{sha256}{MICROCODE_DELIM}SIG:{sig}"
    lint_microcode_line(line)
    return line


def _canonical_text_for_hash(source: CableSource) -> str:
    pieces: list[str] = []
    pieces.append(f"CABLE_ID:{source.cable_id}")
    pieces.append(f"UTC:{source.utc}")
    pieces.append(f"TITLE:{source.title}")
    for name in REQUIRED_SECTIONS:
        pieces.append(f"SECTION:{name}")
        pieces.append(_normalized_text(source.sections[name]))
    pieces.append("END")
    text = "\n".join(pieces).strip() + "\n"
    if not RE_SAFE_ASCII.fullmatch(text):
        _fail("canonical text for hash is not strict ASCII")
    return text


def _normalized_text(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if stripped.startswith("- "):
            out.append(stripped[2:].strip())
        else:
            out.append(stripped)
    return "\n".join(out).strip()


def _extract_summary(source: CableSource) -> str:
    text = _normalized_text(source.sections["SUMMARY"])
    return text.splitlines()[0].strip() if text.strip() else ""


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _tex_breakable_hex(hex_text: str, *, group: int = 8) -> str:
    if not re.fullmatch(r"[0-9A-F]{64}", hex_text):
        _fail("cannot format non-hex SHA256 for TeX")
    pieces: list[str] = []
    for i in range(0, len(hex_text), group):
        chunk = hex_text[i : i + group]
        pieces.append(chunk)
        if i + group < len(hex_text):
            pieces.append(r"\allowbreak{}")
    return "".join(pieces)


def render_body_html(source: CableSource) -> str:
    blocks: list[str] = []
    for section in REQUIRED_SECTIONS:
        blocks.append(f"<h2>{section}</h2>")
        blocks.extend(_render_section_html(source.sections[section]))
    return "\n".join(blocks)


def _render_section_html(lines: list[str]) -> Iterable[str]:
    for block in _parse_blocks(lines):
        if block.kind == "p":
            yield f"<p>{_html_escape(block.text)}</p>"
        elif block.kind == "ul":
            items = "\n".join(f"<li>{_html_escape(item)}</li>" for item in block.items)
            yield f"<ul>\n{items}\n</ul>"
        else:
            _fail(f"unknown html block kind: {block.kind}")


def render_body_tex(source: CableSource) -> str:
    pieces: list[str] = []
    for section in REQUIRED_SECTIONS:
        pieces.append(rf"\noindent\textbf{{{section}}}\par")
        pieces.append("")
        pieces.extend(_render_section_tex(source.sections[section]))
        pieces.append("")
    return "\n".join(pieces).strip() + "\n"


def _render_section_tex(lines: list[str]) -> Iterable[str]:
    for block in _parse_blocks(lines):
        if block.kind == "p":
            yield _latex_escape(block.text)
            yield ""
        elif block.kind == "ul":
            yield r"\begin{itemize}"
            for item in block.items:
                yield rf"\item {_latex_escape(item)}"
            yield r"\end{itemize}"
            yield ""
        else:
            _fail(f"unknown tex block kind: {block.kind}")


@dataclass(frozen=True)
class Block:
    kind: str
    text: str = ""
    items: tuple[str, ...] = ()


def _parse_blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    buffer: list[str] = []
    bullets: list[str] = []

    def flush_paragraph() -> None:
        nonlocal buffer
        if not buffer:
            return
        text = " ".join(s.strip() for s in buffer).strip()
        if text:
            blocks.append(Block(kind="p", text=text))
        buffer = []

    def flush_bullets() -> None:
        nonlocal bullets
        if not bullets:
            return
        items = tuple(item.strip() for item in bullets if item.strip())
        if items:
            blocks.append(Block(kind="ul", items=items))
        bullets = []

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            flush_bullets()
            flush_paragraph()
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            bullets.append(stripped[2:].strip())
            continue
        flush_bullets()
        buffer.append(stripped)

    flush_bullets()
    flush_paragraph()
    return blocks


def _render_template(template: str, mapping: dict[str, str], *, style: str) -> str:
    out = template
    if style == "html":
        for key, value in mapping.items():
            out = out.replace(f"{{{{ {key} }}}}", value)
        return out
    if style == "tex":
        for key, value in mapping.items():
            out = out.replace(f"{{{{{{{key}}}}}}}", value)
        return out
    _fail(f"unknown template style: {style}")


def _load_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _run_latex(*, engine: str, workdir: Path, tex_path: Path) -> None:
    if engine not in {"lualatex", "pdflatex", "xelatex"}:
        _fail("unknown LaTeX engine")
    if shutil.which(engine) is None:
        _fail(f"LaTeX engine not found on PATH: {engine}")

    cmd = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-output-directory",
        str(workdir),
        str(tex_path),
    ]
    proc = subprocess.run(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        _fail(f"{engine} failed:\n{proc.stdout}")


def build_one(md_path: Path, *, repo_root: Path, engine: str) -> BuiltCable:
    markdown = md_path.read_text(encoding="utf-8")
    source = parse_and_lint_cable_markdown(markdown)

    canonical_url = canonical_url_for_id(source.cable_id)

    canonical_text = _canonical_text_for_hash(source).encode("ascii")
    sha256 = compute_sha256_hex_upper(canonical_text)

    microcode = microcode_line(cable_id=source.cable_id, utc=source.utc, sha256=sha256, sig=source.sig)

    summary = _extract_summary(source)
    if not summary:
        _fail("SUMMARY is empty")

    if not re.fullmatch(r"[0-9A-F]{64}", sha256):
        _fail("SHA-256 is malformed")

    aztec_payload = f"{canonical_url}#sha256={sha256[:16]}"

    build_dir = repo_root / "cables" / "build"
    html_dir = build_dir / "html"
    pdf_dir = build_dir / "pdf"
    aztec_dir = build_dir / "aztec"
    manifest_dir = build_dir / "manifest"

    html_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    aztec_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    aztec_png_path = aztec_dir / f"{source.cable_id}.png"
    try:
        write_aztec_png(aztec_payload, aztec_png_path, module_size=6)
        aztec_data_uri = render_aztec_png(aztec_payload, module_size=6).as_data_uri()
    except AztecError as exc:
        _fail(str(exc))

    body_html = render_body_html(source)
    html_template = _load_template(repo_root / "cables" / "templates" / "cable.html")
    html_out = _render_template(
        html_template,
        {
            "cable_id": _html_escape(source.cable_id),
            "utc": _html_escape(source.utc),
            "sha256": _html_escape(sha256),
            "sig": _html_escape(source.sig),
            "canonical_url": _html_escape(canonical_url),
            "microcode": _html_escape(microcode),
            "body_html": body_html,
            "aztec_data_uri": aztec_data_uri,
        },
        style="html",
    )

    html_path = html_dir / f"{source.cable_id}.html"
    html_path.write_text(html_out, encoding="utf-8")

    body_tex = render_body_tex(source)
    tex_template = _load_template(repo_root / "cables" / "templates" / "cable.tex")
    tex_out = _render_template(
        tex_template,
        {
            "CABLE_ID": _latex_escape(source.cable_id),
            "UTC": _latex_escape(source.utc),
            "SHA256": _latex_escape(sha256),
            "SHA256_TEX": _tex_breakable_hex(sha256, group=8),
            "CANONICAL_URL": _latex_escape(canonical_url),
            "MICROCODE": _latex_escape(microcode),
            "SIG": _latex_escape(source.sig),
            "BODY_TEX": body_tex,
            "AZTEC_PATH": _latex_escape("aztec.png"),
            "PDF_CREATION_DATE": _latex_escape(_to_pdf_date(source.utc)),
            "PDF_TRAILER_ID1": _latex_escape(sha256[:32]),
            "PDF_TRAILER_ID2": _latex_escape(sha256[32:64]),
        },
        style="tex",
    )

    workdir = build_dir / "tmp" / source.cable_id
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(aztec_png_path, workdir / "aztec.png")
    tex_path = workdir / "cable.tex"
    tex_path.write_text(tex_out, encoding="utf-8")

    _run_latex(engine=engine, workdir=workdir, tex_path=tex_path)
    _run_latex(engine=engine, workdir=workdir, tex_path=tex_path)

    built_pdf_path = workdir / "cable.pdf"
    if not built_pdf_path.exists():
        _fail("pdflatex did not produce cable.pdf")

    pdf_path = pdf_dir / f"{source.cable_id}.pdf"
    pdf_path.write_bytes(built_pdf_path.read_bytes())

    built = BuiltCable(
        cable_id=source.cable_id,
        utc=source.utc,
        title=source.title,
        canonical_url=canonical_url,
        sha256=sha256,
        microcode=microcode,
        summary=summary,
        html_path=str(html_path.relative_to(repo_root)),
        pdf_path=str(pdf_path.relative_to(repo_root)),
        aztec_payload=aztec_payload,
    )

    (manifest_dir / f"{source.cable_id}.json").write_text(
        json.dumps(asdict(built), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return built


def _load_manifests(repo_root: Path) -> list[BuiltCable]:
    manifest_dir = repo_root / "cables" / "build" / "manifest"
    if not manifest_dir.exists():
        return []
    cables: list[BuiltCable] = []
    for path in sorted(manifest_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cables.append(BuiltCable(**data))
    cables.sort(key=lambda c: c.utc, reverse=True)
    return cables


def _now_utc_rfc2822() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def write_feed(repo_root: Path, cables: list[BuiltCable]) -> None:
    build_dir = repo_root / "cables" / "build"
    feed_path = build_dir / "feed.xml"

    items: list[str] = []
    for cable in cables:
        enclosure_url = f"{CANONICAL_BASE_URL}/pdf/{cable.cable_id}.pdf"
        items.append(
            "\n".join(
                [
                    "    <item>",
                    f"      <title>{_xml_escape(cable.cable_id)}</title>",
                    f"      <link>{_xml_escape(cable.canonical_url)}</link>",
                    f"      <guid isPermaLink=\"false\">{_xml_escape(cable.sha256)}</guid>",
                    f"      <pubDate>{_xml_escape(_to_rfc2822(cable.utc))}</pubDate>",
                    f"      <description>{_xml_escape(cable.summary)}</description>",
                    f"      <enclosure url=\"{_xml_escape(enclosure_url)}\" type=\"application/pdf\" />",
                    "      <content:encoded><![CDATA["
                    + _feed_content_html(repo_root, cable)
                    + "]]></content:encoded>",
                    "    </item>",
                ]
            )
        )

    xml = "\n".join(
        [
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<rss version=\"2.0\" xmlns:content=\"http://purl.org/rss/1.0/modules/content/\">",
            "  <channel>",
            "    <title>MSPMetro Cables</title>",
            f"    <link>{CANONICAL_BASE_URL}</link>",
            "    <description>Verifiable, print-resilient situational awareness documents.</description>",
            f"    <lastBuildDate>{_now_utc_rfc2822()}</lastBuildDate>",
            "    <language>en-us</language>",
            *items,
            "  </channel>",
            "</rss>",
            "",
        ]
    )
    feed_path.write_text(xml, encoding="utf-8")


def _feed_content_html(repo_root: Path, cable: BuiltCable) -> str:
    html_path = repo_root / cable.html_path
    html = html_path.read_text(encoding="utf-8")
    start = html.find("<main>")
    end = html.rfind("</main>")
    if start == -1 or end == -1:
        return html
    return html[start:end + len("</main>")]


def _to_rfc2822(utc_zulu: str) -> str:
    dt = datetime.strptime(utc_zulu, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _to_pdf_date(utc_zulu: str) -> str:
    dt = datetime.strptime(utc_zulu, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    return dt.strftime("D:%Y%m%d%H%M00Z")


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def iter_markdown_sources(repo_root: Path) -> list[Path]:
    content_dir = repo_root / "cables" / "content"
    if not content_dir.exists():
        return []
    return sorted(content_dir.rglob("*.md"))


def write_index_and_bundles(repo_root: Path, cables: list[BuiltCable]) -> None:
    if not cables:
        return

    build_dir = repo_root / "cables" / "build"
    html_dir = build_dir / "html"
    pdf_dir = build_dir / "pdf"
    daily_pdf_dir = pdf_dir / "daily"

    html_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    daily_pdf_dir.mkdir(parents=True, exist_ok=True)

    by_day: dict[str, list[BuiltCable]] = {}
    for cable in cables:
        day = _day_from_cable_id(cable.cable_id)
        by_day.setdefault(day, []).append(cable)

    for day in by_day:
        by_day[day].sort(key=lambda c: c.utc, reverse=True)

    all_zip_path = pdf_dir / "cables-all.zip"
    _write_pdf_bundle(all_zip_path, [repo_root / c.pdf_path for c in cables])

    for day, day_cables in by_day.items():
        day_zip_path = daily_pdf_dir / f"{day}.zip"
        _write_pdf_bundle(day_zip_path, [repo_root / c.pdf_path for c in day_cables])

    index_template = _load_template(repo_root / "cables" / "templates" / "index.html")
    day_blocks_html = _render_day_blocks(by_day)
    index_html = _render_template(
        index_template,
        {
            "all_pdfs_zip_href": _html_escape("../pdf/cables-all.zip"),
            "day_blocks_html": day_blocks_html,
        },
        style="html",
    )
    (html_dir / "index.html").write_text(index_html, encoding="utf-8")

    for day, day_cables in by_day.items():
        daily_html = _render_daily_page(day, day_cables)
        (html_dir / f"daily-{day}.html").write_text(daily_html, encoding="utf-8")


def _day_from_cable_id(cable_id: str) -> str:
    match = re.fullmatch(r"MSPM-CBL-(\d{4}-\d{2}-\d{2})-\d{3}", cable_id)
    if not match:
        _fail("cannot parse date from cable id")
    return match.group(1)


def _render_day_blocks(by_day: dict[str, list[BuiltCable]]) -> str:
    blocks: list[str] = []
    for day in sorted(by_day.keys(), reverse=True):
        day_cables = by_day[day]
        blocks.append('<section class="day">')
        blocks.append(
            f"<h2>{_html_escape(day)} "
            f"(<a href=\"{_html_escape('daily-' + day + '.html')}\">view</a>, "
            f"<a href=\"{_html_escape('../pdf/daily/' + day + '.zip')}\">PDFs .zip</a>)</h2>"
        )
        blocks.append(_render_cables_table(day_cables))
        blocks.append("</section>")
    return "\n".join(blocks)


def _render_cables_table(cables: list[BuiltCable]) -> str:
    rows: list[str] = []
    for cable in cables:
        rows.append(
            "\n".join(
                [
                    "<tr>",
                    f"  <td class=\"mono\"><a href=\"{_html_escape('./' + cable.cable_id + '.html')}\">{_html_escape(cable.cable_id)}</a></td>",
                    f"  <td class=\"mono\">{_html_escape(cable.utc)}</td>",
                    f"  <td>{_html_escape(cable.summary)}</td>",
                    f"  <td class=\"mono\">{_html_escape(cable.sha256[:16])}…</td>",
                    "  <td>"
                    f"<a href=\"{_html_escape(cable.canonical_url)}\">Canonical</a>"
                    f" | <a href=\"{_html_escape('../pdf/' + cable.cable_id + '.pdf')}\">PDF</a>"
                    "</td>",
                    "</tr>",
                ]
            )
        )

    return (
        "<table>\n"
        "  <thead>\n"
        "    <tr><th>Cable</th><th>UTC</th><th>Summary</th><th>SHA-256</th><th>Links</th></tr>\n"
        "  </thead>\n"
        "  <tbody>\n"
        + "\n".join(rows)
        + "\n  </tbody>\n"
        "</table>"
    )


def _render_daily_page(day: str, cables: list[BuiltCable]) -> str:
    table = _render_cables_table(cables)
    zip_href = f"../pdf/daily/{day}.zip"
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "  <head>",
            "    <meta charset=\"utf-8\" />",
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />",
            f"    <title>MSPMetro Cables - { _html_escape(day) }</title>",
            "    <style>",
            "      :root { color-scheme: light; }",
            "      @font-face { font-family: \"Oswald\"; src: url(\"/static/fonts/oswald-v57-latin-regular.woff2\") format(\"woff2\"); font-style: normal; font-weight: 400; font-display: swap; }",
            "      @font-face { font-family: \"Intel One Mono\"; src: url(\"/static/fonts/IntelOneMono-Regular.otf\") format(\"opentype\"); font-style: normal; font-weight: 400; font-display: swap; }",
            "      body { font-family: \"Intel One Mono\", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", monospace; margin: 0; padding: 0; color: #111; }",
            "      main { max-width: 980px; margin: 32px auto; padding: 0 20px; }",
            "      h1 { font-family: \"Oswald\", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; font-size: 22px; margin: 0 0 8px; letter-spacing: 0.02em; }",
            "      p, li { font-size: 14px; line-height: 1.4; }",
            "      .meta { font-size: 13px; color: #333; margin: 0 0 18px; }",
            "      table { width: 100%; border-collapse: collapse; }",
            "      th, td { text-align: left; padding: 8px 8px; vertical-align: top; border-bottom: 1px solid #e6e6e6; }",
            "      th { font-size: 12px; color: #333; font-weight: 600; }",
            "      td { font-size: 13px; }",
            "      td.mono { font-family: \"Intel One Mono\", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", monospace; font-size: 12px; }",
            "      a { color: inherit; text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 2px; }",
            "    </style>",
            "  </head>",
            "  <body>",
            "    <main>",
            f"      <h1>MSPMetro Cables - {_html_escape(day)}</h1>",
            f"      <p class=\"meta\"><a href=\"index.html\">Back to all cables</a> | <a href=\"{_html_escape(zip_href)}\">Download PDFs (.zip)</a></p>",
            table,
            "    </main>",
            "  </body>",
            "</html>",
            "",
        ]
    )


def _write_pdf_bundle(zip_path: Path, pdf_paths: list[Path]) -> None:
    fixed_date_time = (1980, 1, 1, 0, 0, 0)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for pdf_path in sorted(pdf_paths, key=lambda p: p.name):
            data = pdf_path.read_bytes()
            info = zipfile.ZipInfo(filename=pdf_path.name, date_time=fixed_date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o644 & 0xFFFF) << 16
            zf.writestr(info, data)
    tmp_path.replace(zip_path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build MSPMetro cables (HTML + PDF + feed) from Markdown.")
    parser.add_argument("--in", dest="in_path", help="Path to one cable Markdown file.")
    parser.add_argument("--all", action="store_true", help="Build all cables under cables/content.")
    parser.add_argument(
        "--engine",
        default="pdflatex",
        choices=["lualatex", "pdflatex", "xelatex"],
        help="LaTeX engine for PDF build (default: pdflatex).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]

    try:
        if bool(args.in_path) == bool(args.all):
            _fail("exactly one of --in or --all is required")

        built: list[BuiltCable] = []
        if args.in_path:
            built.append(build_one(Path(args.in_path), repo_root=repo_root, engine=args.engine))
        else:
            for md_path in iter_markdown_sources(repo_root):
                built.append(build_one(md_path, repo_root=repo_root, engine=args.engine))

        manifests = _load_manifests(repo_root)
        write_feed(repo_root, manifests)
        write_index_and_bundles(repo_root, manifests)
    except (BuildError, LintError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
