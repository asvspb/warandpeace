Last updated: 2025-08-16
Status: ready

### Python 3.11+ Migration Plan

#### 1) Goals and Scope
- Target runtime: Python 3.11 LTS (or newer minor).
- Keep behaviour identical; no breaking changes for users.
- Modernise code: typing, performance, packaging, CI.

#### 2) Inventory and Impact Analysis
- Runtime entrypoints: `src/bot.py`, `scripts/manage.py`.
- Test suite: `pytest` (22 tests currently passing).
- Dependencies (requirements.txt):
  - Confirm 3.11 support: python-telegram-bot, requests, bs4, python-dotenv, google-generativeai, tenacity, APScheduler, click, mistralai, sqlalchemy, psycopg2-binary, alembic, prometheus-client.
- Docker: base image must be `python:3.11-slim`.

Checklist:
- [ ] Verify upstream packages for Python 3.11 wheels.
- [ ] Note any transitive deps pinning <3.11 (none known now).

#### 3) Codebase Changes
- Typing and syntax:
  - [ ] Use `list[str] | None` and `typing.Self` where helpful (3.11 supports PEP 604 natively).
  - [ ] Remove `from __future__ import annotations` if present (not needed).
- Async improvements:
  - [ ] Ensure blocking I/O in async contexts uses `asyncio.to_thread` or explicit thread pool.
- Logging:
  - [ ] Standardise logging config via one place (avoid multiple `basicConfig`).
- Dataclasses (optional):
  - [ ] Consider replacing dict DTOs with `@dataclass` for stronger typing (follow-up task).

#### 4) Tooling & CI
- Local env:
  - [ ] Update Makefile/dev docs to use `python3.11` and `venv`.
- Docker:
  - [ ] Switch Dockerfile base to `python:3.11-slim`.
  - [ ] Rebuild image; validate runtime, metrics port exposed.
- CI (if applicable):
  - [ ] Run matrix tests for 3.10 and 3.11 for one release cycle.

#### 5) Dependency Upgrades
- Target minimums known to support 3.11:
  - `tenacity>=8.2`, `APScheduler>=3.10`, `click>=8.1`, `sqlalchemy>=2.0` (if/when moving to SQLA 2.x API), `prometheus-client>=0.16`, `requests>=2.31`.
- Actions:
  - [ ] Create a branch; bump non-breaking versions and document changes in release notes.
  - [ ] Run `pip-compile` (optional) or freeze to ensure reproducibility.

#### 6) Testing Strategy
- [ ] Run full pytest locally on 3.11.
- [ ] Add stress test for async parsers (concurrency > 1) to catch event-loop issues.
- [ ] Smoke run bot in Docker for 15–30 minutes; verify no regressions.
- [ ] Validate metrics endpoint at `/metrics`.

#### 7) Backward Compatibility and Rollback
- [ ] Keep 3.10 compatibility for one minor release (dual-support) if needed.
- [ ] Tagged release notes with upgrade guide.
- [ ] Rollback plan: pin Docker image back to 3.10 (`docker compose pull && up -d`).

#### 8) Release Plan
- [ ] Feature-freeze branch `py311-migration`.
- [ ] PR with checklist and CI green.
- [ ] Tag `vX.Y.0` with Python 3.11 as baseline.

#### 9) Post‑migration Improvements (optional)
- [ ] Adopt `tomllib` (3.11 stdlib) if config in TOML in future.
- [ ] Use `taskgroups` or `asyncio.timeout` (3.11) for async coordination and cancellation.
- [ ] Leverage `typing` enhancements (Variadic generics, `typing.TypeGuard`) where beneficial.

#### 10) Risks
- Wheels missing for some deps on ARM/Alpine; mitigate via `manylinux` base or pre-build cache.
- Subtle event-loop blocking in scrapers; mitigated by retry and `to_thread`.
- Telegram client version drift; pin and test job queue behaviour.
