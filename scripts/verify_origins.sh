#!/usr/bin/env bash
set -euo pipefail

ORIGIN_VERIFY_MAX_WAIT_SECONDS="${ORIGIN_VERIFY_MAX_WAIT_SECONDS:-180}"
ORIGIN_VERIFY_DELAY_SECONDS="${ORIGIN_VERIFY_DELAY_SECONDS:-5}"

origins=()
if [[ -n "${ORIGIN_URLS:-}" ]]; then
  IFS=',' read -r -a origins <<<"${ORIGIN_URLS}"
fi

# Prefer explicit publisher origin URLs when present.
if [[ "${#origins[@]}" -eq 0 ]]; then
  if [[ -n "${ORIGIN_BASE_URL:-}" ]]; then origins+=("${ORIGIN_BASE_URL}"); fi
  # Preferred names (SCW/DO/HET).
  if [[ -n "${PUBLISH_ORIGIN_SCW:-}" ]]; then origins+=("${PUBLISH_ORIGIN_SCW}"); fi
  if [[ -n "${PUBLISH_ORIGIN_DO:-}" ]]; then origins+=("${PUBLISH_ORIGIN_DO}"); fi
  if [[ -n "${PUBLISH_ORIGIN_HET:-}" ]]; then origins+=("${PUBLISH_ORIGIN_HET}"); fi

  # Legacy name (GLOBAL).
  if [[ -n "${PUBLISH_ORIGIN_GLOBAL:-}" ]]; then origins+=("${PUBLISH_ORIGIN_GLOBAL}"); fi
fi

if [[ "${#origins[@]}" -eq 0 ]]; then
  echo "error: no origins provided; set ORIGIN_URLS or ORIGIN_BASE_URL/PUBLISH_ORIGIN_{SCW,DO,HET} (or legacy PUBLISH_ORIGIN_GLOBAL)" >&2
  exit 2
fi

normalize_base() {
  local u="$1"
  # Trim leading/trailing whitespace and a trailing slash.
  u="$(printf '%s' "$u" | xargs)"
  u="${u%/}"
  echo "$u"
}

fail=0

curl_body_with_retry() {
  local url="$1"
  local out_file="$2"
  local deadline=$((SECONDS + ORIGIN_VERIFY_MAX_WAIT_SECONDS))
  local last_err=""
  local last_http="000"

  while true; do
    last_err=""
    local err_file
    err_file="$(mktemp)"

    # curl prints the status code even on non-200 responses; on transport errors it exits non-zero.
    if last_http="$(
      curl -sS --max-time 20 -o "$out_file" -w '%{http_code}' "$url" 2>"$err_file" || echo "000"
    )"; then
      :
    fi
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

    sleep "$ORIGIN_VERIFY_DELAY_SECONDS"
  done
}

curl_head_with_retry() {
  local url="$1"
  local deadline=$((SECONDS + ORIGIN_VERIFY_MAX_WAIT_SECONDS))
  local last_err=""
  local last_http="000"

  while true; do
    last_err=""
    local err_file
    err_file="$(mktemp)"
    if last_http="$(
      curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -I "$url" 2>"$err_file" || echo "000"
    )"; then
      :
    fi
    if [[ -s "$err_file" ]]; then
      last_err="$(head -n 1 "$err_file" | tr -d '\r')"
    fi
    rm -f "$err_file" >/dev/null 2>&1 || true

    if [[ "$last_http" == "200" ]]; then
      return 0
    fi

    if (( SECONDS >= deadline )); then
      if [[ -n "$last_err" ]]; then
        echo "FAIL: HEAD ${url} (curl: ${last_err})" >&2
      else
        echo "FAIL: HEAD ${url} (http ${last_http})" >&2
      fi
      return 1
    fi

    sleep "$ORIGIN_VERIFY_DELAY_SECONDS"
  done
}

check_origin() {
  local base manifest_url manifest object_url
  base="$(normalize_base "$1")"
  manifest_url="${base}/manifests/latest.json"

  echo "== ${base}"

  local tmp_manifest
  tmp_manifest="$(mktemp)"
  if ! curl_body_with_retry "$manifest_url" "$tmp_manifest"; then
    rm -f "$tmp_manifest" >/dev/null 2>&1 || true
    return 1
  fi
  manifest="$(cat "$tmp_manifest")"
  rm -f "$tmp_manifest" >/dev/null 2>&1 || true

  if ! printf '%s' "$manifest" | python3 -c '
import json, sys
m=json.load(sys.stdin)
files=m.get("files") or []
if not files:
    raise SystemExit(2)
first=files[0]
print(json.dumps({"version": m.get("version",""), "hash": first.get("hash",""), "path": first.get("path","")}))
' > /tmp/mspmetro-origin-verify.json; then
    echo "FAIL: invalid manifest JSON at ${manifest_url}" >&2
    return 1
  fi

  local version hash path
  version="$(python3 -c 'import json; print(json.load(open("/tmp/mspmetro-origin-verify.json")).get("version",""))')"
  hash="$(python3 -c 'import json; print(json.load(open("/tmp/mspmetro-origin-verify.json")).get("hash",""))')"
  path="$(python3 -c 'import json; print(json.load(open("/tmp/mspmetro-origin-verify.json")).get("path",""))')"

  if [[ -z "$hash" ]]; then
    echo "FAIL: manifest missing first file hash at ${manifest_url}" >&2
    return 1
  fi

  object_url="${base}/objects/${hash}"
  if ! curl_head_with_retry "$object_url"; then
    echo "  from manifest file: ${path}" >&2
    return 1
  fi

  echo "OK: ${version}"
}

for o in "${origins[@]}"; do
  if ! check_origin "$o"; then
    fail=1
  fi
done

rm -f /tmp/mspmetro-origin-verify.json >/dev/null 2>&1 || true
exit "$fail"
