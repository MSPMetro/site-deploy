from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from .models import (
    AuthType,
    EndpointKind,
    ItemKind,
    Source,
    SourceEndpoint,
    SourceTier,
)


@dataclass(frozen=True)
class SyncResult:
    sources_created: int
    sources_updated: int
    endpoints_created: int
    endpoints_updated: int


def _parse_enum(enum_cls, value: str, *, field: str):
    try:
        return enum_cls(value)
    except Exception as e:
        raise ValueError(f"invalid {field}: {value!r} (expected one of {[v.value for v in enum_cls]})") from e


def sync_sources_from_toml(db: Session, path: Path) -> SyncResult:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = raw.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")

    sources_created = 0
    sources_updated = 0
    endpoints_created = 0
    endpoints_updated = 0

    for s in sources:
        if not isinstance(s, dict):
            raise ValueError("each sources[] entry must be a table/dict")

        name = (s.get("name") or "").strip()
        if not name:
            raise ValueError("source.name is required")

        homepage_url = (s.get("homepage_url") or "").strip() or None
        default_language = (s.get("default_language") or "").strip() or None
        trust_notes = (s.get("trust_notes") or "").strip() or None
        enabled = bool(s.get("enabled", True))

        tier = _parse_enum(SourceTier, s.get("tier") or "", field=f"source[{name}].tier")
        kind = _parse_enum(ItemKind, s.get("kind") or "", field=f"source[{name}].kind")

        src = db.query(Source).filter(Source.name == name).one_or_none()
        if not src:
            src = Source(
                name=name,
                homepage_url=homepage_url,
                tier=tier,
                kind=kind,
                default_language=default_language,
                trust_notes=trust_notes,
                enabled=enabled,
            )
            db.add(src)
            db.flush()
            sources_created += 1
        else:
            changed = False
            for attr, value in {
                "homepage_url": homepage_url,
                "tier": tier,
                "kind": kind,
                "default_language": default_language,
                "trust_notes": trust_notes,
                "enabled": enabled,
            }.items():
                if getattr(src, attr) != value:
                    setattr(src, attr, value)
                    changed = True
            if changed:
                sources_updated += 1

        endpoints = s.get("endpoints") or []
        if not isinstance(endpoints, list):
            raise ValueError(f"source[{name}].endpoints must be a list")

        for e in endpoints:
            if not isinstance(e, dict):
                raise ValueError(f"source[{name}].endpoints[] must be a table/dict")
            ekind = _parse_enum(EndpointKind, e.get("kind") or "", field=f"source[{name}].endpoints.kind")
            url = (e.get("url") or "").strip()
            if not url:
                raise ValueError(f"source[{name}].endpoints.url is required")
            poll = int(e.get("poll_interval_seconds") or 900)
            e_enabled = bool(e.get("enabled", True))
            auth_type = _parse_enum(AuthType, e.get("auth_type") or "none", field=f"source[{name}].endpoints.auth_type")
            auth_ref = (e.get("auth_ref") or "").strip() or None

            ep = (
                db.query(SourceEndpoint)
                .filter(
                    SourceEndpoint.source_id == src.id,
                    SourceEndpoint.kind == ekind,
                    SourceEndpoint.url == url,
                )
                .one_or_none()
            )
            if not ep:
                db.add(
                    SourceEndpoint(
                        source_id=src.id,
                        kind=ekind,
                        url=url,
                        poll_interval_seconds=poll,
                        auth_type=auth_type,
                        auth_ref=auth_ref,
                        enabled=e_enabled,
                    )
                )
                endpoints_created += 1
            else:
                changed = False
                for attr, value in {
                    "poll_interval_seconds": poll,
                    "auth_type": auth_type,
                    "auth_ref": auth_ref,
                    "enabled": e_enabled,
                }.items():
                    if getattr(ep, attr) != value:
                        setattr(ep, attr, value)
                        changed = True
                if changed:
                    endpoints_updated += 1

    return SyncResult(
        sources_created=sources_created,
        sources_updated=sources_updated,
        endpoints_created=endpoints_created,
        endpoints_updated=endpoints_updated,
    )

