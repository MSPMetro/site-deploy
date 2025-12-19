from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .db import session
from .models import Alert, AlertSeverity, ScopeKind, Source, SourceTier, ItemKind


def seed() -> None:
    now = datetime.now(timezone.utc)
    with session() as db:
        existing = db.scalar(select(Source).limit(1))
        if not existing:
            nws = Source(
                name="National Weather Service",
                homepage_url="https://www.weather.gov/",
                tier=SourceTier.T1_AUTH,
                kind=ItemKind.JSON_API,
                enabled=True,
            )
            metro_transit = Source(
                name="Metro Transit",
                homepage_url="https://www.metrotransit.org/",
                tier=SourceTier.T1_AUTH,
                kind=ItemKind.JSON_API,
                enabled=True,
            )
            db.add_all([nws, metro_transit])

        db.add(
            Alert(
                severity=AlertSeverity.ADVISORY,
                title="Winter weather advisory in effect after 7pm",
                body="Travel may be slower this evening; allow extra time.",
                scope_kind=ScopeKind.REGION,
                scope_ref="twin-cities",
                trigger_url="https://api.weather.gov/alerts",
                language_profile=AlertSeverity.ADVISORY,
                expires_at=now + timedelta(hours=12),
            )
        )
        db.add(
            Alert(
                severity=AlertSeverity.INFO,
                title="Minor transit delays possible this evening",
                body="Weather may reduce on-time performance during peak travel.",
                scope_kind=ScopeKind.REGION,
                scope_ref="twin-cities",
                trigger_url="https://www.metrotransit.org/",
                language_profile=AlertSeverity.INFO,
                expires_at=now + timedelta(hours=8),
            )
        )

        db.commit()

