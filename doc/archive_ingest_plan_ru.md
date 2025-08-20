## План реализации: загрузка базы данных с архива сайта до ARCHIVE_DATE_GOAL

Этот документ описывает целевую архитектуру, протоколы и детальный порядок работ для автоматической загрузки новостей с архива сайта в БД до даты из `ARCHIVE_DATE_GOAL`, включая мониторинг текущих суток, резюмирование текущих публикаций, пошаговую догрузку архива без резюмирования, регулярные бэкапы и ежемесячную сверку полноты БД с архивом сайта.

### Цели
- Обеспечить непрерывную загрузку текущих новостей (T) с резюмированием и мониторингом новых публикаций.
- Выполнить фоновую догрузку исторических данных до даты `ARCHIVE_DATE_GOAL` без резюмирования.
- Фиксировать статусы каждого этапа загрузки и архивирования в БД.
- Делать ежедневные и ежемесячные бэкапы; проводить ежемесячную сверку полноты с сайтом.
- Обеспечить идемпотентность, наблюдаемость, устойчивость к сбоям, соблюдение rate limits и robots.txt.

### Термины
- «Сегодня» (T): период от локальной полуночи до текущего времени в `TIMEZONE`.
- «Догрузка»: фоновая загрузка исторических диапазонов без резюмирования.
- «Сверка»: сравнение состава публикаций в БД и в архиве сайта за период.

## Архитектура

### Компоненты
- Fetcher (Scraper): получает списки публикаций и контент по временным окнам/страницам.
- Parser/Normalizer: нормализация полей, извлечение метаданных, канонических URL/ID.
- Deduplicator: контроль дублей по `source_id` и `content_hash`.
- Ingest Orchestrator: планирование и исполнение этапов загрузки; отметки статусов.
- Realtime Monitor: опрос новых публикаций сегодня; постановка на резюмирование.
- Summarizer: асинхронное резюмирование публикаций текущих суток.
- Storage (DB): таблицы статей, батчей, резюме, бэкапов, сверок, настроек.
- Backup Service: создание и верификация снапшотов БД (дневные/месячные/полные).
- Verification Service: ежемесячная сверка полноты с сайтом.
- Scheduler: регламенты (cron/оркестратор) на мониторинг/бэкапы/сверки.
- Observer: метрики, логи, алерты, дашборды.

### Поток данных (E2E)
1. Оркестратор создаёт батч «Сегодня», запускает загрузку статей по возрастанию времени.
2. Для каждой новости: нормализация, дедуп, вставка/обновление, постановка на резюмирование.
3. Параллельно Realtime Monitor опрашивает сайт и дополняет текущий батч.
4. Между циклами мониторинга запускается фоновая догрузка исторических диапазонов: вчера → неделя → до начала текущего месяца → предыдущий месяц → далее назад, пока не достигнут `ARCHIVE_DATE_GOAL`.
5. По завершении этапов создаются бэкапы согласно политике; статусы и связи фиксируются в БД.
6. Раз в месяц запускается сверка полноты, при расхождениях создаются задачи на дозакачку/исправление.

## Конфигурация (env)
- ARCHIVE_DATE_GOAL=YYYY-MM-DD
- TIMEZONE=Europe/Moscow
- SITE_BASE_URL=https://example.com
- SCRAPE_CONCURRENCY=4
- SCRAPE_RATE_LIMIT_RPS=1.5
- RETRY_POLICY=3x,exp_backoff
- SUMMARY_ENABLED_FOR_TODAY=true
- SUMMARY_MODEL=gpt-4o-mini (пример)
- SUMMARY_PROMPT_PATH=prompts/summarization_ru.txt
- BACKUP_DAILY_CRON=15 0 * * *
- BACKUP_MONTHLY_CRON=30 1 1 * *
- VERIFICATION_MONTHLY_CRON=0 3 1 * *
- MONITOR_CRON=*/5 * * * *
- STORAGE_BACKUP_BUCKET=s3://backups/news-db/
- HTTP_TIMEOUT_SECONDS=20
- USER_AGENT=news-archiver/1.0 (+contact)
- REQUEST_JITTER_MS=200-500
- MAX_PAGES_PER_BATCH=500
- MAX_ARTICLES_PER_BATCH=5000
- SUMMARY_MAX_TOKENS=512
- SUMMARY_RETRY_LIMIT=3

