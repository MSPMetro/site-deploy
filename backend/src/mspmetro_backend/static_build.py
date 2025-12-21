from __future__ import annotations

import argparse
import html
import json
import os
import re
import socket
import subprocess
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy import case

from .db import session
from .models import Alert, AlertSeverity, Item, Source
from .text_clean import strip_markup_to_text


CT_TZ = ZoneInfo("America/Chicago")
_DENY_URLS_CACHE: set[str] | None = None


def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    u = u.split("#", 1)[0].strip()
    if u.endswith("/"):
        u = u[:-1]
    return u


def _load_denylist_urls() -> set[str]:
    global _DENY_URLS_CACHE
    if _DENY_URLS_CACHE is not None:
        return _DENY_URLS_CACHE
    path = (os.environ.get("MSPMETRO_DENYLIST_URLS_FILE") or "backend/config/denylist_urls.txt").strip()
    denied: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                denied.add(_normalize_url(ln))
    except FileNotFoundError:
        denied = set()
    except Exception:
        denied = set()
    _DENY_URLS_CACHE = denied
    return denied


@dataclass(frozen=True)
class BuildMeta:
    host: str
    time_utc: str
    commit: str


def _git_short_sha() -> str:
    repo_root = Path(__file__).resolve().parents[4]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _build_metadata() -> BuildMeta:
    return BuildMeta(
        host=socket.gethostname(),
        time_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        commit=_git_short_sha(),
    )


def _write_health_file(*, out_dir: Path, build_meta: BuildMeta) -> None:
    payload = "\n".join(
        [
            f"build_time_utc={build_meta.time_utc}",
            f"build_commit={build_meta.commit}",
            f"build_host={build_meta.host}",
            'served_by=[[ env "HOSTNAME" ]]',
        ]
    )
    (out_dir / "health.txt").write_text(payload + "\n", encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_ct(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CT_TZ)


def _format_date_long(dt: datetime) -> str:
    d = _to_ct(dt)
    return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else d.date().isoformat()


def _day_full(dt: datetime) -> str:
    return _to_ct(dt).strftime("%A")


def _rel_time(dt: datetime | None, *, now: datetime) -> str:
    if not dt:
        return "Updated recently"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = max(int(delta.total_seconds()), 0)
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    if minutes < 2:
        return "Updated just now"
    if minutes < 60:
        return f"Updated {minutes} minutes ago"
    if hours < 24:
        return f"Updated {hours} hours ago"
    return f"Updated {days} days ago"


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "item"


def _escape(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _arrow_internal() -> str:
    return '<span class="arrow" aria-hidden="true">→</span>'


def _arrow_external() -> str:
    return '<span class="arrow" aria-hidden="true">↗</span><span class="sr-only"> (external site)</span>'


def _site_href(href: str, *, root_prefix: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("#"):
        return href
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
        return href
    return f"{root_prefix}{href.lstrip('/')}"


@dataclass(frozen=True)
class SectionDef:
    key: str
    label: str
    page_path: str
    source_names: tuple[str, ...]
    max_age_days: int | None = None


SECTIONS: tuple[SectionDef, ...] = (
    SectionDef("weather", "Weather", "/weather/", ("National Weather Service",)),
    SectionDef(
        "metro",
        "Metro",
        "/metro/",
        (
            "MPR News",
            "MinnPost",
            "Sahan Journal",
            "Minnesota Reformer",
            "Racket",
            "The UpTake",
            "The Spokesman-Recorder",
            "The Minnesota Daily",
        ),
    ),
    SectionDef("world", "World", "/world/", ()),
    SectionDef("neighbors", "Neighbors", "/neighbors/", ("Unicorn Riot",)),
    SectionDef("transit", "Transit", "/transit/", ("Streets.mn",)),
    SectionDef(
        "events",
        "Events",
        "/events/",
        (
            "Secret Minneapolis",
            "Twin Cities Family",
            "Twin Cities Frugal Mom",
            "Minnesota Monthly",
            "Artful Living",
            "Midwest Design",
            "PhenoMNal Twin Cities",
        ),
        max_age_days=30,
    ),
)


def _affects_from_title(title: str) -> list[str]:
    t = (title or "").lower()
    affects: list[str] = []
    if any(k in t for k in ["snow", "ice", "blizzard", "wind", "weather", "cold", "storm"]):
        affects.extend(["Commuters", "Drivers"])
    if any(k in t for k in ["bus", "train", "rail", "transit", "metro transit", "bike"]):
        affects.extend(["Riders", "Commuters"])
    if any(k in t for k in ["school", "student", "campus", "class"]):
        affects.extend(["Parents", "Students"])
    if any(k in t for k in ["budget", "council", "board", "election", "mayor"]):
        affects.extend(["Residents"])
    if any(k in t for k in ["airport", "flight", "tsa"]):
        affects.extend(["Air travelers"])
    out: list[str] = []
    for a in affects:
        if a not in out:
            out.append(a)
    return out[:4]


def _ua() -> str:
    ua = os.environ.get("MSPMETRO_USER_AGENT", "").strip()
    if ua:
        return ua
    profile = (os.environ.get("MSPMETRO_UA_PROFILE") or "chrome-linux").strip()
    profiles = {
        "safari-mac": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.10 Safari/605.1.1"
        ),
        "chrome-mac": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.3"
        ),
        "chrome-win": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.3"
        ),
        "chrome-linux": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.3"
        ),
    }
    return profiles.get(profile, profiles["chrome-linux"])


