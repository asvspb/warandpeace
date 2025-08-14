<!--
Document: Algorithm for News DB ingestion
Version: 0.2 (2024-05-30)
Owner: Data Platform Team <data-platform@example.com>
-->

## Наполнение и актуализация новостной базы (ингест без суммаризации)

### 1) Цели и границы
- В базу попадают только «сырые» данные: заголовок, ссылка, дата публикации, полный очищенный текст, источник.
- Суммаризация и дайджесты — отдельные процессы/команды, не блокируют сбор новостей.
- Все даты нормализуются в UTC, ссылки приводятся к канонической форме (canonical URL).

### 2) Модель данных (рекомендация)
> Типы: `VARCHAR(2048)` для ссылок, `TIMESTAMP WITH TIME ZONE` для всех дат.

- **sources** — справочник источников  
  - `id` (PK), `name`, `base_url`, `priority`, `created_at`

- **articles**
  - `id` (PK)
  - `source_id` (FK→`sources.id`)
  - `link` (UNIQUE, canonical, VARCHAR(2048))
  - `title`
  - `published_at` (UTC)
  - `parsed_at` — время фактического разбора страницы
  - `lang` (CHAR(2), ISO-639-1)
  - `content` (TEXT)
  - `created_at`, `updated_at`
  - Индексы: `(published_at)`, `(source_id, published_at DESC)`

- **summaries**
  - `id` (PK)
  - `article_id` (FK→`articles.id`)
  - `summary_text`
  - `model`, `provider`, `temperature`, `tokens_used`
  - `status` (`OK|FAILED|PENDING`)
  - `version`, `prompt_version`
  - `created_at`

- **dlq** (очередь «проблемных»)
  - `id`, `entity_type` (`article|summary`), `entity_ref`, `error_code`, `error_payload`,
    `first_seen_at`, `last_seen_at`, `attempts`

### 3) Алгоритм Backfill (диапазон дат, без суммаризации)
Инварианты:
- **Идемпотентность**: UPSERT по `link`; обновления допускаются только вперёд по времени (`updated_at`).
- **Контроль нагрузки**: bounded parallelism, rate limit, экспоненциальный backoff.
- **Возобновляемость**: checkpoint по (date, page, last_link) с сохранением в таблице `checkpoints` (или S3-файле) для атомарного восстановления.
- **Дедупликация**: нормализация ссылок; проверка по канонической `link`.

Шаги:
1. Нормализовать `from_date..to_date` (UTC, включительно), проверить `from ≤ to`.
2. Для каждой даты слева направо (от старых к новым):
   - Итерировать страницы архива до исчерпания карточек или «устойчивого нуля» (несколько пустых подряд).
   - Для каждой карточки извлечь `title`, `link`, `published_at` → привести `link` к canonical.
   - Отфильтровать существующие `link` → новые добавить в очередь `ingest_article`.
3. `ingest_article` (с ограниченной параллельностью):
   - Скачать страницу, извлечь основной контент, очистить/нормализовать.
   - UPSERT в `articles`.
   - На сетевых/временных ошибках — ретрай с backoff; на постоянных — в `dlq`.
4. Сохранять checkpoint по завершению каждой страницы и/или каждые K статей.
5. Отчёт: найдено/добавлено/дубликаты/ошибки, длительности, p95.

Псевдокод:
```python
async def backfill(from_date, to_date, max_workers=4):
    assert from_date <= to_date
    for date in daterange(from_date, to_date):
        for page in iterate_pages(date):  # пока есть новые карточки
            cards = await list_articles(date, page)
            new_items = [c for c in cards if not db.exists(c.link)]
            await bounded_parallel(new_items, max_workers, ingest_article)
            save_checkpoint(date, page, last_link=(new_items[-1].link if new_items else None))
    report()
```

### 4) Регулярная актуализация (Sync & Reconcile, без суммаризации)
- **Инкрементальная синхронизация** (каждые 5–10 минут):
  - Скан главной/ленты → новые ссылки → `ingest_article`.
  - Лимит на количество новых записей за запуск; паузы между запросами.
- **Ночной reconcile** (1 раз в сутки):
  - За последние D дней сравнить сайт vs БД (по множествам ссылок).
  - Недостающие → mini-backfill, «битые» → переобработка; повторные провалы → `dlq`.
- **Планировщик**: `misfire_grace_time`, `coalesce`, `max_instances=1`, `jitter`.

Псевдокод:
```python
async def sync_recent(max_new=10):
    links = await list_recent_from_main()
    fresh = [l for l in links if not db.exists(l)]
    for link in fresh[:max_new]:
        await ingest_article(link)
        await sleep(post_delay_seconds)
```