### Веб-интерфейс/Админка (env)
- WEB_ENABLED=true
- WEB_PORT=8080
- ADMIN_KEYS_DIR=~/.ssh/news_admins
- ADMIN_HEADER_NAME=X-Admin-Key
- ADMIN_MUTATIONS_REQUIRE_KEY=true

## Модель данных

```sql
-- Батчи (этапы загрузки)
CREATE TABLE IF NOT EXISTS ingest_batches (
  id BIGSERIAL PRIMARY KEY,
  stage VARCHAR(32) NOT NULL, -- TODAY | YESTERDAY | WEEK | MONTH_TO_DATE | PREVIOUS_MONTH | HISTORICAL
  time_start TIMESTAMPTZ NOT NULL,
  time_end   TIMESTAMPTZ NOT NULL,
  summarization_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(16) NOT NULL, -- PENDING | RUNNING | SUCCEEDED | FAILED | PARTIAL | CANCELLED
  archive_mark VARCHAR(16) NOT NULL DEFAULT 'NOT_ARCHIVED',
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  total_items INT DEFAULT 0,
  ingested_items INT DEFAULT 0,
  error TEXT,
  backup_snapshot_id VARCHAR(128)
);

-- Статьи
CREATE TABLE IF NOT EXISTS articles (
  id BIGSERIAL PRIMARY KEY,
  source_id TEXT UNIQUE,
  url TEXT NOT NULL,
  title TEXT,
  content TEXT,
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  batch_id BIGINT REFERENCES ingest_batches(id),
  ingest_status VARCHAR(16) NOT NULL DEFAULT 'INGESTED',
  archive_mark VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  content_hash TEXT,
  source_meta JSONB
);

-- Резюме (только для T)
CREATE TABLE IF NOT EXISTS article_summaries (
  article_id BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
  status VARCHAR(16) NOT NULL, -- PENDING | RUNNING | SUCCEEDED | FAILED
  summary TEXT,
  model TEXT,
  prompt_version TEXT,
  error TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Бэкапы
CREATE TABLE IF NOT EXISTS backups (
  id TEXT PRIMARY KEY,
  scope VARCHAR(16) NOT NULL, -- DAILY | MONTHLY | FULL
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  location TEXT NOT NULL,
  checksum TEXT,
  status VARCHAR(16) NOT NULL -- CREATED | VERIFIED | FAILED
);

-- Сверки
CREATE TABLE IF NOT EXISTS verifications (
  id BIGSERIAL PRIMARY KEY,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  status VARCHAR(16) NOT NULL, -- PENDING | RUNNING | MATCH | MISMATCH | FAILED
  details JSONB
);

-- Настройки/состояния (KV)
CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_articles_published_at ON articles(published_at);
CREATE INDEX IF NOT EXISTS ix_articles_content_hash ON articles(content_hash);
CREATE INDEX IF NOT EXISTS ix_summaries_status ON article_summaries(status);
```

### Ключевые инварианты
- Все даты в БД — UTC; окна вычисляются в `TIMEZONE`, затем конвертируются в UTC.
- Уникальность записей обеспечивается по `source_id`; контроль изменений — по `content_hash`.
- Любая операция повторима (идемпотентность через upsert).

## Порядок этапов и правила окон

### Этап 1: Сегодня (с резюмированием)
- Окно: `[today_start(TZ), now(TZ)]`.
- Загрузка в хронологическом порядке по возрастанию `published_at`.
- Для каждого элемента: нормализация → upsert → постановка в `article_summaries` со `status=PENDING`.
- Realtime Monitor: периодический опрос на новые публикации; дополняет текущий батч.
- Ежедневный бэкап создаётся после закрытия суток (см. политику ниже).

