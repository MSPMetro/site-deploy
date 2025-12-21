.PHONY: setup run run-static run-backend setup-backend migrate-backend seed-backend run-ui db-up db-down test lint fmt
.PHONY: deploy-edge-eur setup-publisher build-site publish-origin publish-edge-global publish-edge-do publish-edge-het publish-origins deploy-brief deploy-edges verify-brief verify-public publish-ipns yolo health
.PHONY: verify-origins
.PHONY: minio-publisher minio-replication publish-minio verify-minio-replication publicize-origin-do deploy-brief-minio
.PHONY: do-cdn-list do-origin-do-cdn-set-domain do-origin-do-cdn-purge
.PHONY: do-origin-do-bind-domain
.PHONY: rebuild-publish

export PUBLISH_VERSION ?= $(shell python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))')

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
	@ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i 'edge-eur.mspmetro.com,' -u root ops/ansible/site.yml

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
	S3_ADDRESSING_STYLE="$${S3_ADDRESSING_STYLE:-$${SCW_S3_ADDRESSING_STYLE:-auto}}"; \
	ORIGIN_BASE_URL="$${ORIGIN_BASE_URL:-$${EDGE_GLOBAL_ORIGIN:-$${PUBLISH_ORIGIN_GLOBAL:-$${ORIGIN_GLOBAL:-}}}}"; \
	export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_BUCKET S3_ENDPOINT_URL S3_REGION S3_ADDRESSING_STYLE ORIGIN_BASE_URL; \
	.venv-publisher/bin/python scripts/publish_s3.py'

# Publish to the DigitalOcean origin used by edges (origin-do).
# Expects DO_* variables (see .env.example).
publish-edge-do: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	AWS_ACCESS_KEY_ID="$${DO_AWS_ACCESS_KEY_ID:-$${DO_SPACES_ACCESS_KEY:-}}"; \
	AWS_SECRET_ACCESS_KEY="$${DO_AWS_SECRET_ACCESS_KEY:-$${DO_SPACES_SECRET_KEY:-}}"; \
	S3_BUCKET="$${DO_S3_BUCKET:-}"; \
	S3_ENDPOINT_URL="$${DO_S3_ENDPOINT_URL:-$${DO_SPACES_ENDPOINT:-}}"; \
	S3_REGION="$${DO_S3_REGION:-$${DO_SPACES_REGION:-us-east-1}}"; \
	S3_ADDRESSING_STYLE="$${DO_S3_ADDRESSING_STYLE:-path}"; \
	ORIGIN_BASE_URL="$${DO_ORIGIN_BASE_URL:-$${PUBLISH_ORIGIN_DO:-}}"; \
	export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_BUCKET S3_ENDPOINT_URL S3_REGION S3_ADDRESSING_STYLE ORIGIN_BASE_URL; \
	.venv-publisher/bin/python scripts/publish_s3.py'

# Publish to the third origin (S3-compatible; provider-agnostic, typically Hetzner).
# Configure via HETZNER_* vars or PUBLISH_ORIGIN_HET.
publish-edge-het: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	AWS_ACCESS_KEY_ID="$${HETZNER_ACCESS_KEY:-}"; \
	AWS_SECRET_ACCESS_KEY="$${HETZNER_SECRET_KEY:-}"; \
	S3_BUCKET="$${HETZNER_S3_BUCKET:-$${S3_BUCKET_EUR:-}}"; \
	S3_ENDPOINT_URL="$${HETZNER_S3_ENDPOINT_URL:-$${HETZNER_ENDPOINT:-}}"; \
	S3_REGION="$${HETZNER_S3_REGION:-$${HETZNER_REGION:-us-east-1}}"; \
	S3_ADDRESSING_STYLE="$${HETZNER_S3_ADDRESSING_STYLE:-auto}"; \
	ORIGIN_BASE_URL="$${HET_ORIGIN_BASE_URL:-$${PUBLISH_ORIGIN_HET:-}}"; \
	export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY S3_BUCKET S3_ENDPOINT_URL S3_REGION S3_ADDRESSING_STYLE ORIGIN_BASE_URL; \
	[ -n "$$S3_BUCKET" ] && [ -n "$$S3_ENDPOINT_URL" ] && [ -n "$$ORIGIN_BASE_URL" ] || { echo "origin-het not configured; set HETZNER_S3_BUCKET/HETZNER_S3_ENDPOINT_URL/HET_ORIGIN_BASE_URL (or PUBLISH_ORIGIN_HET)" >&2; exit 2; }; \
	.venv-publisher/bin/python scripts/publish_s3.py'

publish-origins: setup-publisher build-site
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	$(MAKE) publish-edge-global publish-edge-do publish-edge-het'

deploy-brief:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; cargo build --release --bin cityfeed-puller; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/deploy_brief.yml'

deploy-edges:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; cargo build --release --bin cityfeed-puller; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/deploy_edges.yml'

yolo: publish-origins deploy-edges health
	@echo "OK: build + publish + edge deploy complete."

deploy-brief-minio:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; cargo build --release --bin cityfeed-puller; $(MAKE) publish-minio verify-minio-replication publicize-origin-do verify-origins; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/deploy_edges.yml'

rebuild-publish:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/rebuild_publish.yml'

verify-brief:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; ANSIBLE_CONFIG=ops/ansible/ansible.cfg ansible-playbook -i ops/ansible/inventory.ini ops/ansible/verify_brief.yml'

verify-public:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; bash scripts/verify_public.sh'

verify-origins:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; bash scripts/verify_origins.sh'

