from __future__ import annotations

import html
import re
import unicodedata

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", flags=re.IGNORECASE | re.DOTALL)
_WELL_FORMED_TAG_RE = re.compile(r"<[^>]*>")
# Handles incomplete tags like "<img width=..." that never close (often due to truncation).
_TAG_FRAGMENT_RE = re.compile(r"<[A-Za-z!/][^>\n]{0,5000}")

_IMG_ATTR_GARBAGE_RE = re.compile(
    r"""(?ix)
    (?:^|\s)
    img\s+width\s*=\s*["']?\d{1,5}["']?
    (?:\s+[a-z][a-z0-9:_-]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s]+)){0,60}
    """
)
_ATTR_GARBAGE_RE = re.compile(
    r"""(?ix)
    \b(?:srcset|src|sizes|decoding|loading|fetchpriority|referrerpolicy)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s]+)
    """
)
_WP_IMG_GARBAGE_RE = re.compile(r"(?i)\b(?:wp-post-image|attachment-rss-image-size|size-rss-image-size)\b")


def strip_markup_to_text(s: str) -> str:
    if not s:
        return ""

    s = html.unescape(s).replace("\u00a0", " ")

    s = _SCRIPT_STYLE_RE.sub(" ", s)

    # Remove HTML tags (best-effort).
    s = _WELL_FORMED_TAG_RE.sub(" ", s)
    # Remove dangling tag fragments that never close.
    s = re.sub(r"<[^\n]*$", " ", s)
    s = _TAG_FRAGMENT_RE.sub(" ", s)
    # If any angle brackets remain, they should never reach the user.
    s = s.replace("<", " ").replace(">", " ")

    # Remove common image-attribute garbage that can survive truncation/escaping.
    s = _IMG_ATTR_GARBAGE_RE.sub(" ", s)
    s = _ATTR_GARBAGE_RE.sub(" ", s)
    s = _WP_IMG_GARBAGE_RE.sub(" ", s)

    # Drop control/format characters (e.g., zero-width joiners, bidi marks).
    s = "".join(ch for ch in s if unicodedata.category(ch) not in {"Cc", "Cf"})
    # Replace a few common "bad decode" sentinels.
    s = s.replace("\ufffd", " ").replace("\ufffc", " ")

    return re.sub(r"\s+", " ", s).strip()
