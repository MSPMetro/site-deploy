"""init

Revision ID: 001_init
Revises:
Create Date: 2025-12-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create extension if not exists pgcrypto;")

    def pg_enum(name: str, *values: str) -> postgresql.ENUM:
        # Create once, then prevent table/column DDL from re-creating the same type
        # during `op.create_table(...)` (which uses `checkfirst=False`).
        create_enum = postgresql.ENUM(*values, name=name)
        create_enum.create(op.get_bind(), checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)

    source_tier = pg_enum("source_tier", "T1_AUTH", "T2_INST", "T3_COMM", "T4_OBS")
    item_kind = pg_enum("item_kind", "RSS", "ATOM", "JSON_API", "HTML_SCRAPE", "MANUAL")
    story_type = pg_enum("story_type", "STATUS", "DECISION", "INCIDENT", "ADVISORY", "SCHEDULE", "UPDATE")
    alert_severity = pg_enum("alert_severity", "INFO", "ADVISORY", "WARNING", "EMERGENCY")
    lifecycle_state = pg_enum("lifecycle_state", "DRAFT", "PUBLISHED", "EXPIRED", "ARCHIVED")
    scope_kind = pg_enum("scope_kind", "REGION", "COUNTY", "NEIGHBORHOOD", "CITY", "CUSTOM")
    endpoint_kind = pg_enum("endpoint_kind", "RSS", "ATOM", "JSON_API", "HTML_SCRAPE")
    auth_type = pg_enum("auth_type", "none", "api_key", "bearer", "basic")
    story_update_kind = pg_enum("story_update_kind", "UPDATE", "CORRECTION")

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("homepage_url", sa.Text()),
        sa.Column("tier", source_tier, nullable=False),
        sa.Column("kind", item_kind, nullable=False),
        sa.Column("default_language", sa.Text()),
        sa.Column("trust_notes", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "source_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", endpoint_kind, nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default=sa.text("900")),
        sa.Column("http_etag", sa.Text()),
        sa.Column("http_last_modified", sa.Text()),
        sa.Column("auth_type", auth_type, nullable=False, server_default=sa.text("'none'")),
        sa.Column("auth_ref", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("title", sa.Text()),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("content_text", sa.Text()),
        sa.Column("content_html", sa.Text()),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("raw_html", sa.Text()),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("hash_content", sa.Text(), nullable=False),
        sa.UniqueConstraint("endpoint_id", "external_id", name="uq_items_endpoint_external"),
    )

    op.create_table(
        "stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("story_type", story_type, nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("dek", sa.Text()),
        sa.Column("body_markdown", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status_line", sa.Text()),
        sa.Column("affects", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("scope_kind", scope_kind, nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("source_tier_max", source_tier),
        sa.Column("verification_label", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifecycle_state", lifecycle_state, nullable=False, server_default=sa.text("'DRAFT'")),
    )

    op.create_table(
        "story_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("label", sa.Text()),
        sa.Column("tier", source_tier),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "story_item_map",
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("relationship", sa.Text(), nullable=False),
    )
    op.create_check_constraint(
        "ck_story_item_map_relationship",
        "story_item_map",
        "relationship in ('PRIMARY','SUPPORTING')",
    )

    op.create_table(
        "story_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", story_update_kind, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("what_changed", sa.Text()),
        sa.Column("correction_text", sa.Text()),
        sa.Column("previous_hash", sa.Text()),
        sa.Column("new_hash", sa.Text()),
        sa.Column("snapshot_lock", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_check_constraint(
        "ck_story_updates_update_requires_what_changed",
        "story_updates",
        "kind <> 'UPDATE' OR what_changed IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_story_updates_correction_requires_text",
        "story_updates",
        "kind <> 'CORRECTION' OR correction_text IS NOT NULL",
    )

    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("scope_kind", scope_kind, nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("trigger_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("trigger_url", sa.Text()),
        sa.Column("language_profile", alert_severity, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("scope_kind", scope_kind, nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("bullets", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("date", "section", "scope_kind", "scope_ref", name="uq_briefs"),
    )
    op.create_check_constraint(
        "ck_briefs_section",
        "briefs",
        "section in ('WEATHER','METRO','WORLD','NEIGHBORS','TRANSIT','EVENTS')",
    )

    op.create_table(
        "snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False, unique=True),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("immutable_after", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "snapshot_story_map",
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "story_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("story_version_hash", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("snapshot_story_map")
    op.drop_table("snapshots")
    op.drop_constraint("ck_briefs_section", "briefs", type_="check")
    op.drop_table("briefs")
    op.drop_table("alerts")
    op.drop_constraint("ck_story_updates_correction_requires_text", "story_updates", type_="check")
    op.drop_constraint("ck_story_updates_update_requires_what_changed", "story_updates", type_="check")
    op.drop_table("story_updates")
    op.drop_constraint("ck_story_item_map_relationship", "story_item_map", type_="check")
    op.drop_table("story_item_map")
    op.drop_table("story_links")
    op.drop_table("stories")
    op.drop_table("items")
    op.drop_table("source_endpoints")
    op.drop_table("sources")

    op.execute("drop type if exists story_update_kind;")
    op.execute("drop type if exists auth_type;")
    op.execute("drop type if exists endpoint_kind;")
    op.execute("drop type if exists scope_kind;")
    op.execute("drop type if exists lifecycle_state;")
    op.execute("drop type if exists alert_severity;")
    op.execute("drop type if exists story_type;")
    op.execute("drop type if exists item_kind;")
    op.execute("drop type if exists source_tier;")
