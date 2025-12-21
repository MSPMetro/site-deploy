#!/usr/bin/env bash
set -euo pipefail

domain="${1:-}"
if [[ -z "$domain" ]]; then
  echo "usage: $0 <domain>" >&2
  exit 2
fi

email="${ACME_EMAIL:-admin@mspmetro.com}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="${repo_root}/build/lego"
lego_bin="${work_dir}/lego"

mkdir -p "$work_dir"

install_lego() {
  if [[ -x "$lego_bin" ]]; then
    return 0
  fi

  local version="v4.24.0"
  local os="linux"
  local arch="amd64"
  local tgz="lego_${version}_${os}_${arch}.tar.gz"
  local url="https://github.com/go-acme/lego/releases/download/${version}/${tgz}"

  echo "Downloading lego ${version}..." >&2
  curl -fsSL "$url" -o "${work_dir}/${tgz}"
  tar -C "$work_dir" -xzf "${work_dir}/${tgz}" lego
  rm -f "${work_dir:?}/${tgz}"
  chmod 0755 "$lego_bin"
}

install_lego

if [[ -z "${SCW_ACCESS_KEY:-}" || -z "${SCW_SECRET_KEY:-}" || -z "${SCW_DEFAULT_PROJECT_ID:-}" ]]; then
  cat >&2 <<'EOF'
missing Scaleway DNS credentials for DNS-01.

Set in your environment (or .env):
  SCW_ACCESS_KEY=...
  SCW_SECRET_KEY=...
  SCW_DEFAULT_PROJECT_ID=...

These are used by lego's "scaleway" DNS provider to create _acme-challenge TXT records.
EOF
  exit 2
fi

echo "Issuing/renewing DNS-01 cert for ${domain} via Scaleway DNS..." >&2

"$lego_bin" \
  --path "$work_dir/state" \
  --email "$email" \
  --accept-tos \
  --dns scaleway \
  --domains "$domain" \
  run >/dev/null

cert_dir="${work_dir}/state/certificates"
leaf="${cert_dir}/${domain}.crt"
key="${cert_dir}/${domain}.key"
chain="${cert_dir}/${domain}.issuer.crt"
leaf_single="${cert_dir}/${domain}.leaf.crt"

if [[ ! -s "$leaf" || ! -s "$key" ]]; then
  echo "missing expected cert outputs: ${leaf} / ${key}" >&2
  exit 2
fi

python3 - <<PY
import re
from pathlib import Path
p=Path("${leaf}")
t=p.read_text(encoding="utf-8", errors="replace")
m=re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", t, re.S)
if not m:
    raise SystemExit("could not find PEM certificate block in: ${leaf}")
Path("${leaf_single}").write_text(m.group(0) + "\n", encoding="utf-8")
PY

echo "OK: ${leaf_single}" >&2
echo "OK: ${key}" >&2
if [[ -s "$chain" ]]; then
  echo "OK: ${chain}" >&2
fi