def _http_get_json(url: str, *, accept: str = "application/json") -> dict:
    req = Request(
        url,
        headers={
            "User-Agent": _ua(),
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.8",
            "DNT": "1",
        },
    )
    with urlopen(req, timeout=20) as resp:  # nosec - allowlisted public endpoints
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _http_get_json_with_ua(url: str, *, ua: str, accept: str = "application/json") -> dict:
    req = Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.8",
            "DNT": "1",
        },
    )
    with urlopen(req, timeout=20) as resp:  # nosec - allowlisted public endpoints
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


@dataclass(frozen=True)
class OrientationData:
    temp_f: int | None
    feels_like_f: int | None
    phrase: str | None
    sunrise: str | None
    sunset: str | None
    moonrise: str | None
    moonset: str | None
    moon_phase: str | None
    daylight: str | None


_ORIENTATION_CACHE: OrientationData | None = None


def _format_clock(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Open-Meteo returns local timestamps (no offset) when timezone= is set.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CT_TZ)
        dt = dt.astimezone(CT_TZ)
        return dt.strftime("%-I:%M%p").lower()
    except Exception:
        return None


def _moon_phase_label(value: float | None) -> str | None:
    if value is None:
        return None
    v = float(value)
    if v < 0:
        v = 0.0
    if v > 1:
        v = 1.0
    if v < 0.03 or v > 0.97:
        return "New moon"
    if v < 0.22:
        return "Waxing crescent"
    if v < 0.28:
        return "First quarter"
    if v < 0.47:
        return "Waxing gibbous"
    if v < 0.53:
        return "Full moon"
    if v < 0.72:
        return "Waning gibbous"
    if v < 0.78:
        return "Last quarter"
    return "Waning crescent"


def _moon_phase_from_degrees(deg: float | None) -> str | None:
    if deg is None:
        return None
    d = float(deg) % 360.0
    if d < 10 or d > 350:
        return "New moon"
    if d < 85:
        return "Waxing crescent"
    if d < 95:
        return "First quarter"
    if d < 170:
        return "Waxing gibbous"
    if d < 190:
        return "Full moon"
    if d < 265:
        return "Waning gibbous"
    if d < 275:
        return "Last quarter"
    return "Waning crescent"


def _daylight_duration(sunrise_iso: str | None, sunset_iso: str | None) -> str | None:
    if not sunrise_iso or not sunset_iso:
        return None
    try:
        sr = datetime.fromisoformat(sunrise_iso.replace("Z", "+00:00"))
        ss = datetime.fromisoformat(sunset_iso.replace("Z", "+00:00"))
        if sr.tzinfo is None:
            sr = sr.replace(tzinfo=CT_TZ)
        if ss.tzinfo is None:
            ss = ss.replace(tzinfo=CT_TZ)
        sr = sr.astimezone(CT_TZ)
        ss = ss.astimezone(CT_TZ)
        delta = ss - sr
        total_minutes = max(int(delta.total_seconds() // 60), 0)
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h}h {m:02d}m"
    except Exception:
        return None


def _fetch_open_meteo(lat: float, lon: float) -> dict:
    qs = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "timezone": "America/Chicago",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "current": "temperature_2m,apparent_temperature,weather_code",
            "daily": "sunrise,sunset",
        }
    )
    return _http_get_json(f"https://api.open-meteo.com/v1/forecast?{qs}")

def _met_ua() -> str:
    # met.no requires a descriptive User-Agent with contact information.
    return os.environ.get("MSPMETRO_MET_UA", "MSPMetro/0.1 (admin@mspmetro.com)").strip()


def _format_offset_for_met(now: datetime) -> str:
    ct = now.astimezone(CT_TZ)
    z = ct.strftime("%z")  # e.g. -0600
    if len(z) == 5:
        return f"{z[:3]}:{z[3:]}"
    return "-06:00"


def _fetch_met_sun_moon(lat: float, lon: float, *, now: datetime) -> dict:
    date = now.astimezone(CT_TZ).date().isoformat()
    offset = _format_offset_for_met(now)
    qs = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "date": date, "offset": offset})
    url = f"https://api.met.no/weatherapi/sunrise/3.0/sun?{qs}"
    return _http_get_json_with_ua(url, ua=_met_ua(), accept="application/json")


def _fetch_met_moon(lat: float, lon: float, *, now: datetime) -> dict:
    date = now.astimezone(CT_TZ).date().isoformat()
    offset = _format_offset_for_met(now)
    qs = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "date": date, "offset": offset})
    url = f"https://api.met.no/weatherapi/sunrise/3.0/moon?{qs}"
    return _http_get_json_with_ua(url, ua=_met_ua(), accept="application/json")