### 5) Суммаризация (отдельные запросы/команды)
Запуск не связан с backfill/sync; работает от уже сохранённого `content`.

- **Точки запуска**:
  - `summarize --date YYYY-MM-DD`
  - `summarize-range --from YYYY-MM-DD --to YYYY-MM-DD`
  - `summarize-missing --since-days 14`
  - `summarize-ids --ids <id1,id2,...>`
- **Политика**:
  - Для каждой статьи: загрузить `content` → провайдер A (напр., Gemini) → fallback провайдер B (Mistral).
  - Сохранять результат в `summaries` с метаданными (`model`, `provider`, `status`).
  - Поддерживать перегенерацию; опционально хранить версионность.

Псевдокод:
```python
async def summarize_articles(article_ids):
    for aid in article_ids:
        content = db.get_article(aid).content
        summary = try_gemini_then_mistral(content)
        db.upsert_summary(article_id=aid, text=summary, provider=..., model=..., status="OK")
```

### 6) Надёжность и возобновление
- Checkpoint каждые K операций и при завершении страницы.
- `dlq` с лимитами ретраев и backoff; пометки причин и последней ошибки.
- Каноникализация URL, дедупликация, защита от «пустых дней» (аномалий).
- Явные тайм-ауты и бюджеты ретраев (например, до 3 попыток/сутки для `dlq`).

### 7) Метрики, SLA и алерты
- Ингест: found/added, error rate, p95 latency, backlog size, age-of-last-article (SLA: ≤ X минут).
- Суммаризация: success rate по провайдерам, среднее время, число ретраев, распределение по моделям, DLQ.
- Алерты: «нет новых статей > Y часов», «ошибки > Z% за окно», «DLQ растёт N дней».

### 8) CLI/API (предложения)
- Ингест: `backfill`, `reconcile`, `retry-failed` (фильтры: `--source`, `--since-days`, `--limit`, `--resume`).
- Суммаризация: `summarize`, `summarize-range`, `summarize-missing`, `summarize-ids`.

### 9) Безопасность и комплаенс
- Логи и контент могут содержать персональные данные (PII) — включить маскирование и политику retention.
- Секреты (API-ключи, прокси-логины) хранить во vault /.env, не коммитить в Git.
- Регулярные security-scan зависимостей и review third-party libs.

### 10) Тестирование
- Unit-тесты парсеров (golden-files, mock-HTML).
- Интеграционные тесты: backfill одного дня, сверка ожидаемых vs сохранённых записей.
- Contract-tests на схему БД и API.
- Load-тест суммаризации с ��муляцией N параллельных запросов.

### 11) Документация и onboarding
- Quick-start: `make backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD` → проверка результата.
- Run-book: стандартные операции, FAQ, инструкции по восстановлению после фейлов.
- Диаграмма потоков данных (scraper → DB → summarizer) для наглядности.

---

Итог: конвейер разделён — быстрое и устойчивое наполнение базы «сырыми» данными и независимая суммаризация по запросу. Это упрощает SLA по сбору новостей и позволяет гибко управлять квотами/затратами LLM.

### 12) Статус выполнения
- [x] Разделение конвейеров: инжест «сырых» данных отдельно от суммаризации
- [x] Каноникализация URL и интеграция в парсеры (`parser.py`, `async_parser.py`)
- [x] Расширение схемы БД: `canonical_link` (UNIQUE), `content`, `content_hash`, `updated_at` (+ индексы)
- [x] DLQ: таблица, индексы и функции (`dlq_record`, `get_dlq_size`)
- [x] DB-API для инжеста/суммаризации: `upsert_raw_article`, `list_articles_without_summary_in_range`, `set_article_summary`
- [x] CLI: `ingest-page`, `backfill-range`, `reconcile`, `summarize-range`
- [x] Метрики Prometheus и интеграция в бота (публикации, ошибки, возраст последней статьи)
- [x] Тюнинг Telegram HTTP-клиента и планировщика задач
- [x] Unit-тесты для каноникализации URL; общий прогон тестов зелёный
- [x] CLI для DLQ: `dlq-show`, `dlq-retry` (c бюджетами ретраев)
- [x] Использование `content_hash` для поиска «почти-дубликатов» и отчётов
- [x] Экспорт метрик DLQ/ingest из CLI/джобов (регулярные обновления)
- [x] Транзакционный бэкап/rollback миграций
- [x] Docker: публикация порта метрик и переменные `METRICS_ENABLED`/`METRICS_PORT`