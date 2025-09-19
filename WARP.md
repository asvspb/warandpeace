# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## 1) Часто используемые команды

- Подготовка локального окружения (Python 3.12+):
  - python -m venv .venv && source .venv/bin/activate
  - pip install -r requirements.txt
  - cp .env.example .env  # заполните переменные окружения согласно примеру

- Локальный запуск компонентов без Docker:
  - Бот: python src/bot.py
  - Веб-интерфейс (FastAPI, dev): uvicorn src.webapp.server:app --reload --port 8080

- Docker/Compose (рекомендуется для воспроизводимости):
  - Сборка и запуск: docker compose up --build -d
  - Проверка статуса: docker compose ps
  - Логи по сервисам: docker compose logs -f telegram-bot | wg-client | web | cron
  - Остановка: docker compose down
  - Проверка синтаксиса compose: docker compose config -q

- Метрики Prometheus:
  - Внутри контейнера бота слушается порт 8000 (env: METRICS_PORT). На хост пробрасывается через wg-client: http://localhost:9090/metrics

- Тесты (pytest):
  - Все тесты: pytest -q
  - Один файл: pytest -q tests/test_parser.py
  - Один тест: pytest -q tests/test_parser.py::test_parse_custom_date
  - По шаблону имени: pytest -q -k "parse_custom_date"

- CLI-утилиты (скрипт управления):
  - Список команд: python3 scripts/manage.py --help
  - Статус БД: python3 scripts/manage.py status
  - Инжест одной страницы ленты: python3 scripts/manage.py ingest-page --page 1 --limit 10
  - Backfill диапазона дат (без суммаризации): python3 scripts/manage.py backfill-range --from-date 2025-08-01 --to-date 2025-08-07
  - Сверка последних N дней: python3 scripts/manage.py reconcile --since-days 7
  - Суммаризация статей за диапазон: python3 scripts/manage.py summarize-range --from-date 2025-08-01 --to-date 2025-08-07
  - DLQ: просмотр и повтор: python3 scripts/manage.py dlq-show --limit 50; python3 scripts/manage.py dlq-retry --limit 20
  - Отчёт по дубликатам контента: python3 scripts/manage.py content-hash-report --min-count 2 --details

- WireGuard (при необходимости):
  - Поднять только VPN-клиент: docker compose up -d wg-client
  - Проверить состояние: docker compose logs -f wg-client; docker inspect --format '{{.State.Health.Status}}' wg-client

- Бэкапы (локально):
  - Ежедневные бэкапы выполняет сервис cron (см. docker-compose.yml, env BACKUP_CRON)
  - Разовый запуск утилиты: python3 tools/backup.py --component db --engine sqlite --backend local --encrypt auto

Примечание: src/config.py автоматически подхватывает переменные из .env в корне проекта; во время pytest значения из .env не принудительно переопределяют окружение теста (override отключён).


## 2) Высокоуровневая архитектура и потоки данных

Система состоит из трёх основных слоёв: доменная логика (парсинг/суммаризация/дайджесты), инфраструктура (Telegram API, HTTP, БД, Docker/VPN) и оркестрация (расписание задач, очереди публикаций, веб-админка).

- Источники и парсинг
  - src/parser.py — синхронный парсер страниц новостей (requests + BeautifulSoup). Возвращает статьи с timezone-aware published_at; отдельная функция получает полный текст статьи.
  - src/async_parser.py — асинхронный сбор по датам из архива (httpx + tenacity). Универсальная функция fetch_articles_for_date объединяет ленту и архив, возвращая пары (title, link). Оба парсера учитывают кодировку Windows‑1251 и публикуют метрики внешних HTTP-вызовов.

- Хранилище и модели данных
- src/database.py — слой доступа к БД с dual-backend: при наличии DATABASE_URL используется PostgreSQL через SQLAlchemy, иначе SQLite (локально/pytest). Ключевые таблицы: articles (url, canonical_link, title, published_at, content, summary_text, content_hash), dlq (dead‑letter queue), digests, pending_publications, а также технические таблицы прогресса backfill. Схема для PG описана в src/db/schema.py.
  - Канонизация URL вынесена в src/url_utils.py и применяется при upsert/select (canonical_link — ключ дедупликации).

- Суммаризация и дайджесты (LLM)
  - src/summarizer.py — адаптер над провайдерами Gemini/Mistral. Выбор провайдера управляется переменными окружения (LLM_PRIMARY, GEMINI_ENABLED, MISTRAL_ENABLED, модели и ключи). Есть фолбэк‑логика и публикация метрик токенов/запросов. Помимо коротких резюме есть генераторы дневных/недельных/месячных и годовых дайджестов.

- Публикация и оркестрация
  - src/bot.py — основной процесс Telegram‑бота (python‑telegram‑bot + JobQueue). Цикл: обнаружение новых ссылок → извлечение полного текста → суммаризация → публикация → запись в БД и метрики. Встроен Circuit Breaker (см. ниже), ретраи на сетевые ошибки, троттлинг и логирование с примерами постов.
  - Очередь публикаций (pending_publications) используется как фолбэк, если отправка в Telegram не удалась; отдельные функции dequeue/delete/update позволяют безопасно доотправлять.
  - src/backfill.py — дата‑ориентированный backfill: проходит календарные дни от текущей даты к целевой (BASE_AUTO_UPDATE_DATE_TARGET), соб��рает и upsert’ит «сырые» статьи; поток суммаризации — отдельно.

