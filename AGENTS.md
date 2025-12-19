# Repository Guidelines

## Project Status

This repository is currently uninitialized (only `.git/` is present and there is no commit history yet). Use this document as the baseline contributor guide while the first project scaffolding is added.

## Project Structure & Module Organization

Adopt a predictable layout so tooling and CI are easy to add later:

- `src/` — application/library code
- `tests/` — automated tests mirroring `src/` structure
- `scripts/` — one-off utilities (keep small and documented)
- `data/` — local/dev sample data only (never commit secrets or large exports)
- `docs/` — longer design notes or runbooks

## Build, Test, and Development Commands

No build/test commands are defined yet. When introducing the first runtime/toolchain, add a single “happy path” set of commands and keep them stable. Recommended conventions:

- `make setup` — install dependencies
- `make run` — run locally
- `make test` — execute unit tests
- `make lint` / `make fmt` — lint and auto-format

If you don’t use `make`, provide equivalents in the root `README.md` (e.g., `python -m ...`, `npm run ...`).

## Coding Style & Naming Conventions

- Use 2 or 4 spaces consistently (match the dominant language/toolchain once added).
- Prefer descriptive names: `snake_case` for files/functions (Python), `kebab-case` for scripts/CLI entrypoints.
- Add a formatter/linter early (and run it in CI) to avoid style drift.

## Testing Guidelines

- Put tests under `tests/` and name them consistently (e.g., `test_*.py` for pytest or `*.test.ts` for TypeScript).
- Keep tests fast and deterministic; avoid network calls by default.

## Commit & Pull Request Guidelines

There is no established commit convention yet. Use Conventional Commits until the project history indicates otherwise:

- Examples: `feat: add initial ingester`, `fix: handle empty payload`, `docs: add setup notes`

PRs should include: a clear description, how to run/verify, and any config changes (plus screenshots/log snippets when relevant).

## Security & Configuration

- Never commit secrets. Use `.env` locally and commit `.env.example` with safe placeholders.
- Document required environment variables in `README.md` as they are introduced.

