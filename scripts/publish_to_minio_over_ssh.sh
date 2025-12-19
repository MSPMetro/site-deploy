#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

usage() {
  cat <<'EOF'
Usage:
  scripts/publish_to_minio_over_ssh.sh --host root@HOST [--site-dir build/site] [--local-port 19000] [--no-site-tree]

Purpose:
  Publish the built static site to MinIO running on the publisher host, using
  an SSH port-forward and MinIO creds stored on the host.

Notes:
  - No GUI required.
  - Does not print passwords.
  - Requires: ssh, python3
  - By default, also uploads the normal site paths (index.html, /static/...) so CDNs can serve the site directly.
EOF
}

host=""
site_dir="build/site"
local_port="19000"
publish_site_tree="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      host="${2:-}"
      shift 2
      ;;
    --site-dir)
      site_dir="${2:-}"
      shift 2
      ;;
    --local-port)
      local_port="${2:-}"
      shift 2
      ;;
    --no-site-tree)
      publish_site_tree="0"
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$host" ]]; then
  echo "error: missing --host" >&2
  usage >&2
  exit 2
fi

if [[ ! -d "$site_dir" ]]; then
  echo "error: site dir not found: $site_dir" >&2
  echo "hint: run scripts/build_site.sh first" >&2
  exit 2
fi

if ! [[ "$local_port" =~ ^[0-9]+$ ]] || (( local_port < 1 || local_port > 65535 )); then
  echo "error: invalid --local-port: $local_port" >&2
  exit 2
fi

creds="$(ssh "$host" 'sudo cat /etc/mspmetro/minio-publish.creds')"
minio_user="$(printf '%s\n' "$creds" | awk -F= '/^MINIO_PUBLISH_USER=/{print $2}')"
minio_pass="$(printf '%s\n' "$creds" | awk -F= '/^MINIO_PUBLISH_PASSWORD=/{print $2}')"
minio_bucket="$(printf '%s\n' "$creds" | awk -F= '/^MINIO_PUBLISH_BUCKET=/{print $2}')"

if [[ -z "$minio_user" || -z "$minio_pass" || -z "$minio_bucket" ]]; then
  echo "error: could not parse /etc/mspmetro/minio-publish.creds on $host" >&2
  exit 2
fi

socket="$(mktemp -u "/tmp/mspmetro-minio-ssh.XXXXXX.sock")"
cleanup() {
  ssh -S "$socket" -O exit "$host" >/dev/null 2>&1 || true
  rm -f "$socket" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ssh -M -S "$socket" -fnNT -L "${local_port}:127.0.0.1:9000" "$host"

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN || true
export AWS_ACCESS_KEY_ID="$minio_user"
export AWS_SECRET_ACCESS_KEY="$minio_pass"
export S3_BUCKET="$minio_bucket"
export S3_ENDPOINT_URL="http://127.0.0.1:${local_port}"
export S3_REGION="${S3_REGION:-us-east-1}"
export S3_ADDRESSING_STYLE="path"
export S3_OBJECT_ACL="none"
export PUBLISH_SITE_TREE="$publish_site_tree"

python3 scripts/publish_s3.py --site-dir "$site_dir"
