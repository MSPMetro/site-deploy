.PHONY: setup run run-static run-backend setup-backend migrate-backend seed-backend run-ui db-up db-down test lint fmt
.PHONY: deploy-edge-eur setup-publisher build-site publish-origin publish-edge-global publish-edge-world publish-edge-earth publish-origins deploy-brief verify-brief verify-public publish-ipns
.PHONY: verify-origins
.PHONY: minio-publisher minio-replication publish-minio verify-minio-replication publicize-world deploy-brief-minio
.PHONY: do-cdn-list do-world-cdn-set-domain do-world-cdn-purge
.PHONY: do-world-bind-domain
.PHONY: rebuild-publish

setup:
	@echo "Run one of: make setup-backend, cargo build -p mspmetro-ui"

run:
	@$(MAKE) run-ui

run-static:
	@bash scripts/serve_local.sh

setup-backend:
	@python3 -m venv backend/.venv
	@backend/.venv/bin/pip install -U pip
	@backend/.venv/bin/pip install -e backend

migrate-backend:
	@backend/.venv/bin/alembic -c backend/alembic.ini upgrade head

seed-backend:
	@backend/.venv/bin/python -m mspmetro_backend seed

run-backend:
	@backend/.venv/bin/flask --app mspmetro_backend.app run

run-ui:
	@cargo run -p mspmetro-ui

db-up:
	@echo "NO DOCKER: install and start PostgreSQL via your OS package manager."

db-down:
	@echo "NO DOCKER: stop PostgreSQL via your init system (e.g. systemd)."

test:
	@echo "No tests defined for the static pages yet."

lint:
	@echo "No linter configured yet."

fmt:
	@echo "No formatter configured yet."

deploy-edge-eur:
	@ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i 'edge.eur.mspmetro.com,' -u root ops/ansible/site.yml

setup-publisher:
	@python3 -m venv .venv-publisher
	@.venv-publisher/bin/pip install -U pip
	@.venv-publisher/bin/pip install -r scripts/publisher_requirements.txt

build-site:
	@bash scripts/build_site.sh

publish-origin: setup-publisher build-site
	@.venv-publisher/bin/python scripts/publish_s3.py

# Publish to the Scaleway origin used by edges (edge.global).
# Uses AWS_* credentials from the environment or .env.
publish-edge-global: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	AWS_ACCESS_KEY_ID="$${AWS_ACCESS_KEY_ID:-$${SCW_ACCESS_KEY:-}}"; \
	AWS_SECRET_ACCESS_KEY="$${AWS_SECRET_ACCESS_KEY:-$${SCW_SECRET_KEY:-}}"; \
	S3_BUCKET="$${S3_BUCKET:-$${S3_BUCKET_GLOBAL:-$${BUCKET:-}}}"; \
	S3_ENDPOINT_URL="$${S3_ENDPOINT_URL:-$${SCW_ENDPOINT:-https://s3.fr-par.scw.cloud}}"; \
	S3_REGION="$${S3_REGION:-us-east-1}"; \
	ORIGIN_BASE_URL="$${ORIGIN_BASE_URL:-$${EDGE_GLOBAL_ORIGIN:-$${PUBLISH_ORIGIN_GLOBAL:-$${ORIGIN_GLOBAL:-}}}}"; \
	export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_BUCKET S3_ENDPOINT_URL S3_REGION ORIGIN_BASE_URL; \
	.venv-publisher/bin/python scripts/publish_s3.py'

# Publish to the DigitalOcean origin used by edges (edge.world).
# Expects DO_* variables (see .env.example) or the older DO_SPACES_* / S3_BUCKET_WORLD names.
publish-edge-world: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	AWS_ACCESS_KEY_ID="$${DO_AWS_ACCESS_KEY_ID:-$${DO_SPACES_ACCESS_KEY:-}}"; \
	AWS_SECRET_ACCESS_KEY="$${DO_AWS_SECRET_ACCESS_KEY:-$${DO_SPACES_SECRET_KEY:-}}"; \
	S3_BUCKET="$${DO_S3_BUCKET:-$${S3_BUCKET_WORLD:-}}"; \
	S3_ENDPOINT_URL="$${DO_S3_ENDPOINT_URL:-$${DO_SPACES_ENDPOINT:-}}"; \
	S3_REGION="$${DO_S3_REGION:-$${DO_SPACES_REGION:-us-east-1}}"; \
	S3_ADDRESSING_STYLE="$${DO_S3_ADDRESSING_STYLE:-path}"; \
	ORIGIN_BASE_URL="$${DO_ORIGIN_BASE_URL:-$${EDGE_WORLD_ORIGIN:-$${PUBLISH_ORIGIN_WORLD:-$${ORIGIN_WORLD:-}}}}"; \
	export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_BUCKET S3_ENDPOINT_URL S3_REGION S3_ADDRESSING_STYLE ORIGIN_BASE_URL; \
	.venv-publisher/bin/python scripts/publish_s3.py'

