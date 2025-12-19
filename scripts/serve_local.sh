#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bind_addr="${BIND:-127.0.0.1}"
start_port="${PORT:-8000}"
max_tries="${MAX_TRIES:-20}"

is_port_in_use() {
  local port="$1"
  ss -ltn 2>/dev/null | rg -q ":${port}\\b"
}

pick_port() {
  local port="$start_port"
  local tries=0
  while is_port_in_use "$port"; do
    tries=$((tries + 1))
    if [ "$tries" -ge "$max_tries" ]; then
      echo "error: could not find a free port starting at ${start_port} (tried ${max_tries})" >&2
      exit 1
    fi
    port=$((port + 1))
  done
  echo "$port"
}

port="$(pick_port)"

echo "Serving MSPMetro static site from: ${root_dir}"
echo "Bind: ${bind_addr}"
echo "URL:  http://${bind_addr}:${port}/"
echo "Home: http://${bind_addr}:${port}/index.html"
echo "Pages:"
echo "  - http://${bind_addr}:${port}/weather/"
echo "  - http://${bind_addr}:${port}/metro/"
echo "  - http://${bind_addr}:${port}/world/"
echo "  - http://${bind_addr}:${port}/neighbors/"
echo "  - http://${bind_addr}:${port}/transit/"
echo "  - http://${bind_addr}:${port}/events/"
echo

python3 -m http.server "$port" --bind "$bind_addr" --directory "$root_dir"
