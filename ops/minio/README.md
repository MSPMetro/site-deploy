# MinIO Publisher + Fanout Replication

This repo currently supports publishing the briefing site directly to multiple S3-compatible origins.

This document adds an alternative architecture:

- **Single write**: publish to a local MinIO bucket on the publisher host.
- **Fanout replication**: replicate from MinIO to multiple S3-compatible providers (DigitalOcean, Scaleway, etc).
- **Read-only edges**: edges continue to pull from their nearest origin and serve locally.

Important: MinIO does **not** fix TLS on CDN vanity hostnames by itself. `world.mspmetro.com` / `global.mspmetro.com` / `earth.mspmetro.com` must still be provisioned with a valid certificate at the CDN/provider.

## Components

- Publisher host (recommended: EU region VPS)
  - MinIO (S3 API)
  - `mc mirror --watch` fanout replication services (cross-provider)
  - Site generator + publisher (writes only to MinIO)
- Origins (S3-compatible providers)
  - Buckets are **write-only from MinIO replication**
  - CDNs may front them, but CDNs must be configured separately
- Edges (VPS)
  - Pull manifests/objects via `cityfeed-puller` (no S3 credentials needed)

## What gets replicated

The current publisher writes **only** these key prefixes to the source bucket:

- `objects/<sha256>`
- `manifests/latest.json`
- `manifests/<version>.json`

Fanout replication mirrors those prefixes to each origin bucket.

## Environment variables (publisher)

Create `/etc/mspmetro/minio.env` on the publisher host (chmod 0600) with:

- `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`
- optional `MINIO_VOLUMES=/var/lib/minio`
- optional `MINIO_SERVER_URL` and `MINIO_BROWSER_REDIRECT_URL` if you expose MinIO behind a proxy

Create `/etc/mspmetro/replication.env` with:

- `MINIO_ENDPOINT_URL=http://127.0.0.1:9000`
- `MINIO_BUCKET=mspmetro-site`
- `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` (can be root creds initially)
- For each remote (global/world/earth):
  - `REMOTE_<NAME>_ENDPOINT_URL`
  - `REMOTE_<NAME>_BUCKET`
  - `REMOTE_<NAME>_ACCESS_KEY`
  - `REMOTE_<NAME>_SECRET_KEY`
  - optional `REMOTE_<NAME>_ADDRESSING_STYLE` (`auto|path|virtual`)

## One-time setup

Use the Ansible playbook:

```bash
ANSIBLE_CONFIG=ops/ansible/ansible.cfg \
ansible-playbook -i 'YOUR_PUBLISHER_HOST,' -u root ops/ansible/minio_publisher.yml
```

Then configure replication services:

```bash
ANSIBLE_CONFIG=ops/ansible/ansible.cfg \
ansible-playbook -i 'YOUR_PUBLISHER_HOST,' -u root ops/ansible/minio_replication.yml
```

This sets up a dedicated `mspmetro-repl` user and three `systemd` services:

- `mspmetro-minio-replicate@global.service`
- `mspmetro-minio-replicate@world.service`
- `mspmetro-minio-replicate@earth.service` (optional if configured)

Each service continuously mirrors `minio/mspmetro-site` to the corresponding remote bucket and propagates deletes (`--remove`).

## Publishing flow (publisher host)

On the publisher host:

```bash
./scripts/build_site.sh
./scripts/publish_to_minio.sh
```

Replication services continuously mirror MinIO to remotes.
