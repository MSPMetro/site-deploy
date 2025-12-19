#!/usr/bin/env bash
set -euo pipefail

ORIGIN="${ORIGIN:-https://s3.fr-par.scw.cloud/pull.mspmetro.com}"
ROOT="${ROOT:-/var/www/mspmetro}"
WEB_USER="${WEB_USER:-www-data}"
WEB_GROUP="${WEB_GROUP:-www-data}"
CADDY_SNIPPET_SRC="${CADDY_SNIPPET_SRC:-}"
BINARY_SRC="${1:-}"

if [[ -z "${BINARY_SRC}" ]]; then
  echo "usage: $0 /path/to/cityfeed-puller" >&2
  echo "env: ORIGIN=... ROOT=... WEB_USER=... WEB_GROUP=... CADDY_SNIPPET_SRC=..." >&2
  exit 2
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root (uses install/chown/systemctl)" >&2
  exit 2
fi

install -o root -g root -m 0755 "${BINARY_SRC}" /usr/local/bin/cityfeed-puller

mkdir -p "${ROOT}"
chown -R "${WEB_USER}:${WEB_GROUP}" "${ROOT}"
chmod 0755 "${ROOT}"

cat >/etc/default/cityfeed-puller <<EOF
ORIGIN=${ORIGIN}
ROOT=${ROOT}
EOF
chmod 0644 /etc/default/cityfeed-puller

cat >/etc/systemd/system/cityfeed-puller.service <<'EOF'
[Unit]
Description=Cityfeed manifest puller
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=www-data
Group=www-data
EnvironmentFile=-/etc/default/cityfeed-puller
ExecStart=/usr/local/bin/cityfeed-puller --origin ${ORIGIN}
EOF
chmod 0644 /etc/systemd/system/cityfeed-puller.service

cat >/etc/systemd/system/cityfeed-puller.timer <<'EOF'
[Unit]
Description=Run cityfeed-puller periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF
chmod 0644 /etc/systemd/system/cityfeed-puller.timer

mkdir -p /etc/systemd/system/cityfeed-puller.service.d
cat >/etc/systemd/system/cityfeed-puller.service.d/override.conf <<EOF
[Service]
User=${WEB_USER}
Group=${WEB_GROUP}
UMask=0022
EOF
chmod 0644 /etc/systemd/system/cityfeed-puller.service.d/override.conf

systemctl daemon-reload

sudo -u "${WEB_USER}" /usr/local/bin/cityfeed-puller --origin "${ORIGIN}" --root "${ROOT}"

systemctl enable --now cityfeed-puller.timer

if [[ -n "${CADDY_SNIPPET_SRC}" ]]; then
  SNIPPET_DST=""
  if [[ -d /etc/caddy/conf.d ]]; then
    SNIPPET_DST="/etc/caddy/conf.d/mspmetro.caddy"
  elif [[ -d /etc/caddy/sites-enabled ]]; then
    SNIPPET_DST="/etc/caddy/sites-enabled/mspmetro.caddy"
  elif [[ -d /etc/caddy/sites ]]; then
    SNIPPET_DST="/etc/caddy/sites/mspmetro.caddy"
  else
    echo "warning: no known caddy snippet dir found; copy this snippet into your Caddyfile:" >&2
    cat "${CADDY_SNIPPET_SRC}" >&2
  fi

  if [[ -n "${SNIPPET_DST}" ]]; then
    install -o root -g root -m 0644 "${CADDY_SNIPPET_SRC}" "${SNIPPET_DST}"
    if [[ -f /etc/caddy/Caddyfile ]] && ! grep -q "$(dirname "${SNIPPET_DST}")" /etc/caddy/Caddyfile; then
      echo "warning: /etc/caddy/Caddyfile may not import $(dirname "${SNIPPET_DST}"); ensure it is included before relying on this snippet" >&2
    fi
  fi

  if command -v caddy >/dev/null 2>&1; then
    caddy validate --config /etc/caddy/Caddyfile
  fi
  systemctl reload caddy || true
fi

echo "OK: installed /usr/local/bin/cityfeed-puller"
echo "OK: initialized ${ROOT} and ran initial pull"
echo "OK: enabled cityfeed-puller.timer"
