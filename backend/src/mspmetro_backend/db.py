from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import database_url

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
    return _engine


def session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _SessionLocal()
