#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -d "build/site" ]]; then
  echo "error: missing build/site; run scripts/build_site.sh first" >&2
  exit 2
fi

if [[ -z "${MINIO_S3_ENDPOINT_URL:-}" ]]; then
  echo "error: set MINIO_S3_ENDPOINT_URL (e.g. http://127.0.0.1:9000)" >&2
  exit 2
fi

if [[ -z "${MINIO_S3_BUCKET:-}" ]]; then
  echo "error: set MINIO_S3_BUCKET (e.g. mspmetro-site)" >&2
  exit 2
fi

if [[ -z "${MINIO_AWS_ACCESS_KEY_ID:-}" || -z "${MINIO_AWS_SECRET_ACCESS_KEY:-}" ]]; then
  echo "error: set MINIO_AWS_ACCESS_KEY_ID and MINIO_AWS_SECRET_ACCESS_KEY" >&2
  exit 2
fi

python_venv="${repo_root}/.venv-publisher"
if [[ ! -x "${python_venv}/bin/python" ]]; then
  echo "setting up publisher venv..." >&2
  python3 -m venv "$python_venv"
  "${python_venv}/bin/pip" install -U pip >/dev/null
  "${python_venv}/bin/pip" install -r scripts/publisher_requirements.txt >/dev/null
fi

export AWS_ACCESS_KEY_ID="${MINIO_AWS_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${MINIO_AWS_SECRET_ACCESS_KEY}"
export S3_BUCKET="${MINIO_S3_BUCKET}"
export S3_ENDPOINT_URL="${MINIO_S3_ENDPOINT_URL}"
export S3_REGION="${MINIO_S3_REGION:-us-east-1}"
export S3_ADDRESSING_STYLE="${MINIO_S3_ADDRESSING_STYLE:-path}"
export ORIGIN_BASE_URL="${MINIO_ORIGIN_BASE_URL:-}"

"${python_venv}/bin/python" scripts/publish_s3.py
