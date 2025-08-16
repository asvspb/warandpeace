## План обновления CHANGELOG по последним коммитам

Цель: обновить `doc/CHANGELOG.md` на ветке `develop` на основе коммитов после тега `v1.3.1`. Сформировать секцию Unreleased и подготовить основу для будущего релиза.

### Источник данных
- Базовый тег: `v1.3.1`
- Диапазон коммитов: от `v1.3.1` (исключая) до текущего `HEAD`

### Сортировка по категориям (Conventional-style)
- Added (feat, new docs)
- Changed (refactor, deps, infra)
- Fixed (fix)
- Docs (docs)
- Security (если есть)

### Черновая классификация (по `git log --oneline -n 20`)
- Added:
  - e0552c2 feat: Add web interface for database browsing
  - 025324f feat(backfill): Add --archive-only flag for faster fetching
  - 1af7081 feat: Add network connectivity check and logging
  - 9b9a1cf feat: Add metrics endpoint and robust DB migrations
  - 98e512a feat(docs): Overhaul documentation and add Python 3.11 migration plan
  - 70c879d docs/feat: план оркестрации Gemini и CLI-утилита
  - a9e83fa feat(docs): add AI playbooks and timezone migration plan
- Changed:
  - 7725e05 refactor(logging): Unify log format across the application
  - ab3310b Refactor GEMINI.md into AI executor playbook with structured workflow
  - c51da40 Implement timezone-aware datetime handling with UTC storage
  - 31d6168 Infra: Configure TZ for Moscow timezone migration
  - f092266 build: add click dependency and clarify gemini doc
- Fixed:
  - fcd27c0 fix: генерация резюме для отложенных публикаций
- Docs:
  - 761ea78 docs: обновить CHANGELOG до v1.4.1 и завершить план
  - 0d9282e docs: Mark testing and verification stage as complete
  - 16e4249 docs: добавить планы и правила поддержания документации
- Security:
  - (нет)

### План действий
1) Сформировать секцию `## [Unreleased]` в `doc/CHANGELOG.md` с блоками:
   - Added / Changed / Fixed / Docs / Security
2) Заполнить пункты на основе классификации выше (переформулировать в пользовательскую ценность):
   - прим.: «Добавлен веб‑интерфейс просмотра БД (FastAPI/Jinja), базовая авторизация, метрики»
   - прим.: «Миграция на tz‑aware даты (хранение UTC), подготовка к MSK»
3) Слить однотипные пункты, убрать внутренние детали.
4) Сохранить файл.
5) Запустить `scripts/gemini_cli.py prompt` с текстом секции Unreleased для вычитки/улучшения формулировок.
6) Применить правки по результатам и сохранить.

### Критерии готовности
- `doc/CHANGELOG.md` содержит актуальную секцию Unreleased.
- Формулировки короткие, ориентированы на пользователя.
- Никаких секретов/внутренних путей.
