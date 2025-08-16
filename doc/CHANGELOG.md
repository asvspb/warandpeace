# Changelog

All notable changes to this project will be documented in this file.

## [1.5.0] - 2025-08-16

### Added
- Web-based database browser (FastAPI + Jinja2): list/detail pages, duplicates, DLQ; Basic Auth and metrics.
- Gemini CLI for console orchestration: `scripts/gemini_cli.py` (prompt, summarize-file, models:list, keys:check, keys:rotate) plus ops runbook.
- Metrics endpoint and reinforced DB migrations with standard Prometheus metrics.
- `--archive-only` flag to speed up historical ingestion/backup flows.

### Changed
- Unified log format across the application for better readability and analysis.
- Migrated to timezone‑aware datetimes: UTC storage, MSK presentation; `TZ` configured in containers.
- Docs updated: `GEMINI.md` refined, AI playbooks added (execution and review/planning).
- Documentation standardized: added meta-blocks (Last updated/Status) to plans, synchronized `doc/PLANNING.md` aggregator and added prioritized execution order.
- Dependencies updated: `click` (CLI), `mistralai` (summarization fallback).

### Fixed
- Reliable summary generation for scheduled publications (improved resilience and retries).

## [1.4.1] - 2025-08-14

### Changed
- **Улучшено логирование:** Завершён переход на новую систему логирования. В логах теперь отображается только полезная информация о найденных и опубликованных статьях, "шум" от пустых проверок убран.
- **Повышена стабильность:** Добавлена упреждающая проверка сетевого подключения к серверам Telegram при старте бота.

### Fixed
- Исправлена ошибка, из-за которой бот мог упасть при попытке обработать ошибку `NoneType` в глобальном обработчике.

## [Unreleased]

### Added

### Changed

### Fixed

