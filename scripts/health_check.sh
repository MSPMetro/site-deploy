#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HEALTH_PATH="${HEALTH_PATH:-/health.txt}"
HEALTH_MAX_WAIT_SECONDS="${HEALTH_MAX_WAIT_SECONDS:-20}"
HEALTH_DELAY_SECONDS="${HEALTH_DELAY_SECONDS:-2}"

env_file="${ENV_FILE:-${root_dir}/.env}"
if [[ -f "${env_file}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${env_file}"
  set +a
fi

normalize_base() {
  local u="$1"
  u="$(printf '%s' "$u" | xargs)"
  u="${u%/}"
  echo "$u"
}

read_inventory_edges() {
  local inventory="${INVENTORY_FILE:-${root_dir}/ops/ansible/inventory.ini}"
  if [[ ! -f "$inventory" ]]; then
    return 0
  fi
  awk '
    /^\[mspmetro_edges\]/ { in_section=1; next }
    /^\[/ { in_section=0 }
    in_section && $1 !~ /^#/ && NF > 0 { print $1 }
  ' "$inventory"
}

load_edges() {
  local -n out="$1"
  if [[ -n "${EDGE_URLS:-}" ]]; then
    IFS=',' read -r -a out <<<"${EDGE_URLS}"
    return
  fi

  local found=()
  while IFS= read -r host; do
    [[ -z "$host" ]] && continue
    found+=("https://${host}")
  done < <(read_inventory_edges)
  out=("${found[@]}")
}

load_origins() {
  local -n out="$1"
  local found=()

  if [[ -n "${ORIGIN_URLS:-}" ]]; then
    IFS=',' read -r -a found <<<"${ORIGIN_URLS}"
  else
    [[ -n "${ORIGIN_BASE_URL:-}" ]] && found+=("${ORIGIN_BASE_URL}")
    [[ -n "${PUBLISH_ORIGIN_SCW:-}" ]] && found+=("${PUBLISH_ORIGIN_SCW}")
    [[ -n "${PUBLISH_ORIGIN_DO:-}" ]] && found+=("${PUBLISH_ORIGIN_DO}")
    [[ -n "${PUBLISH_ORIGIN_HET:-}" ]] && found+=("${PUBLISH_ORIGIN_HET}")
  fi

  out=("${found[@]}")
}

curl_with_retry() {
  local url="$1"
  local out_file="$2"
  local deadline=$((SECONDS + HEALTH_MAX_WAIT_SECONDS))
  local last_http="000"
  local last_err=""

  while true; do
    last_err=""
    local err_file
    err_file="$(mktemp)"
    if last_http="$(
      curl -sS --max-time 15 -o "$out_file" -w '%{http_code}' "$url" 2>"$err_file" || echo "000"
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

    sleep "$HEALTH_DELAY_SECONDS"
  done
}

curl_head_with_retry() {
  local url="$1"
  local deadline=$((SECONDS + HEALTH_MAX_WAIT_SECONDS))
  local last_http="000"
  local last_err=""

  while true; do
    last_err=""
    local err_file
    err_file="$(mktemp)"
    if last_http="$(
      curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -I "$url" 2>"$err_file" || echo "000"
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

    sleep "$HEALTH_DELAY_SECONDS"
  done
}

curl_headers_with_retry() {
  local url="$1"
  local out_file="$2"
  local deadline=$((SECONDS + HEALTH_MAX_WAIT_SECONDS))
  local last_http="000"
  local last_err=""

  while true; do
    last_err=""
    local err_file
    err_file="$(mktemp)"
    if last_http="$(
      curl -sS --max-time 15 -o /dev/null -D "$out_file" -w '%{http_code}' -I "$url" 2>"$err_file" || echo "000"
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

    sleep "$HEALTH_DELAY_SECONDS"
  done
}

parse_kv() {
  local key="$1"
  local file="$2"
  grep -m1 "^${key}=" "$file" | cut -d= -f2- || true
}

check_base() {
  local base="$1"
  local url tmp
  base="$(normalize_base "$base")"
  url="${base}${HEALTH_PATH}"

  tmp="$(mktemp)"
  if ! curl_with_retry "$url" "$tmp"; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    return 1
  fi

  local build_time commit served_by
  build_time="$(parse_kv build_time_utc "$tmp")"
  commit="$(parse_kv build_commit "$tmp")"
  served_by="$(parse_kv served_by "$tmp")"
  rm -f "$tmp" >/dev/null 2>&1 || true

  local header_file header_served_by
  header_file="$(mktemp)"
  if curl_headers_with_retry "$url" "$header_file"; then
    header_served_by="$(grep -i '^x-served-by:' "$header_file" | tail -n 1 | cut -d: -f2- | xargs || true)"
  else
    header_served_by=""
  fi
  rm -f "$header_file" >/dev/null 2>&1 || true

  build_time="${build_time:-unknown}"
  commit="${commit:-unknown}"
  if [[ -n "$header_served_by" ]]; then
    served_by="$header_served_by"
  fi
  served_by="${served_by:-unknown}"

  echo "OK: ${base} build=${build_time} commit=${commit} served_by=${served_by}" >&2
  printf '%s|%s\n' "$build_time" "$commit"
}

check_origin_manifest() {
  local base="$1"
  local manifest_url tmp
  base="$(normalize_base "$base")"
  manifest_url="${base}/manifests/latest.json"

  tmp="$(mktemp)"
  if ! curl_with_retry "$manifest_url" "$tmp"; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    return 1
  fi

  local version hash path
  if ! python3 - "$tmp" <<'PY' >"${tmp}.out"; then
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    m = json.load(f)
files = m.get("files") or []
if not files:
    raise SystemExit(2)
first = files[0]
print(m.get("version",""))
print(first.get("hash",""))
print(first.get("path",""))
PY
    echo "FAIL: invalid manifest JSON at ${manifest_url}" >&2
    rm -f "$tmp" "${tmp}.out" >/dev/null 2>&1 || true
    return 1
  fi

  version="$(sed -n '1p' "${tmp}.out")"
  hash="$(sed -n '2p' "${tmp}.out")"
  path="$(sed -n '3p' "${tmp}.out")"
  rm -f "$tmp" "${tmp}.out" >/dev/null 2>&1 || true

  if [[ -z "$hash" ]]; then
    echo "FAIL: manifest missing hash at ${manifest_url}" >&2
    return 1
  fi

  if ! curl_head_with_retry "${base}/objects/${hash}"; then
    echo "  from manifest file: ${path}" >&2
    return 1
  fi

  echo "OK: ${base} manifest=${version}" >&2
  printf '%s\n' "$version"
}

edges=()
origins=()
load_edges edges
load_origins origins

if [[ "${#edges[@]}" -eq 0 && "${#origins[@]}" -eq 0 ]]; then
  echo "error: no edges or origins configured; set EDGE_URLS or ORIGIN_URLS/PUBLISH_ORIGIN_*" >&2
  exit 2
fi

fail=0
expected_version=""

check_group() {
  local label="$1"
  local mode="$2"
  shift
  shift
  local items=("$@")
  local expected_version=""
  if [[ "${#items[@]}" -eq 0 ]]; then
    return 0
  fi
  echo "== ${label}"
  for base in "${items[@]}"; do
    local version
    if [[ "$mode" == "origin" ]]; then
      if ! version="$(check_origin_manifest "$base")"; then
        fail=1
        continue
      fi
    else
      if ! version="$(check_base "$base")"; then
        fail=1
        continue
      fi
    fi
    if [[ -z "$expected_version" ]]; then
      expected_version="$version"
    elif [[ "$version" != "$expected_version" ]]; then
      echo "WARN: version mismatch for ${base}" >&2
    fi
  done
}

check_group "Edges" edge "${edges[@]}"
check_group "Origins" origin "${origins[@]}"

exit "$fail"
