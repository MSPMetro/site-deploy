#!/usr/bin/env bash
set -euo pipefail

want_marker="${MARKER:-PICKS}"

EDGE_VERIFY_MAX_WAIT_SECONDS="${EDGE_VERIFY_MAX_WAIT_SECONDS:-60}"
EDGE_VERIFY_DELAY_SECONDS="${EDGE_VERIFY_DELAY_SECONDS:-3}"

urls=()
if [[ -n "${EDGE_URLS:-}" ]]; then
  # Comma-separated list of URLs to verify.
  IFS=',' read -r -a extra <<<"${EDGE_URLS}"
  urls=("${extra[@]}")
fi

# Back-compat: older .env files used ORIGIN_* as "public website URLs".
if [[ "${#urls[@]}" -eq 0 ]]; then
  if [[ -n "${ORIGIN_GLOBAL:-}" ]]; then urls+=("${ORIGIN_GLOBAL}"); fi
  if [[ -n "${ORIGIN_EUR:-}" ]]; then urls+=("${ORIGIN_EUR}"); fi
  if [[ -n "${ORIGIN_US:-}" ]]; then urls+=("${ORIGIN_US}"); fi
  if [[ -n "${ORIGIN_WORLD:-}" ]]; then urls+=("${ORIGIN_WORLD}"); fi
  if [[ -n "${ORIGIN_EARTH:-}" ]]; then urls+=("${ORIGIN_EARTH}"); fi
fi

if [[ "${#urls[@]}" -eq 0 ]]; then
  echo "error: no URLs provided; set EDGE_URLS (comma-separated), or legacy ORIGIN_GLOBAL/ORIGIN_EUR/ORIGIN_US/ORIGIN_WORLD/ORIGIN_EARTH" >&2
  exit 2
fi

fail=0

normalize_base() {
  local u="$1"
  u="${u%/}"
  echo "$u"
}

curl_get_with_retry() {
  local url="$1"
  local out_file="$2"
  local deadline=$((SECONDS + EDGE_VERIFY_MAX_WAIT_SECONDS))
  local last_err=""
  local last_http="000"

  while true; do
    last_err=""
    local err_file
    err_file="$(mktemp)"
    last_http="$(
      curl -sS --max-time 15 -L -o "$out_file" -w '%{http_code}' "$url" 2>"$err_file" || echo "000"
    )"
    if [[ -s "$err_file" ]]; then
      last_err="$(head -n 1 "$err_file" | tr -d '\r')"
    fi
    rm -f "$err_file" >/dev/null 2>&1 || true

    if [[ "$last_http" == "200" ]]; then
      return 0
    fi

    if (( SECONDS >= deadline )); then
      if [[ -n "$last_err" ]]; then
        echo "FAIL: GET ${url} (curl: ${last_err})" >&2
      else
        echo "FAIL: GET ${url} (http ${last_http})" >&2
      fi
      return 1
    fi

    sleep "$EDGE_VERIFY_DELAY_SECONDS"
  done
}

is_object_origin() {
  local base="$1"
  case "$base" in
    *"://world.mspmetro.com"*|*"://global.mspmetro.com"*|*"://earth.mspmetro.com"*|\
    *"://origin-"*".mspmetro.com"*|*"://origin-"*".rns.sh"*|\
    *".digitaloceanspaces.com"*|*".cdn.digitaloceanspaces.com"*|*".s3."*".scw.cloud"*|*"your-objectstorage.com"*|*".amazonaws.com"*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

check_url() {
  local base
  base="$(normalize_base "$1")"
  echo "== ${base}"

  if is_object_origin "$base"; then
    echo "SKIP: looks like an object-storage origin (not a web site). Use scripts/verify_origins.sh instead." >&2
    return 0
  fi

  local tmp_html
  tmp_html="$(mktemp)"
  if ! curl_get_with_retry "${base}/" "$tmp_html"; then
    # Common with object-storage-backed CDNs when "default root object" isn't configured.
    if curl_get_with_retry "${base}/index.html" "$tmp_html"; then
      echo "FAIL: ${base}/ does not serve index.html (but ${base}/index.html works); configure CDN 'default root object' / 'static website hosting'." >&2
      rm -f "$tmp_html" >/dev/null 2>&1 || true
      return 1
    fi
    rm -f "$tmp_html" >/dev/null 2>&1 || true
    return 1
  fi
  html="$(cat "$tmp_html")"
  rm -f "$tmp_html" >/dev/null 2>&1 || true

  if ! rg -q "${want_marker}" <<<"${html}"; then
    echo "FAIL: missing marker '${want_marker}' in ${base}/" >&2
    return 1
  fi

  if ! rg -q "<link[^>]*rel=\"stylesheet\"[^>]*href=\"/static/css/daily\\.css\"" <<<"${html}"; then
    echo "FAIL: missing daily.css link in ${base}/" >&2
    return 1
  fi

  if ! rg -q "AtkinsonHyperlegibleNext-Regular\\.otf" <<<"${html}"; then
    echo "FAIL: missing Atkinson Hyperlegible preload link in ${base}/" >&2
    return 1
  fi

  if ! rg -q "AtkinsonHyperlegibleNext-Bold\\.otf" <<<"${html}"; then
    echo "FAIL: missing Atkinson Hyperlegible Bold preload link in ${base}/" >&2
    return 1
  fi

  if ! css="$(curl -fsSL --max-time 15 "${base}/static/css/daily.css" 2>/dev/null)"; then
    echo "FAIL: GET ${base}/static/css/daily.css" >&2
    return 1
  fi

  if ! rg -q "FONT & RENDER STABILITY" <<<"${css}"; then
    echo "FAIL: CSS stability header missing in ${base}/static/css/daily.css" >&2
    return 1
  fi

  if ! rg -q "AtkinsonHyperlegibleNext-Regular\\.otf" <<<"${css}"; then
    echo "FAIL: missing Atkinson Hyperlegible @font-face in ${base}/static/css/daily.css" >&2
    return 1
  fi

  if ! rg -q "font-display:\\s*swap" <<<"${css}"; then
    echo "FAIL: missing font-display: swap in ${base}/static/css/daily.css" >&2
    return 1
  fi

  if ! curl -fsSI --max-time 15 "${base}/static/favicon.png" >/dev/null; then
    echo "FAIL: missing ${base}/static/favicon.png" >&2
    return 1
  fi

  if ! curl -fsSI --max-time 15 "${base}/static/Logo_SVG.svg" >/dev/null; then
    echo "FAIL: missing ${base}/static/Logo_SVG.svg" >&2
    return 1
  fi

  echo "OK"
}

for u in "${urls[@]}"; do
  if ! check_url "$u"; then
    fail=1
  fi
done

exit "$fail"
