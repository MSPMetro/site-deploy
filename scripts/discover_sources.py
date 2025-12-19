#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


UA_PROFILES: dict[str, str] = {
    "safari-mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.10 Safari/605.1.1"
    ),
    "chrome-mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.3"
    ),
    "chrome-win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.3"
    ),
    "chrome-linux": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.3"
    ),
}


def normalize_url(u: str) -> str:
    u = u.strip()
    if not u:
        return ""
    u = u.split("#", 1)[0]
    return u


class FeedLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.feed_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        d = {k.lower(): (v or "") for k, v in attrs}
        rel = d.get("rel", "").lower()
        typ = d.get("type", "").lower()
        href = d.get("href", "").strip()
        if not href:
            return
        if "alternate" not in rel:
            return
        if typ in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
            self.feed_hrefs.append(href)


class ArticleMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self._in_ld_json = False
        self._ld_json_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        d = {k.lower(): (v or "") for k, v in attrs}
        if t == "meta":
            name = (d.get("name") or d.get("property") or "").strip().lower()
            content = (d.get("content") or "").strip()
            if name and content and name not in self.meta:
                self.meta[name] = content
        if t == "script":
            typ = (d.get("type") or "").strip().lower()
            if typ == "application/ld+json":
                self._in_ld_json = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_ld_json:
            self._in_ld_json = False

    def handle_data(self, data: str) -> None:
        if self._in_ld_json:
            self._ld_json_chunks.append(data)


def _first(*vals: str) -> str:
    for v in vals:
        v = (v or "").strip()
        if v:
            return v
    return ""


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _safe_slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s[:80] or "site"


@dataclass
class CachedResponse:
    url: str
    status: int
    fetched_at: float
    content_type: str
    headers: dict[str, str]
    body_path: Path


