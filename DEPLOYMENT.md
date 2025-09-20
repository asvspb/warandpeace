# Руководство по развертыванию и настройке Telegram-бота "Война и мир"

Это руководство содержит актуальные инструкции по установке, настройке и запуску проекта с использованием Docker. Обновлено с учетом текущего кода, переменных окружения и сервисов (бот, веб-интерфейс, VPN-клиент WireGuard, бэкапы).

## 1. Предварительные требования

На хосте (сервере) должны быть установлены:

- Git — проверка: `git --version`
- Docker — проверка: `docker --version`, установка: https://docs.docker.com/engine/install/
- Docker Compose v2 — проверка: `docker compose version` (или пакет docker-compose как совместимость)

Рекомендуется создать отдельного пользователя и дать ему права на Docker, а также настроить брандмауэр.

## 2. Установка

### Шаг 1: Клонирование репозитория

```bash
git clone https://github.com/asv-spb/warandpeace.git
cd warandpeace
```

### Шаг 2: Создание и настройка файла .env

Создайте `.env` в корне проекта на основе примера и заполните значения:

```bash
cp .env.example .env
```

Главное:
- Используется PostgreSQL (и в продакшене, и локально). Задайте DATABASE_URL вида:
  postgresql+psycopg://wp:${POSTGRES_PASSWORD}@postgres:5432/warandpeace
  (или используйте набор POSTGRES_HOST/PORT/USER/PASSWORD/DB)

Ключевые переменные окружения (фактически используемые кодом):

```ini
# --- База данных ---
# PostgreSQL (везде)
DATABASE_URL=postgresql+psycopg://wp:${POSTGRES_PASSWORD}@postgres:5432/warandpeace
# Либо задайте POSTGRES_HOST/PORT/USER/PASSWORD/DB

# --- Telegram ---
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHANNEL_ID=@your_channel_username   # или numeric -100...
TELEGRAM_ADMIN_ID=123456789                  # основной админ
# Опционально: список админов через запятую (используется в уведомлениях)
TELEGRAM_ADMIN_IDS=123456789,987654321

# --- Ключи и модели LLM ---
# Рекомендуется задавать Google API-ключи через запятую (коды перебираются при ошибках)
GOOGLE_API_KEYS=key1,key2
# (обратная совместимость): GOOGLE_API_KEY, GOOGLE_API_KEY_1..GOOGLE_API_KEY_9
MISTRAL_API_KEY=
GEMINI_MODEL_NAME=models/gemini-1.5-flash-latest
MISTRAL_MODEL_NAME=mistral-large-latest

# --- Время ---
TIMEZONE=Europe/Moscow

# --- Сетевые таймауты Telegram и ретраи ---
TG_READ_TIMEOUT=60
TG_WRITE_TIMEOUT=60
TG_CONNECT_TIMEOUT=10
TG_POOL_TIMEOUT=60
TG_HTTP_VERSION=1.1
TG_RETRY_ATTEMPTS=4
# Circuit Breaker
TG_CB_FAILURE_THRESHOLD=5
TG_CB_FAILURE_WINDOW_SEC=60
TG_CB_OPEN_COOLDOWN_SEC=30
# Прокси (опционально)
# HTTPS_PROXY=http://user:pass@host:port
# ALL_PROXY=socks5://user:pass@host:port

# --- Логи и поведение ---
LOG_LEVEL=INFO
ENABLE_VERBOSE_LIB_LOGS=false
LOG_POST_EXAMPLES=3
MAX_POSTS_PER_RUN=3
ADMIN_ALERTS_COOLDOWN_SEC=900

# --- Метрики Prometheus ---
# Включение HTTP-сервера метрик внутри контейнера
METRICS_ENABLED=true
# Порт сервера метрик ВНУТРИ контейнера. По умолчанию 8000.
# В docker-compose порт 8000 контейнера пробрасывается на хост как ${METRICS_PORT:-9090}.
# Чтобы избежать несоответствий, оставьте переменную неустановленной (будет 8000 по умолчанию).
# METRICS_PORT=8000

# --- Планировщик фоновой задачи ---
JOB_MISFIRE_GRACE=60
JOB_JITTER=3

# --- Резервное копирование (локальный бэкенд) ---
LOCAL_BACKUP_DIR=/var/backups/warandpeace
BACKUP_TMP_DIR=/tmp/backup
BACKUP_RETENTION_DAYS=7
LOCAL_MIN_FREE_GB=1
# Шифрование age
AGE_PUBLIC_KEYS=    # список публичных ключей через запятую (для шифрования)
AGE_SECRET_KEY=     # приватный ключ (нужен для restore; НЕ хранить в проде в .env)
# Расписание ежедневного бэкапа (используется контейнером cron)
BACKUP_CRON="0 3 * * *"

# --- Веб-интерфейс (просмотр БД) ---
WEB_PORT=8080
WEB_BASIC_AUTH_USER=admin
WEB_BASIC_AUTH_PASSWORD=change_me
WEB_API_ENABLED=false
```