### Этап 2: История без резюмирования
- Последовательность окон:
  - YESTERDAY: `[T-1 00:00, T-1 23:59:59]`.
  - WEEK: `[T-7 00:00, T-2 23:59:59]`.
  - MONTH_TO_DATE: `[month_start, T-8 23:59:59]`.
- Для каждого окна: отдельный батч, без резюмирования, бэкап по окончании.
- Учитывать `ARCHIVE_DATE_GOAL`: не переходить ниже целевой даты.

### Этап 3: Предыдущий месяц
- Окно: `[prev_month_start, prev_month_end]`.
- Полная загрузка без резюмирования.
- Месячный (или полный) бэкап по окончании.

### Повторение до цели
- Между циклами мониторинга запускается догрузка следующих окон назад во времени, пока `time_start <= ARCHIVE_DATE_GOAL 00:00`.
- При достижении цели догрузка останавливается, остаются мониторинг и регламенты.

## Политика «закрытия суток»
- Условие закрытия дня: после локальной полуночи прошло ≥ 30 минут и мониторинг не нашёл новых публикаций N итераций (например, ≥ 3).
- Установка флага `day_closed: { date: YYYY-MM-DD, closed: true }` в `system_settings`.
- Дневной бэкап запускается после закрытия.

## Мониторинг новых публикаций
- Интервал: адаптивный (1–5 минут) в зависимости от активности.
- Критерий новизны: `published_at > last_seen_published_at` или новый `source_id`.
- Состояние: `system_settings['last_seen_published_at']`.
- Идемпотентность: `INSERT ... ON CONFLICT (source_id) DO UPDATE ...` с проверкой `content_hash`.

## Резюмирование (только T)
- Источник промпта: `prompts/summarization_ru.txt` (версионировать, хранить `prompt_version`).
- Параллелизм воркеров ограничить по лимитам модели.
- Ретраи с экспоненциальной паузой, максимум `SUMMARY_RETRY_LIMIT`.
- Ограничить длину входного контента/токенов; при необходимости тримминг.

## Бэкапы
- Ежедневные: после закрытия суток; `scope=DAILY`.
- Ежемесячные: после загрузки полного месяца; `scope=MONTHLY`.
- Полные: по требованию/при первых загрузках; `scope=FULL`.
- Содержимое: дамп БД + манифест (диапазоны дат, количество записей, контрольные суммы).
- Размещение: `STORAGE_BACKUP_BUCKET` с версионированием и KMS.
- Верификация: вычисление и проверка checksum; запись `backups.status=VERIFIED`.
- Ретеншн: DAILY — 30 дней; MONTHLY — 12 месяцев; FULL — 2 копии.

## Ежемесячная сверка полноты
- Период: `[month_start, month_end]`.
- Сбор эталона: список `source_id`/URL/дат с сайта.
- Сравнение с БД: недостачи, дубликаты, несовпадения дат/URL.
- Результаты: `verifications.status=MATCH|MISMATCH`; при MISMATCH — задачи на дозакачку и корректировки.

## Идемпотентность и дедупликация
- Уникальный индекс по `source_id`.
- `content_hash` для различения переизданий/обновлений.
- Upsert: обновлять `title/content/published_at/source_meta` при изменениях.
- Защитные буферы окон: ±5 минут на границах для избежания «дыр».

## Ошибки и отказоустойчивость
- Ретраи сети: экспоненциальный backoff с джиттером; отдельные лимиты на уровень страницы и статьи.
- Обработка 429/5xx: снижение параллелизма, пауза, повтор позже.
- PARTIAL батчи: сохранять прогресс, планировать follow-up батч на «дырки».
- Таймауты HTTP: `HTTP_TIMEOUT_SECONDS` с отменой и логированием причины.

## Часовые пояса
- В БД — UTC; в интерфейсах — `TIMEZONE`.
- Конвертация окон: «вход (TZ) → UTC (БД)».
- Хранить исходную TZ в `articles.source_meta`.

