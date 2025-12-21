# Production Deployment (Manifest Puller)

This repo ships `cityfeed-puller`, a reconciler that pulls `manifests/latest.json` + immutable `objects/<hash>` over HTTP, builds a new snapshot, then atomically switches the `current` symlink.

## Server Layout (authoritative)

```
/var/www/mspmetro-brief/
  objects/
  snapshots/<version>/
  current -> snapshots/<version>
```

The web server should serve **only** `/var/www/mspmetro-brief/current`.

## Happy Path (Ansible + Make)

From the repo root:

```bash
# Publishes to Scaleway (origin-scw) + DigitalOcean (origin-do),
# then installs/updates the puller + systemd timer on edge hosts.
make deploy-brief
```

## One-command rebuild + publish + update edges (Source Box / Publisher)

If your Source Box is the authoritative builder/publisher (build → MinIO → replication fanout), run:

```bash
make rebuild-publish
```

This will:

- sync the repo to the source box (default)
- optionally run ingestion (set `mspmetro_run_ingest=true`)
- run the publisher systemd unit on the source box
- verify origins + public sites
- deploy/pull on all edges

Examples:

```bash
# publish only (no rsync)
ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/rebuild_publish.yml --extra-vars 'mspmetro_sync_repo=false'

# run ingestion, then publish
ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/rebuild_publish.yml --extra-vars 'mspmetro_run_ingest=true'
```

Inventory lives in `ops/ansible/inventory.ini`. Hosts that aren't reachable yet are kept commented under `*_extra` groups.

### Origin redundancy (two CDNs)

Edges are configured with **two origins** (primary + secondary) so they can fail over if an origin/CDN is down:

- `ORIGIN_PRIMARY` and `ORIGIN_SECONDARY` are written to `/etc/default/cityfeed-puller-brief`
- systemd runs `cityfeed-puller` with both `--origin` flags

By convention (preferred origin labels):

- `edge.eur` prefers Scaleway (`origin-scw`) first, then DigitalOcean (`origin-do`)
- `edge.us` prefers DigitalOcean (`origin-do`) first, then Scaleway (`origin-scw`)

## DigitalOcean CDN custom domain (origin-do)

If you want a vanity hostname (example: `origin-do.mspmetro.com`) in front of the DigitalOcean Spaces-backed origin, you must attach a TLS certificate to the DO CDN endpoint.

This repo provides a CLI flow that:

1) issues a DNS-01 cert via Scaleway DNS, then
2) uploads+attaches it to the DO CDN endpoint (no GUI), then
3) you can `CNAME origin-do.mspmetro.com` to `origin-do.sfo3.cdn.digitaloceanspaces.com`.

Run:

```bash
make do-origin-do-bind-domain DO_ORIGIN_CUSTOM_DOMAIN=origin-do.mspmetro.com DO_ORIGIN_HOST=origin-do.sfo3.digitaloceanspaces.com
```

### Publishing to all CDNs

If you have multiple S3-compatible origins (recommended: Scaleway + DigitalOcean + Hetzner), publish to all of them with:

```bash
make publish-origins
```

The third origin (`origin-het`) is optional and configured via `HETZNER_*` / `PUBLISH_ORIGIN_HET` (see `.env.example`). In MSPMetro’s setup, it’s an **edge-only fallback origin URL** (provider bucket hostname), not a public hostname.

### Origin-het: DNS + TLS caveat (important)

`PUBLISH_ORIGIN_HET` / `HET_ORIGIN_BASE_URL` must be a **real HTTPS base URL** that serves:

- `manifests/latest.json`
- `objects/<sha256>`

For most S3-compatible stores, that base URL is the bucket endpoint (examples):

- DigitalOcean Spaces: `https://BUCKET.REGION.digitaloceanspaces.com`
- Hetzner Object Storage: `https://BUCKET.nbg1.your-objectstorage.com`

MSPMetro recommendation: do **not** use a vanity hostname for origin-het. Point edge nodes directly at the provider bucket URL.

A plain DNS `CNAME` from `origin-het.mspmetro.com` to a bucket endpoint often does **not** work for HTTPS:

- TLS certs usually cover `*.your-objectstorage.com`, not `origin-het.mspmetro.com`
- Many object stores route buckets by **Host header**, so `origin-het.mspmetro.com` won’t map to the bucket

If you want a vanity domain like `origin-het.mspmetro.com`, put a real proxy/CDN in front that:

- terminates TLS for `origin-het.mspmetro.com`
- forwards to the bucket endpoint with the correct Host header (or uses path-style routing)

