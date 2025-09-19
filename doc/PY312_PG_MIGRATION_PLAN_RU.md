# Архив: План миграции на Python 3.12 и PostgreSQL (выполнено)

Статус: завершено в релизе v2.0.

Что сделано по плану:
- Python 3.12 — базовый runtime (Dockerfile)
- PostgreSQL — основной backend; dual-backend через SQLAlchemy (SQLite/PG)
- Инициализация схемы через SQLAlchemy (src/db/schema.py)
- Скрипт миграции данных из SQLite в Postgres (tools/migrate_sqlite_to_postgres.py)
- Обновлены .env.example, docker-compose.yml, requirements.txt
- Smoke‑тесты и pytest — зелёные

Актуальная документация:
- DEPLOYMENT.md — запуск и переменные
- WARP.md — архитектура и слои
- doc/BEST_PRACTICES.md — практики и соглашения

Исторические чек‑листы и черновики удалены для краткости. См. git log релиза v2.0.

Цели
- [ ] Перейти на Python 3.12 (docker-образ и локальная разработка)
- [ ] Ввести PostgreSQL как основное хранилище (сохранив возможность локально работать на SQLite)
- [ ] Внедрить слой доступа к БД на SQLAlchemy 2.x (Core) с двустворчатой поддержкой: DATABASE_URL→Postgres, иначе SQLite
- [ ] Обеспечить воспроизводимость, метрики и обратимость (чёткий rollback)

Правила выполнения
- После каждого этапа:
  - [ ] Покрыть изменения тестами (pytest -q), минимум smoke + критические пути
  - [ ] Пересобрать и перезапустить контейнеры (docker compose up --build -d)
  - [ ] Проверить стабильность по логам и /metrics (и /healthz)
  - [ ] Предложить зафиксировать изменения в git (commit) и, по необходимости, push/PR

Легенда чекбоксов
- [ ] Не выполнено
- [x] Выполнено
- [~] В процессе/частично

Этап 0 — Подготовка (текущий)
- [x] Согласовать стек: SQLAlchemy 2.x + psycopg 3.x
- [x] Создать рабочую ветку py312-pg-migration
- [x] Подготовить данный план и добавить в репозиторий (doc/)
- Контрольные точки этапа 0:
  - [x] pytest -q (без изменений логики — sanity)
  - [x] docker compose ps (кластер живёт как прежде)
  - [x] Предложить commit в git (план)

Этап 1 — Переход на Python 3.12 (без изменения логики) [1 день]
Задачи:
- [x] Обновить Dockerfile на base image python:3.12-slim
- [x] Пересобрать образ и убедиться, что метрики/бот/web стартуют
- [x] Прогнать pytest -q локально (чистая venv); контейнерная проверка — через запуск web и health
Проверка и стабилизация:
- [x] docker compose up --build -d; docker compose ps; docker compose logs -f (выборочно)
- [x] /metrics (бот), /healthz (web)
Сохранение:
- [ ] git add/commit "Stage 1: Python 3.12 base"

Этап 2 — Добавить Postgres в docker-compose [0.5–1 день]
Задачи:
- [x] Добавить сервис postgres (image: postgres:16-alpine) с volume ./pgdata, healthcheck pg_isready
- [x] Расширить .env.example: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, DATABASE_URL
- [x] Для сервисов web и telegram-bot добавить переменную DATABASE_URL (пока пустую в .env)
Проверка и стабилизация:
- [x] docker compose up -d postgres; дождаться health=healthy
- [x] docker compose exec postgres pg_isready -U $POSTGRES_USER -d $POSTGRES_DB
- [x] pytest -q (поведение прежнее, т.к. DATABASE_URL ещё не задан)
Сохранение:
- [ ] git add/commit "Stage 2: Compose: Postgres service + env example"

Этап 3 — Зависимости и адаптер подключения (SQLAlchemy) [1–2 дня]
Задачи:
- [x] Добавить в requirements.txt: SQLAlchemy==2.0.x, psycopg[binary]==3.2.x
- [x] Новый модуль подключения, напр. src/db/engine.py:
      - [x] create_engine_from_env(): если os.getenv("DATABASE_URL") → engine(PSQL), иначе engine(SQLite)
      - [x] Контекстный менеджер get_connection() с begin()
- [x] Обновить .dockerignore, исключить pgdata из контекста сборки
- [ ] Сохранить существующий API src/database.py, но перепровести внутренние вызовы через SQLAlchemy connection.execute(text(...)) постепенно (без изменения внешних сигнатур)
Проверка и стабилизация:
- [x] pytest -q с SQLite (DATABASE_URL не задан)
- [x] docker compose build (обновление образов с новыми зависимостями)
- [x] Тест подключения движка (локально) через SQLite DATABASE_URL
Сохранение:
- [ ] git add/commit "Stage 3: SQLAlchemy engine + dual-backend wiring (SQLite default)"

Этап 4 — DDL и совместимость SQL для Postgres [1–2 дня]
Задачи:
- [x] Реализовать создание схемы через SQLAlchemy (метаданные + create_all)
      - [x] id автонумерация, уникальные ключи и индексы
      - [x] TIMESTAMPTZ/DateTime(timezone=True) для временных полей
      - [x] Составные PK/индексы для api_usage_daily, уникальные ключи для URL/credential_id