# Publish to the third "earth" origin (S3-compatible; provider-agnostic).
# Configure via EARTH_* vars, or S3_BUCKET_EARTH + PUBLISH_ORIGIN_EARTH.
publish-edge-earth: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	AWS_ACCESS_KEY_ID="$${EARTH_AWS_ACCESS_KEY_ID:-$${EARTH_ACCESS_KEY:-$${HETZNER_ACCESS_KEY:-}}}"; \
	AWS_SECRET_ACCESS_KEY="$${EARTH_AWS_SECRET_ACCESS_KEY:-$${EARTH_SECRET_KEY:-$${HETZNER_SECRET_KEY:-}}}"; \
	S3_BUCKET="$${EARTH_S3_BUCKET:-$${S3_BUCKET_EARTH:-$${S3_BUCKET_EUR:-}}}"; \
	S3_ENDPOINT_URL="$${EARTH_S3_ENDPOINT_URL:-$${EARTH_ENDPOINT_URL:-$${EARTH_ENDPOINT:-$${HETZNER_ENDPOINT:-}}}}"; \
	S3_REGION="$${EARTH_S3_REGION:-$${EARTH_REGION:-$${HETZNER_REGION:-us-east-1}}}"; \
	S3_ADDRESSING_STYLE="$${EARTH_S3_ADDRESSING_STYLE:-$${EARTH_ADDRESSING_STYLE:-auto}}"; \
	ORIGIN_BASE_URL="$${EARTH_ORIGIN_BASE_URL:-$${PUBLISH_ORIGIN_EARTH:-$${ORIGIN_EARTH:-}}}"; \
	export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_BUCKET S3_ENDPOINT_URL S3_REGION S3_ADDRESSING_STYLE ORIGIN_BASE_URL; \
	[ -n "$$S3_BUCKET" ] && [ -n "$$S3_ENDPOINT_URL" ] && [ -n "$$ORIGIN_BASE_URL" ] || { echo "earth origin not configured; set EARTH_S3_BUCKET/EARTH_S3_ENDPOINT_URL/EARTH_ORIGIN_BASE_URL (or S3_BUCKET_EARTH/PUBLISH_ORIGIN_EARTH)" >&2; exit 2; }; \
	.venv-publisher/bin/python scripts/publish_s3.py'

publish-origins: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	PUBLISH_VERSION="$${PUBLISH_VERSION:-$$(python3 -c \"from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'))\")}\"; \
	export PUBLISH_VERSION; \
	$(MAKE) publish-edge-global publish-edge-world publish-edge-earth'

deploy-brief:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; cargo build --release --bin cityfeed-puller; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/deploy_brief.yml'

deploy-brief-minio:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; cargo build --release --bin cityfeed-puller; $(MAKE) publish-minio verify-minio-replication publicize-world verify-origins; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/deploy_edges.yml'

rebuild-publish:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/rebuild_publish.yml'

verify-brief:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/verify_brief.yml'

verify-public:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; bash scripts/verify_public.sh'

verify-origins:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; bash scripts/verify_origins.sh'

publish-ipns:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/publish_ipns.yml'

# MinIO publisher host (single-write) + fanout replication.
# Provide the host explicitly:
#   PUBLISHER_HOST=YOURHOST make minio-publisher
minio-publisher:
	@bash -lc 'set -euo pipefail; : "$${PUBLISHER_HOST:?set PUBLISHER_HOST}"; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i "$${PUBLISHER_HOST}," -u root ops/ansible/minio_publisher.yml'

# Configures mc aliases + continuous fanout replication from MinIO to remotes.
# Requires controller env (.env) to contain provider credentials for the remotes.
minio-replication:
	@bash -lc 'set -euo pipefail; : "$${PUBLISHER_HOST:?set PUBLISHER_HOST}"; set -a; [ -f .env ] && source .env; set +a; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i "$${PUBLISHER_HOST}," -u root ops/ansible/minio_replication.yml'

# Publish to MinIO on the publisher host using SSH port-forwarding (CLI-only).
PUBLISHER_SSH ?= root@144.76.5.115
publish-minio: build-site
	@bash scripts/publish_to_minio_over_ssh.sh --host "$(PUBLISHER_SSH)"

