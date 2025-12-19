from __future__ import annotations

import argparse
from pathlib import Path

from .seed import seed
from .ingest import ingest
from .db import session
from .source_config import sync_sources_from_toml


def main() -> None:
    parser = argparse.ArgumentParser(prog="mspmetro-backend")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="Insert sample data into the database")
    sub.add_parser("ingest", help="Collect external data and update the database")
    p_sync = sub.add_parser("sync-sources", help="Sync configured sources/endpoints into the database")
    p_sync.add_argument("--file", default="backend/config/sources.toml", help="Path to sources.toml")

    args = parser.parse_args()
    if args.cmd == "seed":
        seed()
    if args.cmd == "ingest":
        ingest()
    if args.cmd == "sync-sources":
        cfg = Path(args.file).resolve()
        with session() as db:
            res = sync_sources_from_toml(db, cfg)
            db.commit()
        print(
            "sync-sources:",
            f"sources created={res.sources_created} updated={res.sources_updated}",
            f"endpoints created={res.endpoints_created} updated={res.endpoints_updated}",
        )