health:
	@bash scripts/health_check.sh

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
# Default to the stable hostname (IPs can change).
PUBLISHER_SSH ?= root@source.mspmetro.com
publish-minio: build-site
	@bash scripts/publish_to_minio_over_ssh.sh --host "$(PUBLISHER_SSH)"

verify-minio-replication:
	@ssh "$(PUBLISHER_SSH)" 'set -euo pipefail; source /etc/mspmetro/env; mc alias set minio http://127.0.0.1:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD" --api s3v4 --path auto >/dev/null; mc stat minio/mspmetro-site/manifests/latest.json >/dev/null; for n in global origin-do origin-het; do f="/etc/default/mspmetro-minio-replicate-$${n}"; if [[ -f "$$f" ]]; then source "$$f"; sudo -u mspmetro-repl -H mc stat "$${DST_ALIAS}/$${DST_BUCKET}/manifests/latest.json" >/dev/null; fi; done; echo OK'

# DigitalOcean Spaces often replicates private objects; enforce public-read ACL on the destination.
# (No-op on publishers that don't have the helper installed.)
publicize-origin-do:
	@ssh "$(PUBLISHER_SSH)" 'set -euo pipefail; if systemctl list-unit-files --no-legend | grep -q "^mspmetro-origin-do-publicize\\.service\\b"; then systemctl start mspmetro-origin-do-publicize.service; echo OK; else echo "SKIP: mspmetro-origin-do-publicize.service not installed"; fi'

# DigitalOcean CDN management (requires DIGITALOCEAN_ACCESS_TOKEN in .env).
do-cdn-list:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; python3 scripts/do_cdn.py list'

# Usage:
#   DIGITALOCEAN_ACCESS_TOKEN=... make do-origin-do-cdn-set-domain DO_ORIGIN_CUSTOM_DOMAIN=origin-do.mspmetro.com DO_ORIGIN_HOST=origin-do.sfo3.digitaloceanspaces.com DO_ORIGIN_CERTIFICATE_ID=...
# Or upload a custom cert in one go:
#   make do-origin-do-cdn-set-domain DO_ORIGIN_CUSTOM_DOMAIN=origin-do.mspmetro.com DO_ORIGIN_HOST=origin-do.sfo3.digitaloceanspaces.com DO_ORIGIN_CUSTOM_CERT_NAME=origin-do-mspmetro-com DO_ORIGIN_CUSTOM_CERT_LEAF=/path/fullchain.pem DO_ORIGIN_CUSTOM_CERT_KEY=/path/privkey.pem
do-origin-do-cdn-set-domain:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; \
	: "$${DO_ORIGIN_CUSTOM_DOMAIN:?set DO_ORIGIN_CUSTOM_DOMAIN}"; \
	: "$${DO_ORIGIN_HOST:?set DO_ORIGIN_HOST}"; \
	ARGS=(set-domain --origin "$${DO_ORIGIN_HOST}" --custom-domain "$${DO_ORIGIN_CUSTOM_DOMAIN}" --ttl "$${DO_ORIGIN_TTL:-3600}"); \
	if [[ -n "$${DO_ORIGIN_CERTIFICATE_ID:-}" ]]; then ARGS+=(--certificate-id "$${DO_ORIGIN_CERTIFICATE_ID}"); fi; \
	if [[ -n "$${DO_ORIGIN_LE_CERT_NAME:-}" ]]; then ARGS+=(--le-cert-name "$${DO_ORIGIN_LE_CERT_NAME}"); fi; \
	if [[ -n "$${DO_ORIGIN_CUSTOM_CERT_NAME:-}" ]]; then \
	  : "$${DO_ORIGIN_CUSTOM_CERT_LEAF:?set DO_ORIGIN_CUSTOM_CERT_LEAF}"; : "$${DO_ORIGIN_CUSTOM_CERT_KEY:?set DO_ORIGIN_CUSTOM_CERT_KEY}"; \
	  ARGS+=(--custom-cert-name "$${DO_ORIGIN_CUSTOM_CERT_NAME}" --custom-cert-leaf "$${DO_ORIGIN_CUSTOM_CERT_LEAF}" --custom-cert-key "$${DO_ORIGIN_CUSTOM_CERT_KEY}"); \
	  if [[ -n "$${DO_ORIGIN_CUSTOM_CERT_CHAIN:-}" ]]; then ARGS+=(--custom-cert-chain "$${DO_ORIGIN_CUSTOM_CERT_CHAIN}"); fi; \
	fi; \
	python3 scripts/do_cdn.py "$${ARGS[@]}"'

do-origin-do-cdn-purge:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; : "$${DO_ORIGIN_HOST:?set DO_ORIGIN_HOST}"; python3 scripts/do_cdn.py purge --origin "$${DO_ORIGIN_HOST}"'

# Issue a DNS-01 certificate via Scaleway DNS (lego), then upload+attach it to the DO CDN endpoint.
# Requires:
# - DIGITALOCEAN_ACCESS_TOKEN in .env
# - SCW_ACCESS_KEY/SCW_SECRET_KEY/SCW_DEFAULT_PROJECT_ID in .env
# - Domain DNS in Scaleway (so TXT records can be created)
#
# Usage:
#   make do-origin-do-bind-domain DO_ORIGIN_CUSTOM_DOMAIN=origin-do.mspmetro.com DO_ORIGIN_HOST=origin-do.sfo3.digitaloceanspaces.com
do-origin-do-bind-domain:
	@bash -lc 'set -euo pipefail; set -a; [ -f .env ] && source .env; set +a; : "$${DO_ORIGIN_CUSTOM_DOMAIN:?set DO_ORIGIN_CUSTOM_DOMAIN}"; bash scripts/do_origin_do_bind_domain.sh "$${DO_ORIGIN_CUSTOM_DOMAIN}"'