class DiskCache:
    def __init__(self, root: Path, ttl_seconds: int) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)

    def _key_dir(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.root / h[:2] / h[2:4] / h

    def get(self, url: str) -> CachedResponse | None:
        d = self._key_dir(url)
        meta_path = d / "meta.json"
        body_path = d / "body.bin"
        if not meta_path.exists() or not body_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched_at = float(meta.get("fetched_at") or 0.0)
            if fetched_at and (time.time() - fetched_at) > self.ttl_seconds:
                return None
            return CachedResponse(
                url=url,
                status=int(meta.get("status") or 0),
                fetched_at=fetched_at,
                content_type=str(meta.get("content_type") or ""),
                headers=dict(meta.get("headers") or {}),
                body_path=body_path,
            )
        except Exception:
            return None

    def put(self, url: str, *, status: int, headers: dict[str, str], content_type: str, body: bytes) -> CachedResponse:
        d = self._key_dir(url)
        d.mkdir(parents=True, exist_ok=True)
        body_path = d / "body.bin"
        meta_path = d / "meta.json"
        body_path.write_bytes(body)
        meta = {
            "url": url,
            "status": int(status),
            "fetched_at": time.time(),
            "content_type": content_type,
            "headers": headers,
        }
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        return CachedResponse(url=url, status=status, fetched_at=meta["fetched_at"], content_type=content_type, headers=headers, body_path=body_path)


class DomainLimiter:
    def __init__(self, *, min_delay: float, max_delay: float) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._lock = asyncio.Lock()
        self._next_ok = 0.0

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.time()
            if now < self._next_ok:
                await asyncio.sleep(self._next_ok - now)
            delay = random.uniform(self.min_delay, self.max_delay)
            self._next_ok = time.time() + delay


class RobotsCache:
    def __init__(self, cache: DiskCache, *, ua: str) -> None:
        self.cache = cache
        self.ua = ua
        self._mem: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def allowed(self, url: str, fetch: "Fetcher") -> bool:
        parsed = urllib.parse.urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base in self._mem:
            rp = self._mem[base]
            return rp.can_fetch(self.ua, url)

        robots_url = urllib.parse.urljoin(base + "/", "robots.txt")
        raw = await fetch.get_bytes(robots_url, accept="text/plain", _skip_robots=True)
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.parse(raw.decode("utf-8", errors="replace").splitlines())
        except Exception:
            # If robots is unparsable, default to allow.
            self._mem[base] = rp
            return True

        self._mem[base] = rp
        return rp.can_fetch(self.ua, url)


class Fetcher:
    def __init__(
        self,
        *,
        cache: DiskCache,
        ua: str,
        min_delay: float,
        max_delay: float,
        max_bytes: int,
        concurrency: int,
        respect_robots: bool,
    ) -> None:
        self.cache = cache
        self.ua = ua
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self._sem = asyncio.Semaphore(concurrency)
        self._limiters: dict[str, DomainLimiter] = {}
        self.robots = RobotsCache(cache, ua=ua)

    def _limiter(self, url: str) -> DomainLimiter:
        host = urllib.parse.urlparse(url).netloc.lower()
        if host not in self._limiters:
            self._limiters[host] = DomainLimiter(min_delay=self.min_delay, max_delay=self.max_delay)
        return self._limiters[host]

    async def get_bytes(self, url: str, *, accept: str, _skip_robots: bool = False) -> bytes:
        url = normalize_url(url)
        if not url:
            raise ValueError("empty url")

        cached = self.cache.get(url)
        if cached and cached.status == 200:
            return cached.body_path.read_bytes()

        if (not _skip_robots) and self.respect_robots and not await self.robots.allowed(url, self):
            raise PermissionError(f"disallowed by robots.txt: {url}")

        limiter = self._limiter(url)
        await limiter.wait_turn()

        async with self._sem:
            return await asyncio.to_thread(self._blocking_get, url, accept)

    def _blocking_get(self, url: str, accept: str) -> bytes:
        cached = self.cache.get(url)
        if cached and cached.status == 200:
            return cached.body_path.read_bytes()

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.ua,
                "Accept": accept,
                "Accept-Language": "en-US,en;q=0.8",
                "DNT": "1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                status = int(getattr(resp, "status", 200) or 200)
                headers = {k.lower(): v for k, v in resp.headers.items()}
                content_type = headers.get("content-type", "")
                body = resp.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    body = body[: self.max_bytes]
                self.cache.put(url, status=status, headers=headers, content_type=content_type, body=body)
                return body
        except urllib.error.HTTPError as e:
            status = int(getattr(e, "code", 0) or 0)
            body = e.read(self.max_bytes + 1) if hasattr(e, "read") else b""
            headers = {k.lower(): v for k, v in getattr(e, "headers", {}).items()} if getattr(e, "headers", None) else {}
            content_type = headers.get("content-type", "")
            self.cache.put(url, status=status, headers=headers, content_type=content_type, body=body)
            raise


def candidate_feed_urls(base: str, html_bytes: bytes) -> list[str]:
    html = html_bytes.decode("utf-8", errors="replace")
    p = FeedLinkParser()
    try:
        p.feed(html)
    except Exception:
        pass

    out: list[str] = []
    seen = set()

    def add(u: str) -> None:
        u = normalize_url(u)
        if not u:
            return
        if u in seen:
            return
        seen.add(u)
        out.append(u)

    for href in p.feed_hrefs:
        add(urllib.parse.urljoin(base, href))

    parsed = urllib.parse.urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    common_paths = [
        "/feed",
        "/rss",
        "/rss.xml",
        "/atom.xml",
        "/index.xml",
        "/feed.xml",
        "/feeds/posts/default?alt=rss",
    ]
    for path in common_paths:
        add(urllib.parse.urljoin(origin, path))

    return out


def parse_feed(feed_url: str, raw: bytes, *, limit: int) -> dict[str, Any]:
    txt = raw.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(txt)
    except Exception:
        return {"ok": False, "error": "invalid XML", "items": []}

    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}

    items: list[dict[str, Any]] = []
    kind = "unknown"
    feed_title = ""
    feed_home = ""

    channel = root.find("channel")
    if channel is not None:
        kind = "rss"
        feed_title = _text(channel.find("title"))
        feed_home = _text(channel.find("link"))
        for it in channel.findall("item")[:limit]:
            title = _text(it.find("title"))
            link = _text(it.find("link"))
            guid = _text(it.find("guid"))
            creator = _text(it.find("dc:creator", ns))
            author = _text(it.find("author"))
            pub = _text(it.find("pubDate"))
            items.append({"title": title, "url": _first(link, guid), "author": _first(creator, author), "published": pub})
        return {"ok": True, "kind": kind, "feed_title": feed_title, "feed_home": feed_home, "items": items}

    if root.tag.endswith("feed"):
        kind = "atom"
        t1 = root.find("atom:title", ns)
        t2 = root.find("title")
        feed_title = _text(t1 if t1 is not None else t2)
        for l in root.findall("atom:link", ns) + root.findall("link"):
            href = l.attrib.get("href", "").strip()
            rel = l.attrib.get("rel", "").strip()
            if href and rel in {"", "alternate"}:
                feed_home = href
                break
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        for e in entries[:limit]:
            t1 = e.find("atom:title", ns)
            t2 = e.find("title")
            title = _text(t1 if t1 is not None else t2)
            u1 = e.find("atom:updated", ns)
            u2 = e.find("updated")
            updated = _text(u1 if u1 is not None else u2)
            p1 = e.find("atom:published", ns)
            p2 = e.find("published")
            published = _text(p1 if p1 is not None else p2)
            author = ""
            a1 = e.find("atom:author", ns)
            a2 = e.find("author")
            a = a1 if a1 is not None else a2
            if a is not None:
                n1 = a.find("atom:name", ns)
                n2 = a.find("name")
                author = _text(n1 if n1 is not None else n2)
            link = ""
            for l in e.findall("atom:link", ns) + e.findall("link"):
                href = l.attrib.get("href", "").strip()
                rel = l.attrib.get("rel", "").strip()
                if href and (rel in {"", "alternate"}):
                    link = href
                    break
            items.append({"title": title, "url": link, "author": author, "published": _first(published, updated)})
        return {"ok": True, "kind": kind, "feed_title": feed_title, "feed_home": feed_home, "items": items}

    return {"ok": False, "error": "unrecognized feed format", "items": []}


