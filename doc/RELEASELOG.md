# RELEASELOG — заметки о релизах

## v2.0 (2025-09-19)
- Python 3.12 — базовый runtime (Dockerfile)
- PostgreSQL — основной backend; dual-backend через SQLAlchemy (SQLite/PG)
- Схема БД через SQLAlchemy (src/db/schema.py)
- Скрипт миграции данных (tools/migrate_sqlite_to_postgres.py)
- Обновлены .env.example, docker-compose.yml, requirements.txt
- Smoke‑тесты и pytest — зелёные

Сопутствующие изменения в документации:
- WARP.md, DEPLOYMENT.md, BEST_PRACTICES.md — обновлены под новый стек
- Добавлен агрегатор PLANNING.md и ROADMAP.md
- Автогенерация STATUS.md (scripts/docs/generate_status.py)