def _fetch_nws_phrase(lat: float, lon: float) -> str | None:
    try:
        points = _http_get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", accept="application/geo+json")
        forecast_url = ((points.get("properties") or {}).get("forecast") or "").strip()
        if not forecast_url:
            return None
        fc = _http_get_json(forecast_url, accept="application/geo+json")
        periods = ((fc.get("properties") or {}).get("periods") or [])
        if periods:
            return (periods[0].get("shortForecast") or "").strip() or None
        return None
    except Exception:
        return None


def _weather_code_phrase(code: int | None) -> str | None:
    if code is None:
        return None
    # Open-Meteo weather codes.
    mapping = {
        0: "Clear",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers",
        81: "Rain showers",
        82: "Heavy showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm",
        99: "Thunderstorm",
    }
    return mapping.get(int(code))


def load_orientation_data() -> OrientationData:
    global _ORIENTATION_CACHE
    if _ORIENTATION_CACHE is not None:
        return _ORIENTATION_CACHE

    point = os.environ.get("MSPMETRO_NWS_POINT", "44.9778,-93.2650").strip()
    try:
        lat_s, lon_s = point.split(",", 1)
        lat = float(lat_s.strip())
        lon = float(lon_s.strip())
    except Exception:
        lat, lon = 44.9778, -93.2650

    temp_f = feels_f = None
    phrase = None
    sunrise = sunset = None
    moonrise = moonset = moon_phase = None

    now = _now()

    try:
        om = _fetch_open_meteo(lat, lon)
        cur = om.get("current") or {}
        temp_f = int(round(float(cur.get("temperature_2m")))) if cur.get("temperature_2m") is not None else None
        feels_f = int(round(float(cur.get("apparent_temperature")))) if cur.get("apparent_temperature") is not None else None
        code = int(cur.get("weather_code")) if cur.get("weather_code") is not None else None
        phrase = _weather_code_phrase(code)
    except Exception:
        daylight = None

    # Prefer NWS phrase when available (official language).
    nws_phrase = _fetch_nws_phrase(lat, lon)
    if nws_phrase:
        phrase = nws_phrase

    try:
        sun = _fetch_met_sun_moon(lat, lon, now=now)
        props = sun.get("properties") or {}
        sunrise_iso = (props.get("sunrise") or {}).get("time") if isinstance(props.get("sunrise"), dict) else None
        sunset_iso = (props.get("sunset") or {}).get("time") if isinstance(props.get("sunset"), dict) else None
        sunrise = _format_clock(sunrise_iso)
        sunset = _format_clock(sunset_iso)
        daylight = _daylight_duration(sunrise_iso, sunset_iso)
    except Exception:
        # Fall back to Open-Meteo daily sunrise/sunset if met.no is unavailable.
        try:
            om = _fetch_open_meteo(lat, lon)
            daily = om.get("daily") or {}
            sunrise_iso = (daily.get("sunrise") or [None])[0] if isinstance(daily.get("sunrise"), list) else None
            sunset_iso = (daily.get("sunset") or [None])[0] if isinstance(daily.get("sunset"), list) else None
            sunrise = _format_clock(sunrise_iso)
            sunset = _format_clock(sunset_iso)
            daylight = _daylight_duration(sunrise_iso, sunset_iso)
        except Exception:
            pass

    try:
        moon = _fetch_met_moon(lat, lon, now=now)
        props = moon.get("properties") or {}
        moonrise_iso = (props.get("moonrise") or {}).get("time") if isinstance(props.get("moonrise"), dict) else None
        moonset_iso = (props.get("moonset") or {}).get("time") if isinstance(props.get("moonset"), dict) else None
        moonrise = _format_clock(moonrise_iso)
        moonset = _format_clock(moonset_iso)
        moon_phase = _moon_phase_from_degrees(props.get("moonphase"))
    except Exception:
        pass

    # Daylight might not have been computed if Open-Meteo forecast failed.
    if "daylight" not in locals():
        daylight = None

    _ORIENTATION_CACHE = OrientationData(
        temp_f=temp_f,
        feels_like_f=feels_f,
        phrase=phrase,
        sunrise=sunrise,
        sunset=sunset,
        moonrise=moonrise,
        moonset=moonset,
        moon_phase=moon_phase,
        daylight=daylight,
    )
    return _ORIENTATION_CACHE


def _strip_html(s: str) -> str:
    return strip_markup_to_text(s)


def _clean_feed_snippet(s: str) -> str:
    s = _strip_html(s)
    if not s:
        return ""
    # WordPress boilerplate: "The post X appeared first on Y."
    if re.search(r"\bappeared first on\b", s, flags=re.IGNORECASE):
        s = re.sub(r"\bThe post\b.*?\bappeared first on\b.*?$", "", s, flags=re.IGNORECASE).strip()
        if not s:
            return ""
    if s.lower().startswith("the post ") and "appeared first on" in s.lower():
        return ""
    # Strip any remaining bracket-like artifacts.
    s = s.replace("[", "").replace("]", "").strip()
    # Keep deks calm and scannable.
    if len(s) > 240:
        s = s[:237].rstrip() + "…"
    return s


