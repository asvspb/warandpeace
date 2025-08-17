Last updated: 2025-08-17
Status: ready

### Python 3.12+ Migration Plan

#### 1) Goals and Scope
- Target runtime: Python 3.12 LTS.
- Keep behaviour identical; no breaking changes for users.
- Modernise code: typing, performance, packaging, CI.

#### 2) Inventory and Impact Analysis
- Runtime entrypoints: `src/bot.py`, `scripts/manage.py`.
- Test suite: `pytest` (all tests must pass).
- Dependencies (requirements.txt):
  - Confirm 3.12 support for all key libraries.
- Docker: base image must be `python:3.12-slim`.

Checklist:
- [ ] Verify upstream packages for Python 3.12 wheels.
- [ ] Note any transitive deps pinning <3.12 (none known now).

#### 3) Codebase Changes
- Typing and syntax:
  - [ ] Use new typing features where appropriate (e.g., `@override` decorator, new generic type syntax).
- Async improvements:
  - [ ] Ensure blocking I/O in async contexts uses `asyncio.to_thread` or explicit thread pool.
- Logging:
  - [ ] Standardise logging config via one place (avoid multiple `basicConfig`).

#### 4) Tooling & CI
- Local env:
  - [ ] Update Makefile/dev docs to use `python3.12` and `venv`.
- Docker:
  - [ ] Switch Dockerfile base to `python:3.12-slim`.
  - [ ] Rebuild image; validate runtime, metrics port exposed.
- CI (if applicable):
  - [ ] Run matrix tests for 3.10 and 3.12 for one release cycle.

#### 5) Dependency Upgrades
- Target minimums known to support 3.12.
- Actions:
  - [ ] Create a branch; bump non-breaking versions and document changes in release notes.
  - [ ] Run `pip-compile` (optional) or freeze to ensure reproducibility.

#### 6) Testing Strategy
- [ ] Run full pytest locally on 3.12.
- [ ] Add stress test for async parsers (concurrency > 1) to catch event-loop issues.
- [ ] Smoke run bot in Docker for 15–30 minutes; verify no regressions.
- [ ] Validate metrics endpoint at `/metrics`.

#### 7) Backward Compatibility and Rollback
- [ ] Keep 3.10 compatibility for one minor release (dual-support) if needed.
- [ ] Tagged release notes with upgrade guide.
- [ ] Rollback plan: pin Docker image back to 3.10 (`docker compose pull && up -d`).

#### 8) Release Plan
- [ ] Feature-freeze branch `py312-migration`.
- [ ] PR with checklist and CI green.
- [ ] Tag `vX.Y.0` with Python 3.12 as baseline.

#### 9) Post‑migration Improvements (optional)
- [ ] Leverage new f-string capabilities.
- [ ] Use sub-interpreters for true parallelism in CPU-bound tasks (future consideration).

#### 10) Risks
- Wheels missing for some deps on ARM/Alpine; mitigate via `manylinux` base or pre-build cache.
- Subtle event-loop blocking in scrapers; mitigated by retry and `to_thread`.
- Telegram client version drift; pin and test job queue behaviour.