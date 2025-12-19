from __future__ import annotations

import os


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required (e.g. postgresql+psycopg://...)")
    return url


def bind_host() -> str:
    return os.environ.get("BIND", "127.0.0.1")


def bind_port() -> int:
    return int(os.environ.get("PORT", "5000"))

