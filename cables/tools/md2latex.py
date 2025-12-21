#!/usr/bin/env python3
import re

RE_RAW_HTML_TAG = re.compile(r"<[A-Za-z/!][^>]*>")

_LATEX_ESCAPES = {
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

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(.+?)\*(?!\*)")
_CODE_RE = re.compile(r"`(.+?)`")


class MdSanitizationError(RuntimeError):
    pass


def ensure_ascii(text: str, *, context: str) -> None:
    for index, ch in enumerate(text):
        if ord(ch) > 127:
            raise MdSanitizationError(f"{context}: non-ASCII character at index {index}: U+{ord(ch):04X}")


def reject_raw_html(text: str, *, context: str) -> None:
    if RE_RAW_HTML_TAG.search(text):
        raise MdSanitizationError(f"{context}: raw HTML detected (disallowed)")


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def latex_escape(text: str) -> str:
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in text)


def md_inline_to_latex(text: str) -> str:
    text = latex_escape(text)
    text = _CODE_RE.sub(r"\\texttt{\1}", text)
    text = _BOLD_RE.sub(r"\\textbf{\1}", text)
    text = _ITALIC_RE.sub(r"\\textit{\1}", text)
    return text

