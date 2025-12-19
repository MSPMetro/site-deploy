from __future__ import annotations

import json
import hashlib
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

from sqlalchemy.orm import Session

from .db import session
from .text_clean import strip_markup_to_text
from .models import (
    Alert,
    AlertSeverity,
    EndpointKind,
    IngestionMetric,
    IngestionRun,
    Item,
    ItemKind,
    ScopeKind,
    Source,
    SourceEndpoint,
    SourceTier,
)


@dataclass(frozen=True)
class IngestResult:
    inserted: int
    updated: int


def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    u = u.split("#", 1)[0].strip()
    if u.endswith("/"):
        u = u[:-1]
    return u


def _load_denylist_urls() -> set[str]:
    path = (os.environ.get("MSPMETRO_DENYLIST_URLS_FILE") or "backend/config/denylist_urls.txt").strip()
    denied: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                denied.add(_normalize_url(ln))
    except FileNotFoundError:
        return set()
    except Exception:
        return set()
    return denied


def _user_agent() -> str:
    ua = os.environ.get("MSPMETRO_USER_AGENT", "").strip()
    if ua:
        return ua

    profile = (os.environ.get("MSPMETRO_UA_PROFILE") or "chrome-linux").strip()
    profiles = {
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
    return profiles.get(profile, profiles["chrome-linux"])


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # NWS uses RFC3339 timestamps.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_dt_any(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    # Try RFC3339/ISO first.
    dt = _parse_dt(v)
    if dt:
        return dt
    # RSS commonly uses RFC822.
    try:
        dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _map_nws_severity(nws: str | None) -> AlertSeverity:
    # NWS severity values: Minor, Moderate, Severe, Extreme, Unknown
    v = (nws or "").strip().lower()
    if v == "extreme":
        return AlertSeverity.EMERGENCY
    if v == "severe":
        return AlertSeverity.WARNING
    if v == "moderate":
        return AlertSeverity.ADVISORY
    return AlertSeverity.INFO


def _fetch_json(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": _user_agent(), "Accept": "application/geo+json"})
    with urlopen(req, timeout=30) as resp:  # nosec - allowlisted public API
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


@dataclass(frozen=True)
class FetchBytesResult:
    status: int
    body: bytes
    etag: str | None
    last_modified: str | None


def _fetch_bytes(url: str, *, accept: str, etag: str | None = None, last_modified: str | None = None) -> FetchBytesResult:
    headers = {"User-Agent": _user_agent(), "Accept": accept}
    headers["Accept-Language"] = "en-US,en;q=0.8"
    headers["DNT"] = "1"
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:  # nosec - allowlisted public endpoints
            status = int(getattr(resp, "status", 200) or 200)
            body = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return FetchBytesResult(
                status=status,
                body=body,
                etag=resp_headers.get("etag"),
                last_modified=resp_headers.get("last-modified"),
            )
    except HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        if status == 304:
            return FetchBytesResult(status=304, body=b"", etag=etag, last_modified=last_modified)
        raise


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strip_html_to_text(s: str) -> str:
    return strip_markup_to_text(s)


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _first(*vals: str) -> str:
    for v in vals:
        v = (v or "").strip()
        if v:
            return v
    return ""


def _parse_feed_xml(feed_url: str, raw: bytes, *, limit: int) -> tuple[str, str | None, list[dict[str, Any]]]:
    txt = raw.decode("utf-8", errors="replace")
    root = ET.fromstring(txt)

    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}

    # RSS <channel><item>...
    channel = root.find("channel")
    if channel is not None:
        title = _text(channel.find("title")) or None
        items: list[dict[str, Any]] = []
        for it in channel.findall("item")[:limit]:
            link = _text(it.find("link"))
            guid = _text(it.find("guid"))
            creator = _text(it.find("dc:creator", ns))
            author = _text(it.find("author"))
            pub = _text(it.find("pubDate"))
            desc = _text(it.find("description"))
            content = _text(it.find("{http://purl.org/rss/1.0/modules/content/}encoded"))
            items.append(
                {
                    "external_id": _first(guid, link, _sha256_text((_text(it.find("title")) or "") + pub)),
                    "title": _text(it.find("title")) or None,
                    "url": _first(link, guid) or None,
                    "author": _first(creator, author) or None,
                    "published": pub or None,
                    "summary": (desc or "")[:500] or None,
                    "content_html": content or desc or None,
                }
            )
        return "rss", title, items

    # Atom <entry>...
    feed_title = _text(root.find("atom:title", ns)) or None
    items = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        link = ""
        for l in entry.findall("atom:link", ns):
            rel = (l.attrib.get("rel") or "alternate").strip().lower()
            href = (l.attrib.get("href") or "").strip()
            if rel == "alternate" and href:
                link = href
                break
        eid = _text(entry.find("atom:id", ns))
        title = _text(entry.find("atom:title", ns)) or None
        pub = _text(entry.find("atom:published", ns)) or _text(entry.find("atom:updated", ns))
        author = _text(entry.find("atom:author/atom:name", ns)) or None
        summary = _text(entry.find("atom:summary", ns)) or None
        content = _text(entry.find("atom:content", ns)) or None
        items.append(
            {
                "external_id": _first(eid, link, _sha256_text((title or "") + (pub or ""))),
                "title": title,
                "url": link or None,
                "author": author,
                "published": pub or None,
                "summary": (summary or "")[:500] or None,
                "content_html": content or summary or None,
            }
        )
    return "atom", feed_title, items


def _get_or_create_nws_source(db: Session) -> tuple[Source, SourceEndpoint]:
    src = db.query(Source).filter(Source.name == "National Weather Service").one_or_none()
    if not src:
        src = Source(
            name="National Weather Service",
            homepage_url="https://www.weather.gov/",
            tier=SourceTier.T1_AUTH,
            kind=ItemKind.JSON_API,
            default_language="en",
            trust_notes="Authoritative weather warnings/advisories.",
            enabled=True,
        )
        db.add(src)
        db.flush()

    ep = (
        db.query(SourceEndpoint)
        .filter(SourceEndpoint.source_id == src.id, SourceEndpoint.kind == EndpointKind.JSON_API)
        .one_or_none()
    )
    if not ep:
        ep = SourceEndpoint(
            source_id=src.id,
            kind=EndpointKind.JSON_API,
            url="https://api.weather.gov/alerts/active?point={lat},{lon}",
            poll_interval_seconds=300,
            enabled=True,
        )
        db.add(ep)
        db.flush()

    return src, ep


def ingest_nws_alerts(db: Session, *, point: str, scope_ref: str) -> IngestResult:
    src, ep = _get_or_create_nws_source(db)
    url = f"https://api.weather.gov/alerts/active?point={point}"
    data = _fetch_json(url)
    features = data.get("features") or []

    now = datetime.now(timezone.utc)
    inserted = 0
    updated = 0

    for f in features:
        props = (f or {}).get("properties") or {}
        trigger_url = (f or {}).get("id") or props.get("@id") or ""
        if not trigger_url:
            continue

        external_id = trigger_url
        title = (props.get("headline") or props.get("event") or "Weather alert").strip()
        severity = _map_nws_severity(props.get("severity"))

        body_parts: list[str] = []
        if props.get("description"):
            body_parts.append(str(props["description"]).strip())
        if props.get("instruction"):
            body_parts.append(str(props["instruction"]).strip())
        body = "\n\n".join([p for p in body_parts if p])[:4000] or title

        expires_at = _parse_dt(props.get("expires")) or _parse_dt(props.get("ends"))

        item = (
            db.query(Item)
            .filter(Item.endpoint_id == ep.id, Item.external_id == external_id)
            .one_or_none()
        )
        if item:
            item.updated_at = _parse_dt(props.get("sent")) or now
            item.title = title
            item.author = None
            item.canonical_url = trigger_url
            item.summary = (props.get("description") or "")[:500] or None
            item.content_text = body
            item.raw_json = props
            item.hash_content = _sha256_text(body)
        else:
            db.add(
                Item(
                    source_id=src.id,
                    endpoint_id=ep.id,
                    external_id=external_id,
                    published_at=_parse_dt(props.get("effective")) or _parse_dt(props.get("sent")),
                    updated_at=_parse_dt(props.get("sent")),
                    title=title,
                    author=None,
                    canonical_url=trigger_url,
                    summary=(props.get("description") or "")[:500] or None,
                    content_text=body,
                    raw_json=props,
                    hash_content=_sha256_text(body),
                )
            )

        existing = db.query(Alert).filter(Alert.trigger_url == trigger_url).one_or_none()
        if existing:
            existing.severity = severity
            existing.title = title
            existing.body = body
            existing.scope_kind = ScopeKind.REGION
            existing.scope_ref = scope_ref
            existing.language_profile = severity
            existing.updated_at = now
            existing.expires_at = expires_at
            updated += 1
        else:
            db.add(
                Alert(
                    severity=severity,
                    title=title,
                    body=body,
                    scope_kind=ScopeKind.REGION,
                    scope_ref=scope_ref,
                    trigger_url=trigger_url,
                    language_profile=severity,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                )
            )
            inserted += 1

    return IngestResult(inserted=inserted, updated=updated)


def ingest_rss_atom(db: Session, *, max_items_per_feed: int = 25) -> dict[str, IngestResult]:
    deny_urls = _load_denylist_urls()
    results: dict[str, IngestResult] = {}
    endpoints = (
        db.query(SourceEndpoint)
        .join(Source, Source.id == SourceEndpoint.source_id)
        .filter(SourceEndpoint.enabled.is_(True))
        .filter(Source.enabled.is_(True))
        .filter(SourceEndpoint.kind.in_([EndpointKind.RSS, EndpointKind.ATOM]))
        .order_by(Source.name.asc(), SourceEndpoint.url.asc())
        .all()
    )

    for ep in endpoints:
        src = ep.source
        accept = "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*"

        inserted = 0
        updated = 0
        try:
            fetched = _fetch_bytes(ep.url, accept=accept, etag=ep.http_etag, last_modified=ep.http_last_modified)
        except Exception as e:
            results[src.name] = IngestResult(inserted=0, updated=0)
            db.add(IngestionMetric(metric="feed_fetch_error", value=1.0, tags={"source": src.name, "url": ep.url, "error": str(e)[:200]}))
            continue

        if fetched.etag and fetched.etag != ep.http_etag:
            ep.http_etag = fetched.etag
        if fetched.last_modified and fetched.last_modified != ep.http_last_modified:
            ep.http_last_modified = fetched.last_modified

        if fetched.status == 304 or not fetched.body:
            results[src.name] = IngestResult(inserted=0, updated=0)
            continue

        try:
            _, feed_title, items = _parse_feed_xml(ep.url, fetched.body, limit=max_items_per_feed)
        except Exception as e:
            results[src.name] = IngestResult(inserted=0, updated=0)
            db.add(IngestionMetric(metric="feed_parse_error", value=1.0, tags={"source": src.name, "url": ep.url, "error": str(e)[:200]}))
            continue

        now = datetime.now(timezone.utc)
        for it in items:
            external_id = (it.get("external_id") or "").strip()
            if not external_id:
                continue
            title = _strip_html_to_text((it.get("title") or "").strip()) or None
            url = (it.get("url") or "").strip() or None
            if url and _normalize_url(url) in deny_urls:
                continue
            author = _strip_html_to_text((it.get("author") or "").strip()) or None
            published_at = _parse_dt_any(it.get("published"))
            summary_html = (it.get("summary") or "").strip() or ""
            content_html = (it.get("content_html") or "").strip() or ""
            summary = _strip_html_to_text(summary_html) or None
            content_text = _strip_html_to_text(content_html) or summary

            raw_json = {"feed_title": feed_title, "endpoint": ep.url}

            existing = db.query(Item).filter(Item.endpoint_id == ep.id, Item.external_id == external_id).one_or_none()
            hash_content = _sha256_text("\n".join([title or "", summary or "", content_html or ""]))
            if existing:
                changed = False
                for attr, value in {
                    "updated_at": now,
                    "title": title,
                    "author": author,
                    "canonical_url": url,
                    "summary": summary,
                    "content_text": content_text,
                    "content_html": content_html or None,
                    "raw_json": raw_json,
                    "hash_content": hash_content,
                    "published_at": published_at,
                }.items():
                    if getattr(existing, attr) != value and value is not None:
                        setattr(existing, attr, value)
                        changed = True
                if changed:
                    updated += 1
            else:
                db.add(
                    Item(
                        source_id=src.id,
                        endpoint_id=ep.id,
                        external_id=external_id,
                        published_at=published_at,
                        updated_at=now,
                        title=title,
                        author=author,
                        canonical_url=url,
                        summary=summary,
                        content_text=content_text,
                        content_html=content_html or None,
                        raw_json=raw_json,
                        hash_content=hash_content,
                    )
                )
                inserted += 1

        results[src.name] = IngestResult(inserted=inserted, updated=updated)
        db.add(IngestionMetric(metric="feed_items_inserted", value=float(inserted), tags={"source": src.name}))
        db.add(IngestionMetric(metric="feed_items_updated", value=float(updated), tags={"source": src.name}))

        # Be polite even server-side: small jitter between endpoints.
        time.sleep(random.uniform(1.0, 3.0))

    return results


def ingest() -> None:
    # Default point: Minneapolis (downtown). This can be overridden later with config tables.
    point = os.environ.get("MSPMETRO_NWS_POINT", "44.9778,-93.2650")
    scope_ref = os.environ.get("MSPMETRO_SCOPE_REF", "twin-cities")
    max_items = int(os.environ.get("MSPMETRO_FEED_MAX_ITEMS", "25"))

    started = datetime.now(timezone.utc)
    try:
        with session() as db:
            run = IngestionRun(started_at=started, status="running", details={"point": point, "scope_ref": scope_ref})
            db.add(run)
            db.flush()

            res = ingest_nws_alerts(db, point=point, scope_ref=scope_ref)
            feed_res = ingest_rss_atom(db, max_items_per_feed=max_items)

            db.add(IngestionMetric(metric="nws_alerts_inserted", value=float(res.inserted), tags={"scope_ref": scope_ref}))
            db.add(IngestionMetric(metric="nws_alerts_updated", value=float(res.updated), tags={"scope_ref": scope_ref}))

            run.finished_at = datetime.now(timezone.utc)
            run.status = "ok"
            run.details = {
                **(run.details or {}),
                "nws_inserted": res.inserted,
                "nws_updated": res.updated,
                "feeds": {k: {"inserted": v.inserted, "updated": v.updated} for k, v in feed_res.items()},
            }

            db.commit()
        total_feed_ins = sum(v.inserted for v in feed_res.values())
        total_feed_upd = sum(v.updated for v in feed_res.values())
        print(f"ingest: nws_alerts inserted={res.inserted} updated={res.updated}; feeds inserted={total_feed_ins} updated={total_feed_upd}")
    except Exception as e:
        try:
            with session() as db:
                run = IngestionRun(started_at=started, status="error", details={"error": str(e)})
                db.add(run)
                db.commit()
        except Exception:
            pass
        print(f"ingest: WARN: {e}", flush=True)
