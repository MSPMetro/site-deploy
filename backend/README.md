# MSPMetro Backend (Flask + SQLAlchemy)

This service owns:

- ingestion + normalization (future)
- alert generation + severity rules
- daily snapshots + archive immutability
- PostgreSQL as the single source of truth

The Rust/Dioxus UI is a **read-only consumer** of the backend API.

## Local run (dev)

Prereqs: Python 3.11+ and Postgres.

NO DOCKER: this repo does not ship a container runtime workflow.

```bash
cd ..
make db-up
```

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install -e .

export DATABASE_URL="postgresql+psycopg://mspmetro:mspmetro@127.0.0.1:5432/mspmetro"
./.venv/bin/alembic upgrade head
./.venv/bin/python -m mspmetro_backend seed
./.venv/bin/flask --app mspmetro_backend.app run
```

Health check:

- `http://127.0.0.1:5000/healthz`
- `http://127.0.0.1:5000/api/v1/frontpage`