def extract_author_from_html(html_bytes: bytes) -> str:
    html = html_bytes.decode("utf-8", errors="replace")
    p = ArticleMetaParser()
    try:
        p.feed(html)
    except Exception:
        pass

    meta = p.meta
    author = _first(meta.get("author", ""), meta.get("parsely-author", ""), meta.get("article:author", ""))
    if author:
        return author

    ld = "\n".join(p._ld_json_chunks).strip()
    if not ld:
        return ""

    # ld+json can contain multiple JSON objects; parse cautiously.
    candidates: list[Any] = []
    for chunk in re.split(r"\n\\s*\n", ld):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            candidates.append(json.loads(chunk))
        except Exception:
            continue

    def pull_author(obj: Any) -> str:
        if isinstance(obj, dict):
            a = obj.get("author")
            if isinstance(a, dict):
                return (a.get("name") or "").strip()
            if isinstance(a, list) and a:
                first = a[0]
                if isinstance(first, dict):
                    return (first.get("name") or "").strip()
                if isinstance(first, str):
                    return first.strip()
            if isinstance(a, str):
                return a.strip()
            g = obj.get("@graph")
            if isinstance(g, list):
                for it in g:
                    r = pull_author(it)
                    if r:
                        return r
        return ""

    for c in candidates:
        a = pull_author(c)
        if a:
            return a
    return ""


