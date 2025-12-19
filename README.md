# MSPMetro

This repo contains:

- Static HTML/CSS pages (current UI reference)
- A Python backend (Flask + SQLAlchemy) for ingestion/alerts/snapshots (in progress)
- A Rust UI server (Dioxus SSR) as a read-only consumer (in progress)

## Static pages (reference UI)

The static “daily briefing” front page is `index.html` (summary + wayfinding), with depth under:

- `weather/`
- `metro/`
- `world/`
- `neighbors/`
- `transit/`
- `events/`

## Local preview

### Static preview

```bash
make run-static
```

If port `8000` is in use, the script automatically picks the next available port.

Optional:

```bash
PORT=8010 make run-static
BIND=0.0.0.0 make run-static
```

## GitHub Pages (static)

This repo includes a GitHub Actions workflow that deploys `build/site/` to GitHub Pages on pushes to `main`.

Enable it in GitHub:

- Settings → Pages → Build and deployment → Source: GitHub Actions

### Backend + UI (work-in-progress)

Backend (requires Postgres + `DATABASE_URL`):

```bash
make db-up
make setup-backend
make migrate-backend
make seed-backend
make run-backend
```

UI (reads from `BACKEND_ORIGIN`, default `http://127.0.0.1:5000`):

```bash
make run
```

Notes:

- On a remote server, keep the backend bound to `127.0.0.1:5000` and reverse-proxy the UI with Nginx/Caddy, or set `UI_BIND=0.0.0.0:8080` for direct port access.
- If you deploy the `mspmetro-ui` binary without the repo checkout, set `UI_STATIC_DIR` to a directory containing `static/` so CSS loads.

## Production publishing (S3-compatible)

Today, the edge deployment uses a manifest/object publisher + puller (see `DEPLOY.md`).

Optional next step: **single-write** MinIO publisher with **fanout replication** to multiple S3 providers:

- Docs: `ops/minio/README.md:1`
- Install MinIO on a publisher host: `PUBLISHER_HOST=... make minio-publisher`
- Configure continuous fanout replication: `PUBLISHER_HOST=... make minio-replication`
