#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${OUT_DIR:-${root_dir}/build/site}"

mkdir -p "${out_dir}"

rsync -a --delete \
  "${root_dir}/index.html" \
  "${out_dir}/index.html"

for d in static weather metro world neighbors transit events daily how-we-know featured; do
  if [[ -d "${root_dir}/${d}" ]]; then
    rsync -a --delete "${root_dir}/${d}/" "${out_dir}/${d}/"
  fi
done

if [[ -n "${DATABASE_URL:-}" && -x "${root_dir}/backend/.venv/bin/python" ]]; then
  "${root_dir}/backend/.venv/bin/python" -m mspmetro_backend.static_build --out "${out_dir}"
fi

echo "OK: built site into ${out_dir}"
