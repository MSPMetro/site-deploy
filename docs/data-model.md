# MSPMetro Data Model (Draft)

This repo currently serves static HTML/CSS pages. This document defines the **backend/editorial object model** to power those pages while enforcing:

- story lifecycle rules (update vs correction, expiration)
- alert severity + language constraints
- daily snapshots that do not retroactively change
- source tier labeling and corroboration guardrails

## Canonical entities

- **Source**: who/where information comes from (tiered)
- **Endpoint**: how we poll a source (RSS/JSON/scrape)
- **Item**: raw ingested record (traceable, deduped)
- **Story**: editorial unit (what the user reads)
- **StoryUpdate**: update/correction ledger entry
- **Alert**: severity + proof link + language profile
- **Brief**: per-section bullets for a date/scope
- **Snapshot**: immutable daily archive + story-version map
- **GeoScope**: region/county/neighborhood applicability

## Hard enums (no free-form strings)

- `SourceTier`: `T1_AUTH`, `T2_INST`, `T3_COMM`, `T4_OBS`
- `StoryType`: `STATUS`, `DECISION`, `INCIDENT`, `ADVISORY`, `SCHEDULE`, `UPDATE`
- `AlertSeverity`: `INFO`, `ADVISORY`, `WARNING`, `EMERGENCY`
- `ItemKind`: `RSS`, `ATOM`, `JSON_API`, `HTML_SCRAPE`, `MANUAL`
- `LifecycleState`: `DRAFT`, `PUBLISHED`, `EXPIRED`, `ARCHIVED`
- `ScopeKind`: `REGION`, `COUNTY`, `NEIGHBORHOOD`, `CITY`, `CUSTOM`

## Non-negotiables encoded by the model

- **Every story** has: scope, sources, `updated_at`, `expires_at`, `story_type`, `lifecycle_state`.
- **Updates** require `what_changed` (material changes only).
- **Corrections** are appended ledger entries; never overwrite/delete the original fact pattern.
- **Tier 4** content is label-required and must never generate alerts.
- **Daily snapshots** preserve story text as-of cutoff; later corrections become annotations.

See `migrations/001_init.sql` for a Postgres-oriented schema draft.

