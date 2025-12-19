#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize discovered sources into a CSV (author/source/url/article).")
    ap.add_argument("--in", dest="inp", default="docs/source_discovery/discovered_sources.json")
    ap.add_argument("--out", dest="outp", default="docs/source_discovery/discovered_articles.csv")
    ap.add_argument(
        "--denylist",
        default="docs/source_discovery/denylist_domains.txt",
        help="Denylist file (domain substrings, one per line)",
    )
    ap.add_argument(
        "--denylist-paywalled",
        default="docs/source_discovery/denylist_paywalled_domains.txt",
        help="Paywalled denylist file (domain substrings, one per line)",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    results = data.get("results") or []

    def read_deny(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [ln.strip().lower() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]

    denied = read_deny(args.denylist)
    denied_paywalled = read_deny(args.denylist_paywalled)

    def is_denied(u: str) -> bool:
        u = (u or "").lower()
        return any(d and d in u for d in denied) or any(d and d in u for d in denied_paywalled)

    rows: list[dict[str, str]] = []
    for r in results:
        site = r.get("site_url") or ""
        if is_denied(site):
            continue
        for f in r.get("feeds") or []:
            feed_title = f.get("feed_title") or ""
            feed_url = f.get("feed_url") or ""
            if is_denied(feed_url):
                continue
            for it in f.get("items") or []:
                if it.get("paywalled"):
                    continue
                if is_denied(it.get("url") or ""):
                    continue
                rows.append(
                    {
                        "source": feed_title or site,
                        "source_url": site,
                        "feed_url": feed_url,
                        "title": (it.get("title") or ""),
                        "url": (it.get("url") or ""),
                        "author": (it.get("author") or ""),
                        "published": (it.get("published") or ""),
                    }
                )

    out_path = Path(args.outp)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["source", "source_url", "feed_url", "title", "url", "author", "published"],
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print(f"wrote {out_path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