- Надёжность сети
  - src/connectivity.py — Circuit Breaker для Telegram API и диагностические метрики сети/VPN (wg0‑эвристика, DNS‑резолв). В состоянии OPEN бот пропускает исходящие вызовы к Telegram до охлаждения; состояние HALF_OPEN даёт пробный запрос.

- Метрики и наблюдаемость
  - src/metrics.py — Prometheus‑метрики: счётчики инжеста/публикаций/ошибок, гистограммы длительностей, возраст последней статьи, размеры DLQ, токены по LLM‑провайдерам/ключам, VPN/DNS статусы. HTTP‑сервер метрик поднимается, если METRICS_ENABLED=true.

- Веб‑интерфейс (админ)
  - src/webapp/server.py (FastAPI) — просмотр БД, отчёты по дубликатам и DLQ, публичные эндпоинты /healthz и /metrics, SSE‑обновления для UI. Аутентификация: HTTP Basic по умолчанию; предусмотрена миграция на WebAuthn/Passkeys (см. doc/WEB_AUTH.md заметки и переменные WEB_AUTH_MODE, WEB_SESSION_SECRET, WEB_RP_ID и пр.).

- Контейнеризация и сеть
- Dockerfile — Python 3.12‑slim; requirements.txt фиксирует версии ключевых библиотек.
  - docker-compose.yml — сервисы: wg-client (WireGuard, пробрасывает метрики бота на хост 9090), telegram-bot (делит сетевой namespace с wg-client), web (FastAPI), redis (pub/sub и кэш), caddy (TLS‑терминация для web), cron (плановые бэкапы). Бот и веб получают .env через env_file. Путь БД примонтирован как ./database:/app/database.

Ключевые переменные окружения (см. .env.example и src/config.py):
- DATABASE_URL (postgresql+psycopg://...) для включения PostgreSQL; без неё используется SQLite (локально/тесты)
- TIMEZONE (Europe/Moscow), METRICS_ENABLED/METRICS_PORT, LOG_LEVEL, BASE_AUTO_UPDATE*, BACKFILL_* (параллелизм/пейсинг), LLM_PRIMARY и ключи провайдеров, WEB_* параметры. Во время pytest всегда используется SQLite.


## 3) Особые для этого репозитория правила/документы

- DEPLOYMENT.md — актуальная пошаговая инструкция по развёртыванию через Docker Compose (сервисный набор, метрики, логи, троблшутинг, backfill‑команды, рекомендации по health и таймаутам Telegram).
- doc/STATUS.md — автогенерируемый свод состояния (версия, коммит, base image, сервисы, БД, зависимости). Обновлять командой: `python3 scripts/docs/generate_status.py`.
- doc/PLANNING.md — агрегатор планов и статусов; синхронизируется с ROADMAP.md и RELEASELOG.md.
- doc/ROADMAP.md — стратегические направления на 1–2 квартала.
- doc/RELEASELOG.md — заметки о релизах (ручная фиксация ключевых изменений).
- doc/WIREGUARD_SETUP_GUIDE_RU.md — руководство по настройке/диагностике WireGuard‑клиента и интеграции с docker‑compose (healthcheck по рукопожатию, проброс порта метрик).
- doc/GEMINI.md — «плейбук исполнителя»: короткий рабочий цикл для ИИ‑агента в этом репо (перед изменениями свериться с git‑состоянием, выполнять планы из doc/, после правок — pytest и сборка образа, обновлять чек‑листы в doc/*PLAN*_RU.md).
- doc/GPT5.md — «плейбук code‑review и планирования»: как быстро онбордиться, как готовить детальные планы внедрения в doc/, структура отчёта ревью и планов, общие конвенции (UTC‑хранение времени, Europe/Moscow на выводе, без блокирующих вызовов в event loop и пр.).
- doc/BEST_PRACTICES.md — сводка практик: структура каталогов, тестовая стратегия (pytest), метрики/логирование, декомпозиция обязанностей модулей, быстрая шпаргалка по запуску локально и в Docker.
- doc/MEDIA_FROM_ORIGINAL_SOURCE_PLAN_RU.md — план извлечения медиа с исходных источников (архитектура, БД‑схема, очереди, интеграция в пайплайн публикаций, тест‑план).


## 4) Контекст для будущих действий WARP

- Разработку и тесты запускать локально командой pytest -q; для ускорения — -k <pattern> и -q. В compose‑окружении тесты можно выполнять через docker compose run --rm telegram-bot pytest -q, если нужно.
- Для действий с прод‑переменными окружения использовать .env вне VCS (в репозитории есть .env.example). src/config.py уже аккуратно загружает .env.
- Для сетевой надёжности предпочитать запуск бота в связке с wg-client (network_mode: service:wg-client) — это влияет на доступность Telegram API и диагностические метрики.
- При доработке пайплайна backfill ориентироваться на «дни», а не «страницы» (STATE.collect_* в src/backfill.py), чтобы гарантировать календарное покрытие и корректные проценты прогресса.
- Если потребуется расширить LLM‑адаптеры или сменить приоритет — менять только в src/summarizer.py и через переменные окружения; метрики токенов/запросов уже агрегируются per‑provider/per‑key.