- [ ] Заменить специфичные для SQLite функции на PG-эквиваленты в DML/SELECT (при переключении рантайма)
      - [ ] substr → substring/date_trunc
      - [ ] CURRENT_TIMESTAMP → NOW()
      - [ ] INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING/UPDATE
- [x] Сохранить поддержку SQLite: схема создаётся и там, и там
Проверка и стабилизация:
- [ ] pytest -q с DATABASE_URL=postgres://... (PG)
- [x] pytest -q без DATABASE_URL (SQLite) — режим зелёный
- [x] docker compose up --build -d; health веб-компонента OK
Сохранение:
- [ ] git add/commit "Stage 4: DDL + SQL compatibility for PG & SQLite"

Этап 5 — Скрипт переноса данных tools/migrate_sqlite_to_postgres.py [1–2 дня]
Задачи:
- [x] Реализовать перенос таблиц партиями (ORDER BY ROWID в SQLite):
      - [x] articles (ON CONFLICT (canonical_link) DO UPDATE ...)
      - [x] pending_publications (UNIQUE url)
      - [x] dlq, digests
      - [x] api_usage_daily; api_usage_events — опционально
      - [x] backfill_progress (единственная запись id=1), sessions, session_stats*
- [x] Добавить проверки количества строк (summary в конце)
Проверка и стабилизация:
- [x] Dry-run на небольшом срезе (LIMIT) с SQLite→SQLite (валидация логики)
- [x] Инициализация схемы в PG (через web-контейнер)
- [x] Частичный перенос: articles (5000), sessions, session_stats*, backfill_progress, api_usage_daily (upsert)
- [x] Верификация COUNT в PG (articles=5000, api_usage_daily≈7 уникальных строк, sessions=47, session_stats_daily=1)
- [x] Полный перенос статей (158599 rows), сверка количеств — OK
- [ ] pytest -q с PG (DATABASE_URL установлен) — после переключения рантайма (Этап 6)
Сохранение:
- [ ] git add/commit "Stage 5: Data migration script + full transfer & checks"

Этап 6 — Переключение рантайма на Postgres [0.5–1 день]
Задачи:
- [ ] В .env выставить DATABASE_URL=postgresql+psycopg://wp:${WP_DB_PASSWORD}@postgres:5432/warandpeace
- [ ] Остановить на время миграции процесс публикаций (бот) → выполнить перенос → включить
Проверка и стабилизация:
- [ ] docker compose up --build -d; убедиться, что web/бот используют PG
- [ ] Небольшой прогон backfill + суммаризация + публикация (smoke)
- [ ] /metrics, отчёты UI (дубликаты, DLQ, usage)
Сохранение:
- [ ] git add/commit "Stage 6: Switch runtime to PG"

Этап 7 — Бэкапы и операционка [0.5 дня]
Задачи:
- [ ] Включить pg_dump: либо установить postgresql-client в образ cron, либо sidecar
- [ ] Обновить tools/backup.py, чтобы поддерживал component=db engine=postgres
Проверка и стабилизация:
- [ ] Ручной запуск бэкапа; проверка файла .dump
- [ ] Восстановление на чистую БД (smoke)
Сохранение:
- [ ] git add/commit "Stage 7: Postgres backups"

Этап 8 — Чистка и документация [0.5 дня]
Задачи:
- [ ] Документировать переменные и команды в DEPLOYMENT.md и .env.example
- [ ] Оставить локальную возможность SQLite для dev/pytest, но задокументировать, что прод=PG
- [ ] Опционально: удалить mounts ./database из сервисов (кроме режима dev)
Проверка и стабилизация:
- [ ] pytest -q; docker compose up --build -d
Сохранение:
- [ ] git add/commit "Stage 8: Docs & cleanup"

Этап 9 — Rollback-план [чёткие шаги]
- [ ] Если нужно откатиться: убрать DATABASE_URL из .env и перезапустить — вернёмся на SQLite
- [ ] Для PG отката: остановить бота, переключить env, перезапустить, убедиться, что веб/UI корректно работает с SQLite
- [ ] Хранить актуальный файловый бэкап SQLite (существующие инструменты остаются)

Этап 10 — Выпуск
- [ ] Открыть PR из py312-pg-migration; дождаться ревью
- [ ] Смёрджить; задокументировать релиз (миграционные шаги и переменные)
- [ ] Тег релиза

Контрольные команды (шпаргалка)
- pytest
  - pytest -q
  - pytest -q -k "parse_custom_date" (пример)
- Docker
  - docker compose up --build -d
  - docker compose ps
  - docker compose logs -f web | telegram-bot
- Postgres
  - docker compose exec postgres pg_isready -U $POSTGRES_USER -d $POSTGRES_DB
- Переменные
  - DATABASE_URL=postgresql+psycopg://wp:${WP_DB_PASSWORD}@postgres:5432/warandpeace

Заметки по совместимости
- Хранение времени — UTC (TIMESTAMPTZ), вывод — Europe/Moscow (как в репозитории)
- Не блокировать event loop в async-коде; сетевые вызовы — с таймаутами/ретраями
- Для upsert: использовать ON CONFLICT(canonical_link) DO UPDATE в PG и ON CONFLICT ... DO NOTHING там, где нужна идемпотентность
