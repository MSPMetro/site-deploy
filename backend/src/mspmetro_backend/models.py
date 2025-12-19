from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceTier(str, enum.Enum):
    T1_AUTH = "T1_AUTH"
    T2_INST = "T2_INST"
    T3_COMM = "T3_COMM"
    T4_OBS = "T4_OBS"


class ItemKind(str, enum.Enum):
    RSS = "RSS"
    ATOM = "ATOM"
    JSON_API = "JSON_API"
    HTML_SCRAPE = "HTML_SCRAPE"
    MANUAL = "MANUAL"


class StoryType(str, enum.Enum):
    STATUS = "STATUS"
    DECISION = "DECISION"
    INCIDENT = "INCIDENT"
    ADVISORY = "ADVISORY"
    SCHEDULE = "SCHEDULE"
    UPDATE = "UPDATE"


class AlertSeverity(str, enum.Enum):
    INFO = "INFO"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    EMERGENCY = "EMERGENCY"


class LifecycleState(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"


class ScopeKind(str, enum.Enum):
    REGION = "REGION"
    COUNTY = "COUNTY"
    NEIGHBORHOOD = "NEIGHBORHOOD"
    CITY = "CITY"
    CUSTOM = "CUSTOM"


class EndpointKind(str, enum.Enum):
    RSS = "RSS"
    ATOM = "ATOM"
    JSON_API = "JSON_API"
    HTML_SCRAPE = "HTML_SCRAPE"


class AuthType(str, enum.Enum):
    none = "none"
    api_key = "api_key"
    bearer = "bearer"
    basic = "basic"


class StoryUpdateKind(str, enum.Enum):
    UPDATE = "UPDATE"
    CORRECTION = "CORRECTION"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    homepage_url: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[SourceTier] = mapped_column(Enum(SourceTier, name="source_tier"), nullable=False)
    kind: Mapped[ItemKind] = mapped_column(Enum(ItemKind, name="item_kind"), nullable=False)
    default_language: Mapped[str | None] = mapped_column(Text)
    trust_notes: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SourceEndpoint(Base):
    __tablename__ = "source_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"))
    kind: Mapped[EndpointKind] = mapped_column(Enum(EndpointKind, name="endpoint_kind"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    http_etag: Mapped[str | None] = mapped_column(Text)
    http_last_modified: Mapped[str | None] = mapped_column(Text)
    auth_type: Mapped[AuthType] = mapped_column(Enum(AuthType, name="auth_type"), nullable=False, default=AuthType.none)
    auth_ref: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    source: Mapped[Source] = relationship()


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("endpoint_id", "external_id", name="uq_items_endpoint_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_endpoints.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    raw_html: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    hash_content: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped[Source] = relationship()
    endpoint: Mapped[SourceEndpoint] = relationship()


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_type: Mapped[StoryType] = mapped_column(Enum(StoryType, name="story_type"), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    dek: Mapped[str | None] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status_line: Mapped[str | None] = mapped_column(Text)
    affects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scope_kind: Mapped[ScopeKind] = mapped_column(Enum(ScopeKind, name="scope_kind"), nullable=False)
    scope_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_tier_max: Mapped[SourceTier | None] = mapped_column(Enum(SourceTier, name="source_tier"))
    verification_label: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lifecycle_state: Mapped[LifecycleState] = mapped_column(
        Enum(LifecycleState, name="lifecycle_state"), nullable=False, default=LifecycleState.DRAFT
    )


class StoryLink(Base):
    __tablename__ = "story_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[SourceTier | None] = mapped_column(Enum(SourceTier, name="source_tier"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class StoryItemMap(Base):
    __tablename__ = "story_item_map"
    __table_args__ = (CheckConstraint("relationship in ('PRIMARY','SUPPORTING')", name="ck_story_item_map_relationship"),)

    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    relationship: Mapped[str] = mapped_column(Text, nullable=False)


class StoryUpdate(Base):
    __tablename__ = "story_updates"
    __table_args__ = (
        CheckConstraint("kind <> 'UPDATE' OR what_changed IS NOT NULL", name="ck_story_updates_update_requires_what_changed"),
        CheckConstraint("kind <> 'CORRECTION' OR correction_text IS NOT NULL", name="ck_story_updates_correction_requires_text"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"))
    kind: Mapped[StoryUpdateKind] = mapped_column(Enum(StoryUpdateKind, name="story_update_kind"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    what_changed: Mapped[str | None] = mapped_column(Text)
    correction_text: Mapped[str | None] = mapped_column(Text)
    previous_hash: Mapped[str | None] = mapped_column(Text)
    new_hash: Mapped[str | None] = mapped_column(Text)
    snapshot_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity, name="alert_severity"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[ScopeKind] = mapped_column(Enum(ScopeKind, name="scope_kind"), nullable=False)
    scope_ref: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"))
    trigger_url: Mapped[str | None] = mapped_column(Text)
    language_profile: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity, name="alert_severity"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Brief(Base):
    __tablename__ = "briefs"
    __table_args__ = (
        UniqueConstraint("date", "section", "scope_kind", "scope_ref", name="uq_briefs"),
        CheckConstraint("section in ('WEATHER','METRO','WORLD','NEIGHBORS','TRANSIT','EVENTS')", name="ck_briefs_section"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[ScopeKind] = mapped_column(Enum(ScopeKind, name="scope_kind"), nullable=False)
    scope_ref: Mapped[str] = mapped_column(Text, nullable=False)
    bullets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    immutable_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SnapshotStoryMap(Base):
    __tablename__ = "snapshot_story_map"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    story_version_hash: Mapped[str] = mapped_column(Text, nullable=False)


class IngestionMetric(Base):
    __tablename__ = "ingestion_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("slug", name="uq_topics_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ItemTopic(Base):
    __tablename__ = "item_topics"

    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class EventItem(Base):
    __tablename__ = "event_items"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
