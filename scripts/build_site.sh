#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${OUT_DIR:-${root_dir}/build/site}"

mkdir -p "${out_dir}"

rsync -a --delete \
  "${root_dir}/index.html" \
  "${out_dir}/index.html"

for d in static weather metro world neighbors transit events daily how-we-know featured credits; do
  if [[ -d "${root_dir}/${d}" ]]; then
    rsync -a --delete "${root_dir}/${d}/" "${out_dir}/${d}/"
  fi
done

if [[ -d "${root_dir}/cables" ]]; then
  echo "Building cables..." >&2
  (cd "${root_dir}/cables" && make build)

  mkdir -p "${out_dir}/cables/pdf"
  rsync -a --delete "${root_dir}/cables/build/html/" "${out_dir}/cables/"
  rsync -a --delete "${root_dir}/cables/build/pdf/" "${out_dir}/cables/pdf/"
  rsync -a --delete "${root_dir}/cables/build/feed.xml" "${out_dir}/cables/feed.xml"
fi

if [[ -n "${DATABASE_URL:-}" && -x "${root_dir}/backend/.venv/bin/python" ]]; then
  "${root_dir}/backend/.venv/bin/python" -m mspmetro_backend.static_build --out "${out_dir}"
fi

build_time_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
build_commit="$(git -C "${root_dir}" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
build_host="$(hostname)"
cat > "${out_dir}/health.txt" <<EOF
build_time_utc=${build_time_utc}
build_commit=${build_commit}
build_host=${build_host}
served_by=[[ env "HOSTNAME" ]]
EOF

echo "OK: built site into ${out_dir}"