async def discover_for_site(
    site_url: str,
    *,
    fetcher: Fetcher,
    sample_items: int,
    fetch_articles: bool,
    max_articles_per_feed: int,
) -> dict[str, Any]:
    site_url = normalize_url(site_url)
    if not site_url:
        return {}

    rec: dict[str, Any] = {"site_url": site_url, "feeds": [], "errors": []}

    try:
        html = await fetcher.get_bytes(site_url, accept="text/html,application/xhtml+xml")
    except Exception as e:
        rec["errors"].append(f"fetch site failed: {e}")
        return rec

    feeds = candidate_feed_urls(site_url, html)
    checked = 0
    for fu in feeds:
        if checked >= 6:
            break
        try:
            raw = await fetcher.get_bytes(fu, accept="application/rss+xml,application/atom+xml,application/xml,text/xml,*/*")
        except Exception:
            continue
        parsed = parse_feed(fu, raw, limit=sample_items)
        if not parsed.get("ok"):
            continue

        feed_rec: dict[str, Any] = {"feed_url": fu, **parsed}

        if fetch_articles:
            fetched = 0
            paywalled = 0
            for item in feed_rec.get("items") or []:
                if fetched >= max_articles_per_feed:
                    break
                url = (item.get("url") or "").strip()
                if not url:
                    continue
                try:
                    art = await fetcher.get_bytes(url, accept="text/html,application/xhtml+xml,*/*")
                except Exception:
                    continue
                if looks_paywalled(art):
                    item["paywalled"] = True
                    paywalled += 1
                    continue
                discovered_author = extract_author_from_html(art)
                if discovered_author and not item.get("author"):
                    item["author"] = discovered_author
                fetched += 1
            feed_rec["paywalled_sampled"] = paywalled
            feed_rec["fetched_sampled"] = fetched

        rec["feeds"].append(feed_rec)
        checked += 1

    if not rec["feeds"]:
        rec["errors"].append("no valid RSS/Atom feeds found (may require manual endpoints or HTML scraping)")

    return rec