verify-minio-replication:
	@ssh "$(PUBLISHER_SSH)" 'set -euo pipefail; source /etc/mspmetro/env; mc alias set minio http://127.0.0.1:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD" --api s3v4 --path auto >/dev/null; mc stat minio/mspmetro-site/manifests/latest.json >/dev/null; sudo -u mspmetro-repl -H mc stat global/pull/manifests/latest.json >/dev/null; sudo -u mspmetro-repl -H mc stat world/mspmetro-world/manifests/latest.json >/dev/null; sudo -u mspmetro-repl -H mc stat earth/mspmetro-eur/manifests/latest.json >/dev/null; echo OK'

# DigitalOcean Spaces often replicates private objects; enforce public-read ACL on the destination.
# (No-op on publishers that don't have the helper installed.)
publicize-world:
	@ssh "$(PUBLISHER_SSH)" 'set -euo pipefail; if systemctl list-unit-files --no-legend | grep -q "^mspmetro-world-publicize\\.service\\b"; then systemctl start mspmetro-world-publicize.service; echo OK; else echo "SKIP: mspmetro-world-publicize.service not installed"; fi'

# DigitalOcean CDN management (requires DIGITALOCEAN_ACCESS_TOKEN in .env).
do-cdn-list:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; python3 scripts/do_cdn.py list'

# Usage:
#   DIGITALOCEAN_ACCESS_TOKEN=... make do-world-cdn-set-domain DO_WORLD_CUSTOM_DOMAIN=world.mspmetro.com DO_WORLD_CERTIFICATE_ID=...
# Or upload a custom cert in one go:
#   make do-world-cdn-set-domain DO_WORLD_CUSTOM_DOMAIN=world.mspmetro.com DO_WORLD_CUSTOM_CERT_NAME=world-mspmetro-com DO_WORLD_CUSTOM_CERT_LEAF=/path/fullchain.pem DO_WORLD_CUSTOM_CERT_KEY=/path/privkey.pem
do-world-cdn-set-domain:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	: "$${DO_WORLD_CUSTOM_DOMAIN:?set DO_WORLD_CUSTOM_DOMAIN}"; \
	ORIGIN="mspmetro-world.sfo3.digitaloceanspaces.com"; \
	ARGS=(set-domain --origin "$$ORIGIN" --custom-domain "$${DO_WORLD_CUSTOM_DOMAIN}" --ttl "$${DO_WORLD_TTL:-3600}"); \
	if [[ -n "$${DO_WORLD_CERTIFICATE_ID:-}" ]]; then ARGS+=(--certificate-id "$${DO_WORLD_CERTIFICATE_ID}"); fi; \
	if [[ -n "$${DO_WORLD_LE_CERT_NAME:-}" ]]; then ARGS+=(--le-cert-name "$${DO_WORLD_LE_CERT_NAME}"); fi; \
	if [[ -n "$${DO_WORLD_CUSTOM_CERT_NAME:-}" ]]; then \
	  : "$${DO_WORLD_CUSTOM_CERT_LEAF:?set DO_WORLD_CUSTOM_CERT_LEAF}"; : "$${DO_WORLD_CUSTOM_CERT_KEY:?set DO_WORLD_CUSTOM_CERT_KEY}"; \
	  ARGS+=(--custom-cert-name "$${DO_WORLD_CUSTOM_CERT_NAME}" --custom-cert-leaf "$${DO_WORLD_CUSTOM_CERT_LEAF}" --custom-cert-key "$${DO_WORLD_CUSTOM_CERT_KEY}"); \
	  if [[ -n "$${DO_WORLD_CUSTOM_CERT_CHAIN:-}" ]]; then ARGS+=(--custom-cert-chain "$${DO_WORLD_CUSTOM_CERT_CHAIN}"); fi; \
	fi; \
	python3 scripts/do_cdn.py "$${ARGS[@]}"'

do-world-cdn-purge:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; python3 scripts/do_cdn.py purge --origin "mspmetro-world.sfo3.digitaloceanspaces.com"'

# Issue a DNS-01 certificate via Scaleway DNS (lego), then upload+attach it to the DO CDN endpoint.
# Requires:
# - DIGITALOCEAN_ACCESS_TOKEN in .env
# - SCW_ACCESS_KEY/SCW_SECRET_KEY/SCW_DEFAULT_PROJECT_ID in .env
# - Domain DNS in Scaleway (so TXT records can be created)
#
# Usage:
#   make do-world-bind-domain DO_WORLD_CUSTOM_DOMAIN=origin-us.mspmetro.com
do-world-bind-domain:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; : "$${DO_WORLD_CUSTOM_DOMAIN:?set DO_WORLD_CUSTOM_DOMAIN}"; bash scripts/do_world_bind_domain.sh "$${DO_WORLD_CUSTOM_DOMAIN}"'