def _clean_title(s: str | None) -> str:
    t = _strip_html(s or "")
    if not t:
        return ""
    if len(t) > 140:
        t = t[:137].rstrip() + "…"
    return t


def _item_when(it: Item) -> datetime | None:
    return it.updated_at or it.published_at or it.ingested_at


def _load_items_for_sources(
    db,
    source_names: tuple[str, ...],
    *,
    limit: int,
    now: datetime,
    max_age_days: int | None = None,
) -> list[tuple[Item, Source]]:
    if not source_names:
        return []
    deny_urls = _load_denylist_urls()
    q = (
        db.query(Item, Source)
        .join(Source, Source.id == Item.source_id)
        .filter(Source.name.in_(list(source_names)))
    )
    if max_age_days is not None:
        cutoff = now - timedelta(days=int(max_age_days))
        q = q.filter((Item.published_at.is_not(None) & (Item.published_at >= cutoff)) | (Item.ingested_at >= cutoff))
    q = q.order_by(desc(Item.published_at).nullslast(), desc(Item.ingested_at))
    rows = q.limit(limit * 3).all()
    if not deny_urls:
        return rows[:limit]
    out: list[tuple[Item, Source]] = []
    for it, src in rows:
        if it.canonical_url and _normalize_url(it.canonical_url) in deny_urls:
            continue
        out.append((it, src))
        if len(out) >= limit:
            break
    return out


def _load_active_alerts(db, *, limit: int, now: datetime) -> list[Alert]:
    q = db.query(Alert)
    q = q.filter((Alert.expires_at.is_(None)) | (Alert.expires_at > now))
    # Severity order (high -> low) without relying on enum sort behavior.
    sev_order = case(
        (Alert.severity == AlertSeverity.EMERGENCY, 4),
        (Alert.severity == AlertSeverity.WARNING, 3),
        (Alert.severity == AlertSeverity.ADVISORY, 2),
        (Alert.severity == AlertSeverity.INFO, 1),
        else_=0,
    )
    q = q.order_by(desc(sev_order), desc(Alert.created_at))
    return q.limit(limit).all()


def _severity_label(sev: str) -> str:
    v = (sev or "").strip().upper()
    return {
        AlertSeverity.EMERGENCY.value: "Emergency",
        AlertSeverity.WARNING.value: "Warning",
        AlertSeverity.ADVISORY.value: "Advisory",
        AlertSeverity.INFO.value: "Info",
    }.get(v, v.title() or "Info")