## Планировщик
- MONITOR_CRON: частота опроса Realtime Monitor.
- BACKUP_DAILY_CRON: проверять флаг закрытия суток, запускать бэкап.
- BACKUP_MONTHLY_CRON: запускать месячный бэкап после завершения загрузки месяца.
- VERIFICATION_MONTHLY_CRON: запускать сверку полноты.
- Фоновая догрузка: по триггеру «окно простоя мониторинга» либо отдельным джобом.

## Наблюдаемость
- Метрики: RPS скрейпера, доля ошибок, средняя задержка публикация→ингест, глубина очереди Summarizer, длительность батчей, размеры БД.
- Логи: корреляция по `batch_id`, `source_id`; уровни INFO/WARN/ERROR.
- Алерты: отсутствие бэкапа к 02:00, `MISMATCH` после сверки, рост ошибок > X%.
- Дашборды: состояние батчей, активность мониторинга, статусы резюмирования.

## Веб‑интерфейс (UI/Админка)

### Цели и аудитория
- Предоставить веб‑просмотр базы публикаций и статусов.
- Дать возможность инициировать резюмирование/перерезюмирование только доверенным администраторам.

### Основные функции
- Главная панель:
  - Карточка «Заполнение архива»: прогресс‑бар и процент заполнения относительно `ARCHIVE_DATE_GOAL`.
  - Счётчики: всего статей в БД, доля с резюме «за сегодня», глубина очереди Summarizer.
- Таблица статей:
  - Колонки: дата/время, заголовок, источник/URL, батч/стадия, и колонка «Резюмирование».
  - Колонка «Резюмирование» показывает:
    - SUCCEEDED — зелёная галочка.
    - RUNNING — индикатор выполнения.
    - FAILED — красный значок с подсказкой об ошибке.
    - Отсутствует запись в `article_summaries` — кнопка «+» для добавления резюме.
  - Действия (только для админа с ключом):
    - «Резюмировать заново» (иконка ↻) — постановка статьи в очередь на повторное резюмирование.
    - «Добавить резюме» (иконка +), если резюме отсутствует.
- Карточка статьи (страница новости):
  - Слева — полный текст статьи и метаданные.
  - Справа — блок «Резюме»: текущий текст резюме (если есть), статус и кнопка «Резюмировать заново».
  - Если резюме отсутствует — показать пустой блок с кнопкой «Добавить резюме».

### Расчёт процента заполнения архива
- Диапазон цели: от `ARCHIVE_DATE_GOAL 00:00` до «сейчас».
- Пути расчёта:
  - По эталонному количеству из последней сверки (`verifications`): `percent = round(min(100, ingested/expected * 100))`, где `expected` — число публикаций с сайта за диапазон (из `verifications.details`), `ingested` — количество записей в `articles` в этом диапазоне.
  - Если эталон недоступен — приблизить по покрытию дат (минимальная дата в `articles` ≤ `ARCHIVE_DATE_GOAL`) и/или по счётчику страниц/источников.
- Значение и метод расчёта отображаются в подсказке прогресс‑бара.

### Безопасность и доступ
- Режимы доступа:
  - Без ключа — полный read‑only: кнопки мутаций скрыты или отключены.
  - С валидным ключом — разрешены мутации (добавить/перерезюмировать).
- Ключи хранятся вне репозитория, в директории `~/.ssh` сервера приложения:
  - Каталог `~/.ssh/news_admins/` содержит один или несколько файлов‑ключей (симметричные токены), например `~/.ssh/news_admins/alice.token`.
  - Сервер при старте загружает разрешённые значения токенов из этого каталога.
- Клиент (браузер/прокси) передаёт ключ в заголовке `X-Admin-Key` (см. `ADMIN_HEADER_NAME`).
- Ключи могут быть отозваны удалением файла из `~/.ssh/news_admins/` без рестарта (переинициализация по таймеру/сигналу).
- Все мутации логируются с указанием хеша ключа и IP источника.

### API (черновик)
- GET `/api/progress/archive?goal=YYYY-MM-DD`
  - Ответ: `{ percent: number, method: 'verification|approx', range: { from, to }, counts: { ingested, expected|null } }`.
