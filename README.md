# War & Peace — Новости, суммаризация и публикации

Этот репозиторий содержит Telegram-бота и пайплайн для сбора, суммаризации и публикации новостей. 

Документация:
- DEPLOYMENT.md — как запустить
- WARP.md — обзор архитектуры и правила
- doc/STATUS.md — текущее состояние (генерируется: `python3 scripts/docs/generate_status.py`)
- doc/PLANNING.md — агрегатор планов
- doc/ROADMAP.md — направления на 1–2 квартала
- doc/RELEASELOG.md — заметки о релизах

Git hooks:
- Включить версионируемые хуки: `git config core.hooksPath .githooks`
- Pre-commit хук автоматически генерирует doc/STATUS.md и БЛОКИРУЕТ коммит, если документация не обновлена (можно временно обойти `--no-verify`).

## База данных: PostgreSQL только

Проект переведён на PostgreSQL. SQLite более не поддерживается в прод/локальной разработке.

Переменные окружения для подключения:
- Либо единая DATABASE_URL: `postgresql+psycopg://<user>:<password>@<host>:<port>/<db>`
- Либо набор POSTGRES_*: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB

Проверка окружения и подключения:
- Локально: `python3 scripts/validate_env.py` (можно пропустить сетевые проверки `SKIP_ENV_DB_CHECKS=1`)
- В контейнере web: `docker compose exec -T web python3 scripts/validate_env.py`

## Миграции схемы (Alembic)

Alembic использует DATABASE_URL. Конфиг: `alembic.ini`, окружение: `alembic/env.py`.

Базовый цикл:
- Создать/обновить миграцию из моделей (если используете автогенерацию):
  - `alembic revision --autogenerate -m "<описание>"`
- Применить миграции:
  - `alembic upgrade head`
- Откатить:
  - `alembic downgrade -1`

Для выполнения внутри контейнера web (с актуальным окружением):
- `docker compose run --rm -T -v "$PWD:/app" web alembic upgrade head`

Примечание: начальная миграция `alembic/versions/0001_initial.py` — пустая (no-op) и служит базовой отметкой.

## Резервные копии (backup) и восстановление (restore)

Инструменты:
- Резервная копия: `tools/backup.py`
- Восстановление: `tools/restore.py`

Переменные окружения:
- LOCAL_BACKUP_DIR — каталог хранения бэкапов (например, `./backups`)
- AGE_PUBLIC_KEYS — обязательны для шифрования `.env` и опционально для БД
- AGE_SECRET_KEY — необходим для расшифровки `.age` при восстановлении

Примеры команд:
- Бэкап БД PostgreSQL локально (формат pg_dump custom):
  - `python3 tools/backup.py --component db --engine postgres --backend local`
- Бэкап .env (всегда шифруется):
  - `python3 tools/backup.py --component env --backend local`

Восстановление БД PostgreSQL из локальных бэкапов:
- Посмотреть содержимое последнего дампа (без изменений):
  - `python3 tools/restore.py --latest --list`
- «Сухой прогон» (проверка файла и вывод действий, без изменений в БД):
  - `python3 tools/restore.py --latest --dry-run`
- Восстановить в текущую БД (без дропа существующей):
  - `python3 tools/restore.py --latest`
- Опасно: дропнуть БД и восстановить с нуля:
  - `python3 tools/restore.py --latest --drop-existing`
- Восстановить в отдельную БД:
  - `python3 tools/restore.py --latest --db-name warandpeace_test`

Интеграция с cron выполняется из контейнера `cron`, см. docker-compose.yml, переменная `BACKUP_CRON` задаёт расписание.