## Install + First Pull (Ubuntu/Debian)

On your workstation (build):

```bash
cargo build --release
```

Copy to VPS:

```bash
scp ./target/release/cityfeed-puller root@YOUR_VPS:/tmp/cityfeed-puller
```

On the VPS (install + permissions + initial pull):

```bash
sudo install -o root -g root -m 0755 /tmp/cityfeed-puller /usr/local/bin/cityfeed-puller

sudo mkdir -p /var/www/mspmetro-brief
sudo chown -R caddy:caddy /var/www/mspmetro-brief
sudo chmod 0755 /var/www/mspmetro-brief

sudo -u caddy /usr/local/bin/cityfeed-puller \
  --origin https://pull.s3.fr-par.scw.cloud \
  --origin https://origin-do.sfo3.digitaloceanspaces.com \
  --root /var/www/mspmetro-brief
```

Verify:

```bash
readlink /var/www/mspmetro-brief/current
find /var/www/mspmetro-brief -maxdepth 3 -type d -print
```

## Nginx Wiring

Edit your existing site config and set:

```
root /var/www/mspmetro-brief/current;
```

Then reload (not restart):

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Caddy Wiring (static site)

If you are serving the static site directly with Caddy, templates live in:

- `ops/caddy/mspmetro.caddy` (static only)
- `ops/caddy/mspmetro.edge-us.caddy`
- `ops/caddy/mspmetro.edge-eur.caddy`

## Caddy Wiring (Rust UI + Flask backend, testing)

If you want the Rust UI + backend running on the server but keep the static pages for section depth,
use `ops/caddy/mspmetro.ssr.caddy`.

This config:

- proxies `/` and `/healthz` to the Rust UI on `127.0.0.1:8080`
- optionally proxies `/api/*` to the backend on `127.0.0.1:5000`
- serves everything else (e.g. `/metro/`, `/daily/`, `/static/`) from `/var/www/mspmetro-brief/current`

Install example:

```bash
sudo cp ops/caddy/mspmetro.ssr.caddy /etc/caddy/Caddyfile
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Service templates (systemd) for testing live in:

- `ops/systemd/mspmetro-backend.service`
- `ops/systemd/mspmetro-ui.service`

## Automation (cron, every 10 minutes)

Create a log file writable by the web user:

```bash
sudo touch /var/log/cityfeed-puller.log
sudo chown www-data:www-data /var/log/cityfeed-puller.log
```

Create `/etc/cron.d/cityfeed-puller`:

```cron
*/10 * * * * caddy /usr/local/bin/cityfeed-puller --origin https://pull.s3.fr-par.scw.cloud --root /var/www/mspmetro-brief >> /var/log/cityfeed-puller.log 2>&1
```

## Automation (systemd timer, randomized 15–45 minutes)

Copy:

- `ops/systemd/cityfeed-puller.service` → `/etc/systemd/system/cityfeed-puller.service`
- `ops/systemd/cityfeed-puller.timer` → `/etc/systemd/system/cityfeed-puller.timer`

Optionally set `/etc/default/cityfeed-puller-brief`:

```bash
ORIGIN=https://pull.s3.fr-par.scw.cloud
ROOT=/var/www/mspmetro-brief
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cityfeed-puller.timer
```

## Safety Checks

Kill mid-run (should not change `current`):

```bash
sudo -u caddy timeout -s INT 1 /usr/local/bin/cityfeed-puller --origin https://pull.s3.fr-par.scw.cloud --root /var/www/mspmetro-brief || true
readlink /var/www/mspmetro-brief/current
```

Rollback: repoint `manifests/latest.json` to an older `version` (the VPS will converge on the next run).

## Edge Nodes (Caddy + systemd timer)

If an edge server uses Caddy, prefer a separate snippet file over editing a large monolithic `Caddyfile`. Templates live in:

- `ops/caddy/mspmetro.edge-us.caddy`
- `ops/caddy/mspmetro.edge-eur.caddy`

And a one-shot setup helper (install binary, initialize `/var/www/mspmetro-brief`, enable systemd timer, optionally install the Caddy snippet) is:

- `scripts/edge_puller_setup.sh`

## IPFS/IPNS (optional)

If `ipfs` is installed and running on a host in the `mspmetro_ipfs` inventory group, deployment also publishes the current briefing snapshot to IPFS and updates IPNS.

Manual run:

```bash
make publish-ipns
```

The published IPNS key defaults to `mspmetro` and can be configured via `IPNS_KEY_NAME` / `IPNS_LIFETIME` in `.env`.