- GET `/api/articles?offset&limit&query&stage&has_summary`
  - Возвращает список статей с полем `summary_status` и `has_summary`.
- GET `/api/articles/{id}` — статья с текущим резюме (если есть).
- POST `/api/articles/{id}/summary`
  - Требует заголовок `X-Admin-Key`.
  - Создаёт/ставит в очередь резюмирование, если отсутствует.
- POST `/api/articles/{id}/summary/resummarize`
  - Требует заголовок `X-Admin-Key`.
  - Принудительно ставит в очередь повторное резюмирование.
- Все POST‑эндпоинты возвращают 202 (accepted) при успешной постановке в очередь.

### Мэппинг UI↔БД
- Колонка «Резюмирование» строится по наличию строки в `article_summaries` и её `status`.
- Кнопка «+» доступна, если строки нет; кнопка «↻» — если статус `SUCCEEDED|FAILED`.
- Детали ошибки берутся из `article_summaries.error`.

### Нефункциональные требования
- Авторизация ключом обязательна для любых мутаций; отсутствие ключа гарантирует read‑only режим.
- Ключи не хранятся и не коммитятся в репозиторий; только в `~/.ssh/` на сервере.
- UI и API должны сохранять идемпотентность: повторные нажатия не создают дубликаты задач.

## Контракты модулей (высокоуровневые)

```python
# Fetcher
fetch_paginated(time_start_utc, time_end_utc, order='asc'|'desc') -> Iterator[List[RawItem]]
fetch_article_body(url) -> ArticleBody

# Normalizer
normalize(raw_item: RawItem) -> NormalizedItem(source_id, url, title, content, published_at_utc, source_meta)

# Storage
upsert_article(normalized: NormalizedItem, batch_id) -> ArticleRow
mark_batch_status(batch_id, status, error=None)
create_batch(stage, time_start_utc, time_end_utc, summarization_enabled) -> BatchRow
link_backup(batch_id, backup_id)

# Summarizer
enqueue_summary(article_id)
run_summary_worker()

# Backups
create_backup(scope: 'DAILY'|'MONTHLY'|'FULL') -> backup_id
verify_backup(backup_id) -> bool

# Verification
verify_period(month_start, month_end) -> VerificationResult
```

## Псевдокод оркестрации

```python
def orchestrate():
  ensure_today_batch()
  schedule_monitoring()

  while not reached_archive_goal():
    if monitor_idle_window_available():
      stage = next_backfill_stage()
      window = compute_window(stage, ARCHIVE_DATE_GOAL)
      if not window:
        break
      run_ingest_batch(stage, window, summarization_enabled=False)
      if should_backup_after(stage):
        backup_id = create_backup(scope_for(stage))
        link_backup(current_batch_id(), backup_id)
    sleep(short_interval)


def ensure_today_batch():
  window = [today_start(TZ), now(TZ)]
  run_ingest_batch('TODAY', window, summarization_enabled=True)
```

## Миграции и версии промптов
- SQL-миграции для создания таблиц и индексов; следующий релиз — добавить `system_settings`.
- Файл промпта: `prompts/summarization_ru.txt` — хранить версию в начале файла и писать в `article_summaries.prompt_version`.
- Управление версиями: при изменении промпта — только новые статьи получают новую версию; опционально перерасчёт для T с `FAILED`.

## Тестирование
- Юнит: парсер, дедуп, расчёт окон с TZ, идемпотентный upsert, вычисление `content_hash`.
- Интеграция: пагинация, ретраи, off-by-one на границах окон, частичный сбой батча.
- Нагрузочные: RPS на `SCRAPE_CONCURRENCY`, стабильность при 429/5xx.
- E2E: сценарий T → догрузка → месячный → бэкапы → сверка; контроль статусов в БД.

## Безопасность и комплаенс
- Секреты в менеджере секретов/ENV; не хранить ключи в коде.
- User-Agent с контактной информацией; соблюдение robots.txt.
- Ограничение параллелизма/скорости; пауза при ошибках и капче.
- Шифрование бэкапов (KMS), ограничение доступа, аудит.

