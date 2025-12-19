from __future__ import annotations

from flask import Flask, jsonify, request
from dotenv import load_dotenv

from .db import session
from .models import Alert, AlertSeverity

try:
    from strawberry.flask.views import GraphQLView

    from .graphql_api import schema
except Exception:  # pragma: no cover
    GraphQLView = None
    schema = None


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.get("/api/v1/frontpage")
    def api_frontpage():
        # Read-only consumer contract: always return something stable.
        # If DB is empty, UI can still render placeholders.
        with session() as db:
            alerts = (
                db.query(Alert)
                .order_by(Alert.created_at.desc())
                .limit(5)
                .all()
            )

        return jsonify(
            {
                "orientation": {
                    "day": "WED",
                    "date": "2025-12-17",
                    "region": "MINNEAPOLIS–ST. PAUL",
                    "temp_f": 32,
                    "feels_like_f": 26,
                    "phrase": "Snow after 7pm",
                    "sunrise": "7:47am",
                    "sunset": "4:36pm",
                },
                "city_status": "Normal operations · No declared emergencies",
                "alerts": [
                    {
                        "severity": a.severity.value,
                        "title": a.title,
                        "body": a.body,
                        "scope_kind": a.scope_kind.value,
                        "scope_ref": a.scope_ref,
                        "trigger_url": a.trigger_url,
                        "language_profile": a.language_profile.value,
                    }
                    for a in alerts
                ],
                "defaults": {
                    "alert_severity_order": [
                        AlertSeverity.EMERGENCY.value,
                        AlertSeverity.WARNING.value,
                        AlertSeverity.ADVISORY.value,
                        AlertSeverity.INFO.value,
                    ]
                },
            }
        )

    @app.get("/api/v1/alerts")
    def api_alerts():
        limit = int(request.args.get("limit", "25"))
        with session() as db:
            alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
        return jsonify(
            [
                {
                    "severity": a.severity.value,
                    "title": a.title,
                    "body": a.body,
                    "scope_kind": a.scope_kind.value,
                    "scope_ref": a.scope_ref,
                    "trigger_url": a.trigger_url,
                    "language_profile": a.language_profile.value,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                }
                for a in alerts
            ]
        )

    if GraphQLView is not None and schema is not None:
        app.add_url_rule(
            "/api/graphql",
            view_func=GraphQLView.as_view("graphql", schema=schema, graphiql=False),
        )
        app.add_url_rule(
            "/api/v1/graphql",
            view_func=GraphQLView.as_view("graphql_v1", schema=schema, graphiql=False),
        )

    return app


app = create_app()
