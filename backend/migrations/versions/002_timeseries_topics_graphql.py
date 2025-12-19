"""timeseries + triggers + topic/event scaffolding

Revision ID: 002_timeseries_topics_graphql
Revises: 001_init
Create Date: 2025-12-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_timeseries_topics_graphql"
down_revision = "001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Time-series style metrics (pure Postgres): use a BRIN index on time.
    op.create_table(
        "ingestion_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_ingestion_metrics_metric", "ingestion_metrics", ["metric"])
    op.execute("create index if not exists brin_ingestion_metrics_recorded_at on ingestion_metrics using brin (recorded_at);")

    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])

    # Extend items with optional author (for downstream grouping and display).
    op.add_column("items", sa.Column("author", sa.Text()))

    # Topic/event scaffolding for grouping.
    op.create_table(
        "topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_topics_slug"),
    )
    op.create_table(
        "item_topics",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_item_topics_topic_id", "item_topics", ["topic_id"])

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("location", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_events_starts_at", "events", ["starts_at"])

    op.create_table(
        "event_items",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_event_items_event_id", "event_items", ["event_id"])

    # PL/pgSQL trigger: always update updated_at on row updates.
    op.execute(
        """
create or replace function mspmetro_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
"""
    )
    op.execute(
        """
drop trigger if exists trg_alerts_set_updated_at on alerts;
create trigger trg_alerts_set_updated_at
before update on alerts
for each row
execute function mspmetro_set_updated_at();
"""
    )
    op.execute(
        """
drop trigger if exists trg_events_set_updated_at on events;
create trigger trg_events_set_updated_at
before update on events
for each row
execute function mspmetro_set_updated_at();
"""
    )


def downgrade() -> None:
    op.execute("drop trigger if exists trg_events_set_updated_at on events;")
    op.execute("drop trigger if exists trg_alerts_set_updated_at on alerts;")
    op.execute("drop function if exists mspmetro_set_updated_at;")

    op.drop_table("event_items")
    op.drop_table("events")
    op.drop_index("ix_item_topics_topic_id", table_name="item_topics")
    op.drop_table("item_topics")
    op.drop_table("topics")

    op.drop_column("items", "author")

    op.drop_index("ix_ingestion_runs_started_at", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")

    op.execute("drop index if exists brin_ingestion_metrics_recorded_at;")
    op.drop_index("ix_ingestion_metrics_metric", table_name="ingestion_metrics")
    op.drop_table("ingestion_metrics")

