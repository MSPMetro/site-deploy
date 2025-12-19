#!/usr/bin/env bash
set -euo pipefail

# =========================
# Configuration (overridable via env)
# =========================
ORIGIN="${ORIGIN:-https://s3.fr-par.scw.cloud/pull.mspmetro.com}"
ROOT="${ROOT:-/var/www/mspmetro}"
WEB_USER="${WEB_USER:-www-data}"
BINARY_SRC="${1:-}"

# =========================
# Usage / sanity checks
# =========================
if [[ -z "${BINARY_SRC}" ]]; then
  echo "usage: $0 /path/to/cityfeed-puller" >&2
  echo "env vars: ORIGIN=... ROOT=... WEB_USER=..." >&2
  exit 2
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "error: must be run as root (uses install/chown)" >&2
  exit 2
fi

if [[ ! -x "${BINARY_SRC}" ]]; then
  echo "error: ${BINARY_SRC} is not executable" >&2
  exit 2
fi

# =========================
# Install puller binary
# =========================
install -o root -g root -m 0755 \
  "${BINARY_SRC}" \
  /usr/local/bin/cityfeed-puller

# =========================
# Prepare site root
# =========================
mkdir -p "${ROOT}"
chown -R "${WEB_USER}:${WEB_USER}" "${ROOT}"
chmod 0755 "${ROOT}"

# =========================
# Prepare logging
# =========================
touch /var/log/cityfeed-puller.log
chown "${WEB_USER}:${WEB_USER}" /var/log/cityfeed-puller.log
chmod 0644 /var/log/cityfeed-puller.log

# =========================
# One-time initial pull
# =========================
# NOTE:
# This script performs a ONE-TIME initialization only.
# Ongoing updates are handled by cron or a systemd timer.
sudo -u "${WEB_USER}" \
  /usr/local/bin/cityfeed-puller \
    --origin "${ORIGIN}" \
    --root "${ROOT}"

# =========================
# Final instructions
# =========================
echo "OK: installed /usr/local/bin/cityfeed-puller"
echo "OK: initialized ${ROOT}"
echo "Next: configure Caddy with ops/caddy/mspmetro.caddy (serve /var/www/mspmetro/current only)."
echo "Next: set up periodic pulls via ops/systemd/ or ops/cron/ (this script does not schedule updates)."