## Эксплуатация (Runbook)
- Как форсировать закрытие дня: установить флаг в `system_settings` и запустить джоб бэкапа.
- Как перезапустить упавший батч: создать follow-up батч с тем же окном, пересечь границы на ±5 минут, включить дедуп.
- Как докачать «дырку» по диапазону: вручную задать окно в оркестраторе.
- Как проверить целостность: запустить сверку за период; изучить `verifications.details`.
- Как восстановиться из бэкапа: см. `doc/BACKUP_RESTORE_RU.md`.

## Производительность и стоимость
- Балансировать `SCRAPE_CONCURRENCY` и RPS по ответам сервера (адаптивный лимитер).
- Кэширование списков страниц на короткое время, если сайт позволяет.
- Снижение частоты мониторинга ночью/в выходные (пригодно, если публикаций мало).

## Риски и смягчение
- Блокировка/бан: честный User-Agent, ограничение RPS, экспоненциальные паузы, контакт.
- Изменения верстки: версионирование парсеров, тесты-контракты, быстрые фиксы.
- Большие месяцы: дробление на недели/дни внутри месяца, контроль MAX_* лимитов.

## Дорожная карта внедрения
1. Миграции БД и KV `system_settings`.
2. Fetcher/Parser + идемпотентный upsert.
3. Оркестратор батчей и вычисление окон.
4. Realtime Monitor и очередь Summarizer (использовать `prompts/summarization_ru.txt`).
5. Бэкап-сервис и интеграция со снапшотами.
6. Догрузка: вчера/неделя/до начала месяца.
7. Предыдущий месяц + месячный бэкап.
8. Сверка полноты.
9. Наблюдаемость + алерты.
10. E2E и rollout.
11. Веб‑интерфейс и API: прогресс заполнения, таблица с колонкой «Резюмирование», карточка статьи с блоком резюме, защита мутаций ключом из `~/.ssh/news_admins/`.

## Примеры cron и команд

```bash
# systemd timer/cron примеры
# Мониторинг новых публикаций каждые 5 минут
*/5 * * * * /usr/local/bin/newsctl monitor --tz "$TIMEZONE"

# Фоновая догрузка (один батч за проход)
*/7 * * * * /usr/local/bin/newsctl backfill --goal "$ARCHIVE_DATE_GOAL" --tz "$TIMEZONE"

# Дневной бэкап после полуночи
15 0 * * * /usr/local/bin/newsctl backup daily

# Месячный бэкап и сверка
30 1 1 * * /usr/local/bin/newsctl backup monthly
0 3 1 * * /usr/local/bin/newsctl verify month --tz "$TIMEZONE"
```

## Мини-спецификация CLI (пример)

```bash
newsctl orchestrate                # запустить основной цикл (one-shot/daemon)
newsctl monitor                    # мониторинг новых публикаций за сегодня
newsctl backfill --goal YYYY-MM-DD # одна итерация догрузки
newsctl backup daily|monthly|full  # создать бэкап указанного типа
newsctl verify day|month --date ...# сверка полноты
newsctl batch status --id <id>     # статус батча
```

## Примечания по интеграции с уже существующими файлами
- Использовать промпт `prompts/summarization_ru.txt` для резюмирования.
- Шаблоны/подсказки для дайджестов (`prompts/digest_daily_ru.txt`, `prompts/digest_weekly_ru.txt`, `prompts/digest_monthly_ru.txt`) в этот процесс не вовлекаются напрямую, но их можно применить на этапах аналитики поверх БД.

---

Документ охватывает требования: загрузка текущих суток с резюмированием и мониторингом, фоновая догрузка без резюмирования до `ARCHIVE_DATE_GOAL`, бэкапы (суточные/месячные) и ежемесячная сверка, статусы всех этапов в БД, устойчивость и наблюдаемость. При необходимости можно дополнить детальными схемами последовательностей и спецификой целевого сайта.