def read_seeds(path: str) -> list[str]:
    out: list[str] = []
    for line in open(path, "r", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def read_denylist(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line.lower())
    return out


def is_denied(url: str, denied: list[str]) -> bool:
    u = (url or "").lower()
    for d in denied:
        if d and d in u:
            return True
    return False


def looks_paywalled(html_bytes: bytes) -> bool:
    html = html_bytes.decode("utf-8", errors="replace").lower()
    # Heuristics for common paywall/metered frameworks + UI copy.
    patterns = [
        r"\bpaywall\b",
        r"\bmetered\b",
        r"\bavailable to subscribers\b",
        r"\bfor subscribers\b",
        r"\bsubscription required\b",
        r"\bsign in to continue\b",
        r"\bsign in\b.*\bto continue reading\b",
        r"\bcontinue reading\b.*\bsubscribe\b",
        r"\bsubscribe\b.*\bto continue reading\b",
        r"\bthis content is only available\b.*\bsubscribers?\b",
        r"\bregister\b.*\bto continue reading\b",
        r"tinypass|piano\.io|cxense|zephr|leaky-paywall|laterpay|subscriptions?\.",
        r"data-paywall|class=[\"'][^\"']*paywall|id=[\"'][^\"']*paywall",
        r"meteredcontent|arc-paywall|cpt-shim|tp-modal",
        r"amp-access|subscribe\.js|paywall\.js",
    ]
    for pat in patterns:
        try:
            if re.search(pat, html):
                return True
        except re.error:
            continue
    return False


async def run(args: argparse.Namespace) -> int:
    seeds = read_seeds(args.seeds)
    denied = read_denylist(args.denylist)
    denied_paywalled = read_denylist(args.denylist_paywalled)
    seeds = [s for s in seeds if not is_denied(s, denied)]
    seeds = [s for s in seeds if not is_denied(s, denied_paywalled)]

    ua = UA_PROFILES.get(args.ua_profile, "")
    if not ua:
        raise SystemExit(f"unknown --ua-profile {args.ua_profile!r}; choose from: {', '.join(sorted(UA_PROFILES))}")

    cache = DiskCache(Path(args.cache_dir), ttl_seconds=int(args.cache_ttl_hours * 3600))
    fetcher = Fetcher(
        cache=cache,
        ua=ua,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_bytes=args.max_bytes,
        concurrency=args.concurrency,
        respect_robots=not args.ignore_robots,
    )

    results: list[dict[str, Any]] = []

    # Fan out per-site tasks; per-domain throttling keeps it polite.
    tasks = []
    for s in seeds[: args.max_sites]:
        if is_denied(s, denied):
            continue
        tasks.append(
            asyncio.create_task(
                discover_for_site(
                    s,
                    fetcher=fetcher,
                    sample_items=args.sample,
                    fetch_articles=not args.no_fetch_articles,
                    max_articles_per_feed=args.max_articles_per_feed,
                )
            )
        )
    for t in asyncio.as_completed(tasks):
        rec = await t
        if rec:
            # Final filter: strip denied feeds/items if they slipped in via redirects.
            rec["feeds"] = [
                f
                for f in (rec.get("feeds") or [])
                if not is_denied(f.get("feed_url") or "", denied)
                and not is_denied(f.get("feed_url") or "", denied_paywalled)
            ]
            for f in rec["feeds"]:
                # Strip paywalled items (either via denylist or heuristic author-extraction fetch).
                f["items"] = [
                    it
                    for it in (f.get("items") or [])
                    if not is_denied(it.get("url") or "", denied)
                    and not is_denied(it.get("url") or "", denied_paywalled)
                    and not bool(it.get("paywalled"))
                ]
            # Drop feeds that appear mostly paywalled in sampled article fetches.
            rec["feeds"] = [
                f
                for f in rec["feeds"]
                if not (
                    (f.get("paywalled_sampled") is not None)
                    and (f.get("fetched_sampled") is not None)
                    and (
                        (int(f.get("paywalled_sampled") or 0) + int(f.get("fetched_sampled") or 0)) > 0
                    )
                    and (
                        (int(f.get("paywalled_sampled") or 0) / float(int(f.get("paywalled_sampled") or 0) + int(f.get("fetched_sampled") or 0)))
                        > float(args.max_paywall_ratio)
                    )
                )
            ]
            results.append(rec)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": results}
    out_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path} ({len(results)} sites)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Discover RSS/Atom feeds and sample recent items (polite + cached).")
    ap.add_argument("--seeds", default="docs/source_discovery/seed_urls.txt", help="Seed list file (one URL per line)")
    ap.add_argument("--out", default="docs/source_discovery/discovered_sources.json", help="Output JSON path")
    ap.add_argument("--cache-dir", default="data/cache/source_discovery", help="Cache directory (gitignored)")
    ap.add_argument("--cache-ttl-hours", type=float, default=24.0, help="Cache TTL (hours)")
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

    ap.add_argument("--sample", type=int, default=5, help="Sample items per feed")
    ap.add_argument("--max-articles-per-feed", type=int, default=5, help="Max article pages to fetch per feed for author extraction")
    ap.add_argument("--no-fetch-articles", action="store_true", help="Do not fetch article pages (feeds only)")
    ap.add_argument(
        "--max-paywall-ratio",
        type=float,
        default=0.5,
        help="If sampled articles are mostly paywalled, drop the entire feed (0.0-1.0).",
    )

    ap.add_argument("--min-delay", type=float, default=10.0, help="Min per-domain delay between requests (seconds)")
    ap.add_argument("--max-delay", type=float, default=30.0, help="Max per-domain delay between requests (seconds)")
    ap.add_argument("--concurrency", type=int, default=4, help="Max concurrent in-flight requests (overall)")
    ap.add_argument("--max-sites", type=int, default=200, help="Max sites to process from the seeds list")
    ap.add_argument("--max-bytes", type=int, default=2_000_000, help="Max bytes per response to store (default 2MB)")

    ap.add_argument(
        "--ua-profile",
        default="chrome-linux",
        choices=sorted(UA_PROFILES.keys()),
        help="User-Agent profile to use (matches common browser UA strings)",
    )
    ap.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt (not recommended)")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.min_delay < 0 or args.max_delay < 0 or args.max_delay < args.min_delay:
        raise SystemExit("invalid delay range")
    if args.max_paywall_ratio < 0 or args.max_paywall_ratio > 1:
        raise SystemExit("invalid --max-paywall-ratio (must be 0.0-1.0)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
