from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import strawberry
from strawberry.types import Info

from .db import session
from .models import Event, IngestionMetric, Item, Source, Topic


@strawberry.type
class Article:
    id: strawberry.ID
    title: Optional[str]
    url: Optional[str]
    author: Optional[str]
    published_at: Optional[datetime]
    source_name: Optional[str]


@strawberry.type
class TopicType:
    id: strawberry.ID
    name: str
    slug: str

    @strawberry.field
    def articles(self, info: Info, limit: int = 25) -> list[Article]:
        with session() as db:
            topic = db.query(Topic).filter(Topic.id == self.id).one()
            # Join via association table name to keep it simple.
            rows = (
                db.execute(
                    """
                    select i.id, i.title, i.canonical_url, i.author, i.published_at, s.name as source_name
                    from item_topics it
                    join items i on i.id = it.item_id
                    left join sources s on s.id = i.source_id
                    where it.topic_id = :tid
                    order by i.published_at desc nulls last, i.ingested_at desc
                    limit :lim
                    """,
                    {"tid": str(topic.id), "lim": limit},
                )
                .mappings()
                .all()
            )
            return [
                Article(
                    id=str(r["id"]),
                    title=r.get("title"),
                    url=r.get("canonical_url"),
                    author=r.get("author"),
                    published_at=r.get("published_at"),
                    source_name=r.get("source_name"),
                )
                for r in rows
            ]


@strawberry.type
class EventType:
    id: strawberry.ID
    name: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    location: Optional[str]
    url: Optional[str]

    @strawberry.field
    def articles(self, info: Info, limit: int = 25) -> list[Article]:
        with session() as db:
            rows = (
                db.execute(
                    """
                    select i.id, i.title, i.canonical_url, i.author, i.published_at, s.name as source_name
                    from event_items ei
                    join items i on i.id = ei.item_id
                    left join sources s on s.id = i.source_id
                    where ei.event_id = :eid
                    order by i.published_at desc nulls last, i.ingested_at desc
                    limit :lim
                    """,
                    {"eid": str(self.id), "lim": limit},
                )
                .mappings()
                .all()
            )
            return [
                Article(
                    id=str(r["id"]),
                    title=r.get("title"),
                    url=r.get("canonical_url"),
                    author=r.get("author"),
                    published_at=r.get("published_at"),
                    source_name=r.get("source_name"),
                )
                for r in rows
            ]


@strawberry.type
class MetricPoint:
    recorded_at: datetime
    metric: str
    value: float
    tags: strawberry.scalars.JSON


@strawberry.type
class Query:
    @strawberry.field
    def sources(self, info: Info) -> list[str]:
        with session() as db:
            return [s.name for s in db.query(Source).order_by(Source.name.asc()).all()]

    @strawberry.field
    def articles(self, info: Info, limit: int = 50) -> list[Article]:
        with session() as db:
            rows = (
                db.query(Item, Source)
                .join(Source, Source.id == Item.source_id)
                .order_by(Item.published_at.desc().nullslast(), Item.ingested_at.desc())
                .limit(limit)
                .all()
            )
            out: list[Article] = []
            for item, src in rows:
                out.append(
                    Article(
                        id=str(item.id),
                        title=item.title,
                        url=item.canonical_url,
                        author=item.author,
                        published_at=item.published_at,
                        source_name=src.name if src else None,
                    )
                )
            return out

    @strawberry.field
    def topics(self, info: Info, limit: int = 200) -> list[TopicType]:
        with session() as db:
            rows = db.query(Topic).order_by(Topic.name.asc()).limit(limit).all()
            return [TopicType(id=str(t.id), name=t.name, slug=t.slug) for t in rows]

    @strawberry.field
    def events(self, info: Info, limit: int = 200) -> list[EventType]:
        with session() as db:
            rows = db.query(Event).order_by(Event.starts_at.desc().nullslast(), Event.created_at.desc()).limit(limit).all()
            return [
                EventType(
                    id=str(e.id),
                    name=e.name,
                    starts_at=e.starts_at,
                    ends_at=e.ends_at,
                    location=e.location,
                    url=e.url,
                )
                for e in rows
            ]

    @strawberry.field
    def metrics(self, info: Info, metric: str, limit: int = 200) -> list[MetricPoint]:
        with session() as db:
            rows = (
                db.query(IngestionMetric)
                .filter(IngestionMetric.metric == metric)
                .order_by(IngestionMetric.recorded_at.desc())
                .limit(limit)
                .all()
            )
            return [MetricPoint(recorded_at=r.recorded_at, metric=r.metric, value=r.value, tags=r.tags) for r in rows]


schema = strawberry.Schema(query=Query)

