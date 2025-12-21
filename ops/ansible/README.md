# Ansible: SSR stack on an edge host

This playbook deploys the **Rust UI (SSR)** + **Flask backend** onto an edge host that already serves the static site with Caddy.

It is designed to be safe for testing:

- UI is exposed at `/ui/` (does not replace the static site `/`)
- backend is exposed only at `/api/v1/*` (does not replace existing `/api*` handlers)
- both services bind to `127.0.0.1` and are reverse-proxied by Caddy

## Run

From the repo root:

```bash
ANSIBLE_CONFIG=ops/ansible/ansible.cfg \
ansible-playbook -i 'edge-eur.mspmetro.com,' -u root ops/ansible/site.yml
```

## Rebuild + Publish + Update Edges (CLI-only)

To run the full pipeline (publish on Source Box, then have edges pull), use:

```bash
make rebuild-publish
```

Or directly:

```bash
ANSIBLE_CONFIG=ops/ansible/ansible.cfg \
ansible-playbook -i ops/ansible/inventory.ini ops/ansible/rebuild_publish.yml
```

Override defaults (example):

```bash
ANSIBLE_CONFIG=ops/ansible/ansible.cfg \
ansible-playbook -i 'edge-eur.mspmetro.com,' -u root ops/ansible/site.yml \
  --extra-vars 'mspmetro_db_password=REDACTED mspmetro_ui_port=8090'
```

## What it installs

- Repo checkout to `mspmetro_repo_dir` (default `/opt/mspmetro-ssr/cityfeed_pull`)
- UI binary to `/usr/local/bin/mspmetro-ui`
- Backend venv at `{{ mspmetro_repo_dir }}/backend/.venv`
- Systemd units:
  - `mspmetro-backend.service`
  - `mspmetro-ui.service`
- Env files:
  - `/etc/default/mspmetro-backend`
  - `/etc/default/mspmetro-ui`
- Caddy patch:
  - adds `handle_path /ui*` → `127.0.0.1:{{ mspmetro_ui_port }}`
  - adds `/api/v1/*` → `127.0.0.1:{{ mspmetro_backend_port }}`
