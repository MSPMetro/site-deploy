#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f /etc/mspmetro/minio-publish.creds ]]; then
  # This is now optional if systemd provides /etc/default/mspmetro-source-publish.
  :
fi

if [[ ! -x /usr/local/bin/minio ]]; then
  echo "minio is not installed on this host (/usr/local/bin/minio missing)" >&2
  exit 2
fi

if ! systemctl is-active --quiet mspmetro-minio.service; then
  echo "minio service is not active (mspmetro-minio.service)" >&2
  exit 2
fi

if [[ ! -x .venv-publisher/bin/python ]]; then
  echo "missing .venv-publisher; run the source_box playbook to provision it" >&2
  exit 2
fi

bash scripts/build_site.sh

if [[ -z "${AWS_ACCESS_KEY_ID:-}" || -z "${AWS_SECRET_ACCESS_KEY:-}" || -z "${S3_BUCKET:-}" ]]; then
  if [[ -r /etc/mspmetro/minio-publish.creds ]]; then
    set -a
    source /etc/mspmetro/minio-publish.creds
    set +a
    export AWS_ACCESS_KEY_ID="${MINIO_PUBLISH_USER:-}"
    export AWS_SECRET_ACCESS_KEY="${MINIO_PUBLISH_PASSWORD:-}"
    export S3_BUCKET="${MINIO_PUBLISH_BUCKET:-}"
    export S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-http://127.0.0.1:9000}"
    export S3_REGION="${S3_REGION:-us-east-1}"
    export S3_ADDRESSING_STYLE="${S3_ADDRESSING_STYLE:-path}"
    export PUBLISH_SITE_TREE="${PUBLISH_SITE_TREE:-1}"
    export S3_OBJECT_ACL="${S3_OBJECT_ACL:-none}"
  fi
fi

if [[ -z "${AWS_ACCESS_KEY_ID:-}" || -z "${AWS_SECRET_ACCESS_KEY:-}" || -z "${S3_BUCKET:-}" ]]; then
  echo "missing publish credentials; expected /etc/default/mspmetro-source-publish or readable /etc/mspmetro/minio-publish.creds" >&2
  exit 2
fi

publish_version="$(
  python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'))"
)"
export PUBLISH_VERSION="$publish_version"

.venv-publisher/bin/python scripts/publish_s3.py --origin-base-url "http://127.0.0.1:9000"