def _doc_head(*, root_prefix: str, title: str, description: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content="{_escape(description)}" />

    <link rel="stylesheet" href="{_escape(_site_href('/static/css/daily.css', root_prefix=root_prefix))}" />
    <link
      rel="preload"
      href="{_escape(_site_href('/static/fonts/AtkinsonHyperlegibleNext-Regular.otf', root_prefix=root_prefix))}"
      as="font"
      type="font/otf"
      crossorigin
    />
    <link
      rel="preload"
      href="{_escape(_site_href('/static/fonts/AtkinsonHyperlegibleNext-Bold.otf', root_prefix=root_prefix))}"
      as="font"
      type="font/otf"
      crossorigin
    />
    <link rel="icon" type="image/png" href="{_escape(_site_href('/static/favicon.png', root_prefix=root_prefix))}" />
    <link rel="apple-touch-icon" href="{_escape(_site_href('/static/favicon.png', root_prefix=root_prefix))}" />
    <title>{_escape(title)}</title>
  </head>
  <body id="top">
"""


def _doc_foot() -> str:
    return """  </body>
</html>
"""


def _orientation_block(*, now: datetime, root_prefix: str) -> str:
    day = '[[ dateInZone "Monday" now "America/Chicago" ]]'
    date_long = '[[ dateInZone "January 2, 2006" now "America/Chicago" ]]'
    utc_clock = '[[ now.UTC.Format "15:04Z" ]]'
    od = load_orientation_data()
    temp = f"{od.temp_f}°F" if od.temp_f is not None else "--°F"
    feels = f"(feels {od.feels_like_f}°F)" if od.feels_like_f is not None else "(feels --°F)"
    phrase = od.phrase or "—"
    sunrise = od.sunrise or "—"
    sunset = od.sunset or "—"
    return f"""
    <a class="skip-link" href="#main">Skip to main content</a>

    <header class="orientation" aria-label="Orientation">
      <div class="wrap">
        <dl class="orientation-grid">
          <div class="orientation-logo">
            <dt class="sr-only">MSPMetro</dt>
            <dd>
              <a class="brand" href="https://www.mspmetro.com/" aria-label="MSPMetro home">
                <img src="/static/Logo_SVG.svg" alt="" aria-hidden="true" width="72" height="72" />
              </a>
            </dd>
          </div>
          <div>
            <dt>Day</dt>
            <dd>{day}</dd>
          </div>
          <div>
            <dt>Date</dt>
            <dd>{date_long}</dd>
          </div>
          <div>
            <dt>Region</dt>
            <dd>Twin Cities</dd>
          </div>
          <div>
            <dt>Weather</dt>
            <dd>
              {_escape(temp)} <span class="muted">{_escape(feels)}</span>
              <span aria-hidden="true">•</span> {_escape(phrase)}
            </dd>
          </div>
          <div class="orientation-sun">
            <dt>Sunrise/Sunset</dt>
            <dd>{_escape(sunrise)} / {_escape(sunset)}</dd>
          </div>
          <div class="orientation-utc">
            <dt>UTC</dt>
            <dd><span class="orientation-utc__value">{utc_clock}</span></dd>
          </div>
        </dl>
      </div>
    </header>
"""


def _top_nav(*, is_frontpage: bool, root_prefix: str) -> str:
    if is_frontpage:
        weather = "#weather"
        metro = "#metro"
        world = "#world"
        neighbors = "/neighbors/"
        transit = "#transit"
        events = "/events/"
    else:
        weather = _site_href("/weather/", root_prefix=root_prefix)
        metro = _site_href("/metro/", root_prefix=root_prefix)
        world = _site_href("/world/", root_prefix=root_prefix)
        neighbors = _site_href("/neighbors/", root_prefix=root_prefix)
        transit = _site_href("/transit/", root_prefix=root_prefix)
        events = _site_href("/events/", root_prefix=root_prefix)

    return f"""
    <nav class="top-nav" aria-label="Primary">
      <div class="wrap">
        <a href="{weather}">Weather</a> · <a href="{metro}">Metro</a> ·
        <a href="{world}">World</a> · <a href="{neighbors}">Neighbors</a> ·
        <a href="{transit}">Transit</a> · <a href="{events}">Events</a>
      </div>
    </nav>
"""


def _footer(*, root_prefix: str, build_meta: BuildMeta) -> str:
    od = load_orientation_data()
    daylight = od.daylight or "—"
    moon = od.moon_phase or "—"
    moon_bits = [f"Moon: {_escape(moon)}"]
    if od.moonrise:
        moon_bits.append(f"Moonrise {_escape(od.moonrise)}")
    if od.moonset:
        moon_bits.append(f"Moonset {_escape(od.moonset)}")
    moon_line = '<span aria-hidden="true"> • </span>'.join(moon_bits)
    return f"""
    <footer class="footer" aria-label="Context">
      <div class="wrap">
        <p>
          Daylight: {_escape(daylight)}<span aria-hidden="true"> • </span>{moon_line}
        </p>
        <p class="footer-links">
          <a href="{_escape(_site_href('/how-we-know/', root_prefix=root_prefix))}">How we know</a
          ><span aria-hidden="true"> · </span><a href="{_escape(_site_href('/daily/', root_prefix=root_prefix))}">Daily archive</a
          ><span aria-hidden="true"> · </span><a href="{_escape(_site_href('/credits/', root_prefix=root_prefix))}">Credits</a>
        </p>
        <p class="footer-build">
          Build: {_escape(build_meta.host)}<span aria-hidden="true"> · </span>{_escape(build_meta.time_utc)}
          <span aria-hidden="true"> · </span>{_escape(build_meta.commit)}
        </p>
      </div>
    </footer>
"""


def _render_frontpage(db, *, out_dir: Path, now: datetime, build_meta: BuildMeta) -> None:
    alerts = _load_active_alerts(db, limit=3, now=now)
    alert_list_hidden_attr = "" if alerts else " hidden"

    alert_items = []
    for a in alerts:
        pill = _severity_label(a.severity.value)
        sev = a.severity.value.lower()
        title = (a.title or "").strip() or "Alert"
        body = (a.body or "").strip()
        summary = body.splitlines()[0].strip() if body else ""
        line = _escape(summary or title)
        source_label = "Source: National Weather Service (Tier 1)"
        alert_items.append(
            f"""          <li>
            <span class="alert-pill" data-severity="{_escape(sev)}">{_escape(pill)}</span>
            {line}
            <span class="alert-source">{_escape(source_label)}</span>
          </li>"""
        )

    cards_html = []
    picks_html = []

    for sec in SECTIONS:
        items = _load_items_for_sources(db, sec.source_names, limit=6, now=now, max_age_days=sec.max_age_days)
        top_items = items[:3]
        list_items = []
        for item, _src in top_items:
            title = _clean_title(item.title)
            if not title or not item.canonical_url:
                continue
            anchor = f"i-{item.id.hex[:10]}"
            href = _site_href(f"{sec.page_path}#{anchor}", root_prefix="")
            list_items.append(
                f"""              <li>
                <a href="{_escape(href)}">{_escape(title)} {_arrow_internal()}</a>
              </li>"""
            )

        if sec.key == "world" and len(list_items) < 3:
            list_items.extend(
                [
                    f"""              <li>
                <a href="{_escape(_site_href(sec.page_path, root_prefix=''))}">World briefing {_arrow_internal()}</a>
              </li>""",
                    f"""              <li>
                <a href="https://www.npr.org/sections/world/" rel="external noopener noreferrer">NPR World {_arrow_external()}</a>
              </li>""",
                    f"""              <li>
                <a href="https://www.bbc.com/news/world" rel="external noopener noreferrer">BBC World {_arrow_external()}</a>
              </li>""",
                ]
            )
        elif sec.key == "events" and len(list_items) < 3:
            list_items.extend(
                [
                    f"""              <li>
                <a href="{_escape(_site_href(sec.page_path, root_prefix=''))}">Today and this weekend {_arrow_internal()}</a>
              </li>""",
                    f"""              <li>
                <a href="https://www.minneapolis.org/calendar/" rel="external noopener noreferrer">Minneapolis calendar {_arrow_external()}</a>
              </li>""",
                    f"""              <li>
                <a href="https://www.visitsaintpaul.com/events/" rel="external noopener noreferrer">Saint Paul events {_arrow_external()}</a>
              </li>""",
                ]
            )
        elif not list_items:
            list_items.append(
                f"""              <li>
                <a href="{_escape(_site_href(sec.page_path, root_prefix=''))}">Open {_escape(sec.label)} {_arrow_internal()}</a>
              </li>"""
            )

        header = sec.key.upper()
        header_html = (
            f'<h2 class="kicker" id="{sec.key}-title">{header}</h2>'
            if sec.key == "weather"
            else f'<h2 class="kicker" id="{sec.key}-title"><a href="{_escape(_site_href(sec.page_path, root_prefix=""))}">{header} {_arrow_internal()}</a></h2>'
        )

        cards_html.append(
            f"""          <section id="{sec.key}" class="card" aria-labelledby="{sec.key}-title">
            {header_html}
            <ul class="link-list">
{os.linesep.join(list_items)}
            </ul>
            <a class="see-all" href="{_escape(_site_href(sec.page_path, root_prefix=''))}">SEE ALL {_arrow_internal()}</a>
          </section>"""
        )

        # Picks: only story/event picks (no Weather/Transit, and no Metro).
        # Use 4 items where possible for a richer "this looks interesting" scan.
        if sec.key in {"neighbors", "events"}:
            pick_items = items[:4]
            if pick_items:
                pick_li = []
                for item, src in pick_items:
                    title = _clean_title(item.title)
                    if not title or not item.canonical_url:
                        continue
                    anchor = f"i-{item.id.hex[:10]}"
                    href = _site_href(f"{sec.page_path}#{anchor}", root_prefix="")
                    note = f"From {src.name}"
                    affects = _affects_from_title(title)
                    if affects:
                        note = f"Affects: {' · '.join(affects)}"
                    pick_li.append(
                        f"""              <li>
                <a href="{_escape(href)}">{_escape(title)} {_arrow_internal()}</a>
                <span class="pick-note">{_escape(note)}.</span>
              </li>"""
                    )
                if pick_li:
                    picks_html.append(
                        f"""          <section class="card card--pick" aria-labelledby="pick-{sec.key}-title">
            <h3 class="kicker" id="pick-{sec.key}-title">{sec.key.upper()}</h3>
            <ul class="link-list">
{os.linesep.join(pick_li)}
            </ul>
          </section>"""
                    )
            elif sec.key == "events":
                picks_html.append(
                    """          <section class="card card--pick" aria-labelledby="pick-events-title">
            <h3 class="kicker" id="pick-events-title">EVENTS</h3>
            <ul class="link-list">
              <li>
                <a href="https://www.minneapolis.org/calendar/" rel="external noopener noreferrer">Minneapolis calendar """
                    + _arrow_external()
                    + """</a>
                <span class="pick-note">A quick scan for tonight.</span>
              </li>
              <li>
                <a href="https://www.visitsaintpaul.com/events/" rel="external noopener noreferrer">Saint Paul events """
                    + _arrow_external()
                    + """</a>
                <span class="pick-note">Useful if weather changes plans.</span>
              </li>
              <li>
                <a href="https://www.walkerart.org/calendar/" rel="external noopener noreferrer">Walker Art Center """
                    + _arrow_external()
                    + """</a>
                <span class="pick-note">Museum + film listings.</span>
              </li>
              <li>
                <a href="https://first-avenue.com/shows/" rel="external noopener noreferrer">First Avenue shows """
                    + _arrow_external()
                    + """</a>
                <span class="pick-note">Live music planning.</span>
              </li>
            </ul>
          </section>"""
                )

    # World picks: keep a few external, non-paywalled references.
    picks_html.append(
        """          <section class="card card--pick" aria-labelledby="pick-world-title">
            <h3 class="kicker" id="pick-world-title">WORLD</h3>
            <ul class="link-list">
              <li>
                <a href="https://www.npr.org/sections/world/" rel="external noopener noreferrer">NPR World """
        + _arrow_external()
        + """</a>
                <span class="pick-note">A fast scan for high-impact developments.</span>
              </li>
              <li>
                <a href="https://www.bbc.com/news/world" rel="external noopener noreferrer">BBC World """
        + _arrow_external()
        + """</a>
                <span class="pick-note">Useful background if something breaks late.</span>
              </li>
              <li>
                <a href="https://apnews.com/world-news" rel="external noopener noreferrer">AP World """
        + _arrow_external()
        + """</a>
                <span class="pick-note">Straight reporting, quick headlines.</span>
              </li>
              <li>
                <a href="https://www.reuters.com/world/" rel="external noopener noreferrer">Reuters World """
        + _arrow_external()
        + """</a>
                <span class="pick-note">Markets and geopolitics signal.</span>
              </li>
            </ul>
          </section>"""
    )

    # What changed: count items in last 2 hours.
    recent_cutoff = now - timedelta(hours=2)
    recent_items = db.query(Item).filter(Item.ingested_at >= recent_cutoff).count()

    doc = (
        _doc_head(
            root_prefix="",
            title="MSPMetro — Daily",
            description="A calm, accessible daily dashboard for news, transit, weather, and events.",
        )
        + _orientation_block(now=now, root_prefix="")
        + _top_nav(is_frontpage=True, root_prefix="")
        + f"""
    <main id="main" class="wrap" tabindex="-1">
      <h1 class="sr-only">MSPMetro Daily Dashboard</h1>

      <section class="feature" aria-labelledby="feature-title">
        <h2 class="kicker" id="feature-title"><a href="/featured/">FEATURE</a></h2>
        <h3 class="feature__hed"><a href="/featured/">Featured story and context</a></h3>
        <p class="feature__dek">One story at a time: high-priority context, restrained and sourceable.</p>
      </section>

      <div class="front-updates" role="group" aria-label="Status and alerts">
        <section class="status" aria-label="City status">
          <p class="status__line">
            <span class="status__label">CITY STATUS:</span> Normal operations<span aria-hidden="true"> · </span>No declared emergencies
          </p>
        </section>

        <section class="alerts" aria-live="polite" aria-atomic="true">
          <h2 class="kicker" id="alerts-title">ALERTS</h2>
          <ul class="alert-list" aria-labelledby="alerts-title"{alert_list_hidden_attr}>
{os.linesep.join(alert_items)}
          </ul>
          <p class="empty-state">No current alerts or disruptions</p>
        </section>
      </div>

      <div class="front-briefs" role="group" aria-label="Briefs">
        <section class="glance" aria-label="Today at a glance">
          <h2 class="kicker" id="glance-title">TODAY AT A GLANCE</h2>
          <ul class="brief-list" aria-labelledby="glance-title">
            <li>Built from verified sources; updates post quietly.</li>
            <li>Use section pages for depth; front page stays a briefing.</li>
            <li>Look for advisories that change your next 12 hours.</li>
          </ul>
        </section>

        <section class="before" aria-label="Before you go">
          <h2 class="kicker" id="before-title">BEFORE YOU GO</h2>
          <ul class="brief-list" aria-labelledby="before-title">
            <li>Check weather and transit before travel.</li>
            <li>Keep plans flexible if advisories escalate.</li>
          </ul>
        </section>
      </div>

      <section id="summary" aria-label="Summary">
        <div class="grid" aria-label="Daily sections">
{os.linesep.join(cards_html)}
        </div>
      </section>

      <section class="sampling" aria-labelledby="picks-title">
        <h2 class="kicker" id="picks-title">PICKS</h2>
        <div class="grid" aria-label="Quick picks by section">
{os.linesep.join(picks_html)}
        </div>
      </section>

      <p class="what-changed" id="what-changed">Updated recently: {_escape(str(recent_items))} items</p>
    </main>
"""
        + _footer(root_prefix="", build_meta=build_meta)
        + _doc_foot()
    )

    (out_dir / "index.html").write_text(doc, encoding="utf-8")


def _render_section_page(db, *, sec: SectionDef, out_dir: Path, now: datetime, build_meta: BuildMeta) -> None:
    out_path = out_dir / sec.key / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if sec.source_names:
        rows = _load_items_for_sources(db, sec.source_names, limit=40, now=now, max_age_days=sec.max_age_days)
        newest = None
        for it, _ in rows:
            newest = it.updated_at or it.published_at or it.ingested_at
            if newest:
                break
        updated_line = _rel_time(newest, now=now) if newest else "Updated today"
    else:
        rows = []
        updated_line = "Updated today"

    index_items = []
    detail_items = []

    for it, src in rows[:25]:
        title = _clean_title(it.title)
        if not title:
            continue
        anchor = f"i-{it.id.hex[:10]}"
        dek = _clean_feed_snippet(it.summary or "") or _clean_feed_snippet(it.content_text or "") or ""
        affects = _affects_from_title(title)
        affects_txt = f"Affects: {' · '.join(affects)} · " if affects else ""
        item_when = _item_when(it)
        item_updated = _rel_time(item_when, now=now) if item_when else "Updated today"
        meta = f"{affects_txt}{item_updated}"
        index_items.append(
            f"""          <li>
            <a href="#{_escape(anchor)}">{_escape(title)} {_arrow_internal()}</a>
            <p class="dek">{_escape(dek)}</p>
            <p class="meta-line">{_escape(meta)} · {_escape(src.name)}</p>
          </li>"""
        )

        body_p1 = _clean_feed_snippet(it.content_text or "") or _clean_feed_snippet(it.summary or "") or "Brief summary unavailable in feed."
        body_p2 = "Use the source link for full context and verification."

        src_link = ""
        if it.canonical_url:
            src_link = (
                f"""          <p class="source">
            <span class="meta-label">Source:</span>
            <a href="{_escape(it.canonical_url)}" rel="external noopener noreferrer">{_escape(src.name)} {_arrow_external()}</a>
          </p>"""
            )

        affects_line = ""
        if affects:
            affects_line = f"""          <p class="meta-line"><span class="meta-label">Affects:</span> {_escape(" · ".join(affects))}</p>"""

        published = _item_when(it)
        published_line = _to_ct(published).strftime("%Y-%m-%d %H:%M %Z") if published else ""

        detail_items.append(
            f"""        <article id="{_escape(anchor)}" class="article-detail">
          <h2>{_escape(title)}</h2>
          <p>{_escape(body_p1)}</p>
          <p>{_escape(body_p2)}</p>
{affects_line}
          <p class="meta-line"><span class="meta-label">Published:</span> {_escape(published_line)}</p>
{src_link}
          <p class="back">
            <a href="#index">Back to index {_arrow_internal()}</a>
          </p>
        </article>"""
        )

    if not index_items:
        index_items.append(
            """          <li>
            <a href="../">Daily briefing <span class="arrow" aria-hidden="true">→</span></a>
            <p class="dek">No items available yet for this section.</p>
            <p class="meta-line">Updated today</p>
          </li>"""
        )
        detail_items.append(
            """        <article id="empty" class="article-detail">
          <h2>No items yet</h2>
          <p>This section is staged but not populated yet.</p>
          <p class="back"><a href="../">Back to daily <span class="arrow" aria-hidden="true">→</span></a></p>
        </article>"""
        )

    title = f"MSPMetro — {sec.label}"
    desc = f"{sec.label} briefing: daily civic updates."

    doc = (
        _doc_head(root_prefix="../", title=title, description=desc)
        + _orientation_block(now=now, root_prefix="../")
        + _top_nav(is_frontpage=False, root_prefix="../")
        + f"""
    <main id="main" class="wrap" tabindex="-1">
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        <a href="../">Daily briefing</a>
      </nav>

      <header class="section-header">
        <h1>{_escape(sec.label)}</h1>
        <p class="section-meta">{_escape(updated_line)}</p>
      </header>

      <section class="briefing" aria-label="Section brief">
        <h2 class="kicker" id="section-brief-title">SECTION BRIEF</h2>
        <ul class="brief-list" aria-labelledby="section-brief-title">
          <li>High-signal updates only; the full story stays at the source.</li>
          <li>Items are grouped for planning your next 12 hours.</li>
          <li>Attribution is explicit for every item.</li>
        </ul>
      </section>

      <section class="watching" aria-label="What we are watching">
        <h2 class="kicker" id="watching-title">WHAT WE’RE WATCHING</h2>
        <ul class="brief-list" aria-labelledby="watching-title">
          <li>Material changes that alter travel or timing.</li>
          <li>Advisories that escalate during the day.</li>
          <li>Operational disruptions that affect services.</li>
        </ul>
      </section>

      <section id="index" class="index-block" aria-label="Article index">
        <h2 class="kicker" id="index-title">ARTICLES</h2>
        <ul class="article-index" aria-labelledby="index-title">
{os.linesep.join(index_items)}
        </ul>
      </section>

      <section class="details" aria-label="Article details">
{os.linesep.join(detail_items)}
        <p class="back">
          <a href="#top">Back to top <span class="arrow" aria-hidden="true">↑</span></a>
        </p>
      </section>
    </main>
"""
        + _footer(root_prefix="../", build_meta=build_meta)
        + _doc_foot()
    )

    out_path.write_text(doc, encoding="utf-8")


def build_site(*, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    build_meta = _build_metadata()

    with session() as db:
        _render_frontpage(db, out_dir=out_dir, now=now, build_meta=build_meta)
        for sec in SECTIONS:
            _render_section_page(db, sec=sec, out_dir=out_dir, now=now, build_meta=build_meta)
    _write_health_file(out_dir=out_dir, build_meta=build_meta)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate MSPMetro static pages from the Source Box database.")
    ap.add_argument("--out", default=os.environ.get("OUT_DIR", "build/site"), help="Output directory")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    build_site(out_dir=out_dir)
    print(f"OK: generated dynamic pages into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
