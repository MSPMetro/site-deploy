-- Postgres-oriented schema draft for MSPMetro.
-- This repo currently serves static HTML, but the schema below is the intended foundation.

create extension if not exists pgcrypto;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'source_tier') then
    create type source_tier as enum ('T1_AUTH','T2_INST','T3_COMM','T4_OBS');
  end if;
  if not exists (select 1 from pg_type where typname = 'item_kind') then
    create type item_kind as enum ('RSS','ATOM','JSON_API','HTML_SCRAPE','MANUAL');
  end if;
  if not exists (select 1 from pg_type where typname = 'story_type') then
    create type story_type as enum ('STATUS','DECISION','INCIDENT','ADVISORY','SCHEDULE','UPDATE');
  end if;
  if not exists (select 1 from pg_type where typname = 'alert_severity') then
    create type alert_severity as enum ('INFO','ADVISORY','WARNING','EMERGENCY');
  end if;
  if not exists (select 1 from pg_type where typname = 'lifecycle_state') then
    create type lifecycle_state as enum ('DRAFT','PUBLISHED','EXPIRED','ARCHIVED');
  end if;
  if not exists (select 1 from pg_type where typname = 'scope_kind') then
    create type scope_kind as enum ('REGION','COUNTY','NEIGHBORHOOD','CITY','CUSTOM');
  end if;
  if not exists (select 1 from pg_type where typname = 'endpoint_kind') then
    create type endpoint_kind as enum ('RSS','ATOM','JSON_API','HTML_SCRAPE');
  end if;
  if not exists (select 1 from pg_type where typname = 'auth_type') then
    create type auth_type as enum ('none','api_key','bearer','basic');
  end if;
  if not exists (select 1 from pg_type where typname = 'story_update_kind') then
    create type story_update_kind as enum ('UPDATE','CORRECTION');
  end if;
end $$;

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  homepage_url text,
  tier source_tier not null,
  kind item_kind not null,
  default_language text,
  trust_notes text,
  enabled boolean not null default true
);

create table if not exists source_endpoints (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id) on delete cascade,
  kind endpoint_kind not null,
  url text not null,
  poll_interval_seconds integer not null default 900,
  http_etag text,
  http_last_modified text,
  auth_type auth_type not null default 'none',
  auth_ref text,
  enabled boolean not null default true
);

create table if not exists items (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id) on delete cascade,
  endpoint_id uuid not null references source_endpoints(id) on delete cascade,
  external_id text not null,
  published_at timestamptz,
  updated_at timestamptz,
  title text,
  canonical_url text,
  summary text,
  content_text text,
  content_html text,
  raw_json jsonb,
  raw_html text,
  ingested_at timestamptz not null default now(),
  hash_content text not null,
  unique (endpoint_id, external_id)
);

create table if not exists stories (
  id uuid primary key default gen_random_uuid(),
  story_type story_type not null,
  headline text not null,
  dek text,
  body_markdown text not null default '',
  status_line text,
  affects jsonb not null default '[]'::jsonb,
  scope_kind scope_kind not null,
  scope_ref text not null,
  source_tier_max source_tier,
  verification_label text,
  published_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null,
  lifecycle_state lifecycle_state not null default 'DRAFT'
);

create table if not exists story_links (
  id uuid primary key default gen_random_uuid(),
  story_id uuid not null references stories(id) on delete cascade,
  source_id uuid references sources(id) on delete set null,
  url text not null,
  label text,
  tier source_tier,
  created_at timestamptz not null default now()
);

create table if not exists story_item_map (
  story_id uuid not null references stories(id) on delete cascade,
  item_id uuid not null references items(id) on delete cascade,
  relationship text not null check (relationship in ('PRIMARY','SUPPORTING')),
  primary key (story_id, item_id)
);

create table if not exists story_updates (
  id uuid primary key default gen_random_uuid(),
  story_id uuid not null references stories(id) on delete cascade,
  kind story_update_kind not null,
  created_at timestamptz not null default now(),
  what_changed text,
  correction_text text,
  previous_hash text,
  new_hash text,
  snapshot_lock boolean not null default false,
  constraint story_updates_update_requires_what_changed
    check (kind <> 'UPDATE' or what_changed is not null),
  constraint story_updates_correction_requires_text
    check (kind <> 'CORRECTION' or correction_text is not null)
);

create table if not exists alerts (
  id uuid primary key default gen_random_uuid(),
  severity alert_severity not null,
  title text not null,
  body text not null,
  scope_kind scope_kind not null,
  scope_ref text not null,
  trigger_source_id uuid references sources(id) on delete set null,
  trigger_url text,
  language_profile alert_severity not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists briefs (
  id uuid primary key default gen_random_uuid(),
  date date not null,
  section text not null check (section in ('WEATHER','METRO','WORLD','NEIGHBORS','TRANSIT','EVENTS')),
  scope_kind scope_kind not null,
  scope_ref text not null,
  bullets jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(),
  unique (date, section, scope_kind, scope_ref)
);

create table if not exists snapshots (
  id uuid primary key default gen_random_uuid(),
  date date not null unique,
  cutoff_at timestamptz not null,
  created_at timestamptz not null default now(),
  immutable_after timestamptz not null
);

create table if not exists snapshot_story_map (
  snapshot_id uuid not null references snapshots(id) on delete cascade,
  story_id uuid not null references stories(id) on delete cascade,
  story_version_hash text not null,
  primary key (snapshot_id, story_id)
);