Примечание о метриках: по умолчанию сервер метрик в контейнере бота слушает порт 8000, а на хосте метрики доступны по `http://<host>:9090/metrics` (см. docker-compose.yml, проброс порта из `wg-client`). Не з��давайте METRICS_PORT без необходимости, иначе возможна рассинхронизация значений порта между контейнером и пробросом.


## 3. Запуск и управление

Проект содержит несколько сервисов:
- `postgres` — база данных PostgreSQL (основной runtime)
- `wg-client` — WireGuard VPN-клиент, сетевой неймспейс которого использует бот
- `telegram-bot` — основной бот
- `web` — веб-интерфейс для просмотра БД (read-only)
- `cron` — контейнер со встроенным расписанием бэкапов

### Сборка и запуск

```bash
docker compose up --build -d
# Первичная инициализация схемы БД (создаст таблицы в PostgreSQL)
docker compose exec web python3 scripts/manage.py db-init-sqlalchemy
```

### Проверка статуса

```bash
docker compose ps
```

Ожидаемо: `postgres` — healthy, `wg-client` — healthy (после рукопожатия), `warandpeace-bot` — Up, `web` — Up.

### Логи

```bash
docker compose logs -f telegram-bot
# или по сервисам
# docker compose logs -f wg-client
# docker compose logs -f web
# docker compose logs -f cron
```

### Остановка

```bash
docker compose down
```

## 4. Обновление

```bash
git pull origin main
docker compose up --build -d
```

## 5. Устранение неполадок

- Бот перезапускается — проверьте логи `docker compose logs -f telegram-bot` и корректность `.env`
- Нет публикаций в канал — проверьте `TELEGRAM_CHANNEL_ID` и права бота в канале
- Метрики недоступны — проверьте, что `wg-client` запущен, и обращайтесь к `http://<host>:9090/metrics`

## 6. Логирование и уведомления

Переменные окружения для управления логами и уведомлениями:

```ini
LOG_LEVEL=INFO                     # DEBUG|INFO|WARNING|ERROR|CRITICAL
ENABLE_VERBOSE_LIB_LOGS=false      # подробные логи httpx/PTB и пр.
ADMIN_ALERTS_COOLDOWN_SEC=900      # троттлинг админ-уведомлений
LOG_POST_EXAMPLES=3                # примеры новых статей в логах
MAX_POSTS_PER_RUN=3                # лимит публикаций за один цикл
```

## 7. Историческая загрузка (Backfill)

Загрузка «сырых» статей с начала текущего года:

```bash
docker compose run --rm telegram-bot \
  python3 scripts/manage.py backfill-range \
  --from-date "$(date +%Y)-01-01" --to-date "$(date +%F)"
```

Статистика и суммаризация:

```bash
docker compose run --rm telegram-bot python3 scripts/manage.py status

docker compose run --rm telegram-bot \
  python3 scripts/manage.py summarize-range \
  --from-date "$(date +%Y)-01-01" --to-date "$(date +%F)"
```

Заметки:
- Команда идемпотентна: дубликаты не создаются (используется canonical_link)
- Прогресс и ошибки видны в логах и DLQ (`dlq-show`)

## 8. Надежность сети: таймауты, ретраи, предохрани��ель

В проекте реализованы:
- Ретраи с экспоненциальной задержкой на сетевые/временные ошибки Telegram
- Circuit Breaker (предохранитель) с окнами ошибок и охлаждением
- Очередь публикаций (посты сохраняются и флашатся по восстановлению связи)

Переменные окружения настройки:

```ini
# HTTP/сетевые таймауты Telegram
TG_CONNECT_TIMEOUT=10
TG_READ_TIMEOUT=60
TG_WRITE_TIMEOUT=60
TG_POOL_TIMEOUT=60
TG_HTTP_VERSION=1.1

# Кол-во попыток при сетевых сбоях Telegram
TG_RETRY_ATTEMPTS=4

# Circuit Breaker
TG_CB_FAILURE_THRESHOLD=5        # сколько сбоев в окне
TG_CB_FAILURE_WINDOW_SEC=60      # окно для подсчёта сбоев
TG_CB_OPEN_COOLDOWN_SEC=30       # «остывание» перед пробной попыткой

# Прокси при необходимости
# HTTPS_PROXY=http://user:pass@host:port
# ALL_PROXY=socks5://user:pass@host:port
```

## 9. Веб-интерфейс для просмотра базы данных и админ-аутентификация

Веб-интерфейс работает отдельным сервисом `web` и получает доступ к БД в режиме read-only. В продакшене рекомендуется публиковать его через Caddy с автоматическим TLS и включить WebAuthn (Passkeys) или хотя бы Basic Auth.

Базовая настройка через `.env`:

```ini
WEB_PORT=8080
WEB_AUTH_MODE=basic                 # basic|webauthn
WEB_BASIC_AUTH_USER=admin           # для режима basic
WEB_BASIC_AUTH_PASSWORD=your_strong_password
WEB_API_ENABLED=false               # публичный JSON API, по умолчанию выключен
WEB_API_KEY=                        # если включите API, задайте ключ для /api
```

Прод-настройка для WebAuthn (рекомендуется):

```ini
WEB_AUTH_MODE=webauthn
WEB_RP_ID=admin.example.com         # домен админки (без порта)
WEB_RP_NAME=War & Peace Admin
WEB_SESSION_SECRET=<длинный_секрет>
CADDY_DOMAIN=admin.example.com
CADDY_EMAIL=you@example.com
```

После этого:

```bash
docker compose up --build -d web caddy
```

Примечания:
- В docker-compose сервис `web` всегда запускается (переменная `WEB_ENABLED` используется только при прямом запуске `src/webapp/server.py`).
- БД примонтирована как `:ro`, изменение данных через веб-интерфейс невозможно.
- Healthcheck доступен на `/healthz`. Метрики Prometheus — на `/metrics` (публично, при необходимости ограничьте доступ на уровне Caddy/IP).

## 10. WireGuard (опционально)

Проект может работать через VPN-клиент WireGuard (`wg-client`). Рекомендуется для устойчивости и сетевой изоляции. Подробное руководство: `doc/WIREGUARD_SETUP_GUIDE_RU.md`.

Кратко:
- Храните клиентские параметры в `config/wireguard/wg.env`
- Используйте `./scripts/wireguard/manage.sh render` для генерации `config/wireguard/wg0.conf`
- Поднимайте `wg-client` командой `docker compose up -d wg-client`
- Метрики бота публикуются через проброс порта `wg-client` на хост (по умолчанию `9090 -> 8000`)

## 11. Бэкапы и восстановление

- Ежедневные бэкапы выполняет сервис `cron` согласно `BACKUP_CRON`. Поддерживается локальный бэкенд (`LOCAL_BACKUP_DIR`).
- Шифрование age: для резервного копирования `.env` — обязательно (`AGE_PUBLIC_KEYS`), для БД — опционально (в `tools/backup.py --encrypt auto|on|off`).
- Восстановление PostgreSQL из локального бэкапа:

```bash
# Посмотреть содержимое последнего дампа
./scripts/restore_now.sh --list

# Сухой прогон (проверка файла/ключа, без изменений в БД)
./scripts/restore_now.sh --dry-run

# Реальное восстановление в текущую БД
./scripts/restore_now.sh --latest

# Опасно: дропнуть БД и восстановить с нуля
./scripts/restore_now.sh --latest --drop-existing
```

Примечание: для зашифрованных бэкапов `.dump.age` требуется `AGE_SECRET_KEY` в окружении.

---

Документ синхронизирован с текущим кодом (src/config.py, src/webapp/server.py, src/bot.py, tools/backup.py, tools/restore.py, docker-compose.yml). Если вы используете более ранние версии переменных (например, `GEMINI_MODEL`), переходите на актуальные (`GEMINI_MODEL_NAME`).