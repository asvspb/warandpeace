# Персистентная дневная статистика использования API и «статистика текущей сессии»

Документ-план для реализации другим ИИ. Репозиторий: warandpeace.

Согласован с конвенциями из doc/GPT5.md и doc/GEMINI.md, учитывает текущую архитектуру (см. WARP.md, разделы «Метрики» и «Хранилище»).


## 1) Цель и контекст

Цель: реализовать сохранение дневной (по датам) статистики использования внешних API (в первую очередь LLM-провайдеры: Gemini/Mistral; опционально Telegram API) так, чтобы данные не терялись при перезапуске/пересборке контейнера. Дополнительно — поддержать «статистику текущей сессии» (с момента запуска процесса бота) отдельно от персистентных суточных агрегатов.

Контекст:
- Сейчас метрики публикуются в Prometheus (in-memory, сбрасываются при рестарте) — этого недостаточно для долговременной аналитики.
- В проекте уже используется SQLite (монтируется том ./database:/app/database), что удобно для персистентных агрегатов.
- Часовой пояс: хранение в БД — UTC; вывод в UI — Europe/Moscow (см. конвенции в doc/GPT5.md и WARP.md).


## 2) Объём работ (scope)

Обязательно (MVP):
- LLM-использование: количество запросов, успешных запросов, токены на вход/выход, стоимость (если применимо), задержка, коды ошибок/статусы, провайдер/модель/ключ.
- Дневная агрегация по UTC-дате d (00:00:00Z…23:59:59Z).
- Отдельная «статистика текущей сессии» (с момента старта процесса бота) — в памяти и видимая через /metrics и/или web-админку.
- Персистентность в SQLite с автоматическим бэкапом существующим механизмом cron.

Опционально (после MVP):
- Telegram API: счётчики удачных/ошибочных попыток отправки, коды ошибок, троттлинг, средние задержки.
- Внешние HTTP-вызовы парсера (requests/httpx): суммарные метрики успешности/времени.
- Веб-интерфейс отчёта по дням (таблица/фильтры/экспорт CSV).


## 3) Архитектурный подход

- Событийная запись: при каждом обращении к провайдеру фиксируем событие в памяти (быстрая структура) и периодически сбрасываем в БД (батч, интервал настраиваемый). Дополнительно — прямые insert’ы допустимы, но батч снижает накладные расходы.
- Два уровня хранения:
  1) Таблица событий api_usage_events (сырые записи).
  2) Таблица дневных агрегатов api_usage_daily (итоги по датам/провайдерам/моделям/ключам).
- Агрегация: инкрементально обновляется при каждом сбросе событий в БД и/или отдельной периодической задачей (hourly). В конце суток — финализация дня (идемпотентно).
- «Статистика текущей сессии»: держим в памяти с момента старта; при экспорте в /metrics показываем обе линии: per-session (reset при рестарте) и per-day (из БД — не сбрасывается).


## 4) Схема БД (SQLite)

Таблица сырых событий (минимально необходимое; поля можно расширять при необходимости):

```sql
CREATE TABLE IF NOT EXISTS api_usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc TEXT NOT NULL,                -- ISO 8601 UTC (e.g. 2025-08-26T12:34:56.789Z)
  provider TEXT NOT NULL,              -- 'gemini' | 'mistral' | 'telegram' | 'http' | ...
  model TEXT,                          -- модель LLM, если применимо
  api_key_hash TEXT,                   -- SHA-256 от ключа/идентификатора; не хранить секреты
  endpoint TEXT,                       -- опционально: конкретный endpoint провайдера
  req_count INTEGER NOT NULL DEFAULT 1,
  success INTEGER NOT NULL,            -- 1/0
  http_status INTEGER,                 -- код ответа, если есть
  latency_ms INTEGER,                  -- длительность запроса
  tokens_in INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0.0,
  error_code TEXT,                     -- код ошибки/исключения (если был)
  extra_json TEXT                      -- опционально: доп. поля, JSON-строка
);
CREATE INDEX IF NOT EXISTS idx_api_usage_events_ts ON api_usage_events (ts_utc);
CREATE INDEX IF NOT EXISTS idx_api_usage_events_provider_model ON api_usage_events (provider, model);
CREATE INDEX IF NOT EXISTS idx_api_usage_events_api_key_hash ON api_usage_events (api_key_hash);
```

Таблица дневных агрегатов:

```sql
CREATE TABLE IF NOT EXISTS api_usage_daily (
  day_utc TEXT NOT NULL,               -- YYYY-MM-DD (UTC)
  provider TEXT NOT NULL,
  model TEXT,
  api_key_hash TEXT,
  req_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0,
  tokens_in_total INTEGER NOT NULL DEFAULT 0,
  tokens_out_total INTEGER NOT NULL DEFAULT 0,
  cost_usd_total REAL NOT NULL DEFAULT 0.0,
  latency_ms_sum INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day_utc, provider, model, api_key_hash)
);
CREATE INDEX IF NOT EXISTS idx_api_usage_daily_provider ON api_usage_daily (provider);
```

Отдельно (опционально) — учёт сессий процесса бота:

```sql
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  started_at_utc TEXT NOT NULL,
  ended_at_utc TEXT,
  git_sha TEXT,
  container_id TEXT,
  notes TEXT
);
```

Примечание: даты храним в UTC; преобразование на вывод делаем на уровне UI/CLI.


## 5) Точки интеграции в код

- src/summarizer.py
  - В местах вызова провайдеров (Gemini/Mistral) добавить сбор метаданных: provider, model, токены (in/out), успех/ошибка, latency, оценка стоимости (если возможно получить по тарифам).
  - Вызывать вспомогательную функцию record_api_event(...), которая пишет в in-memory буфер и, при необходимости, в БД.

- src/metrics.py
  - Добавить экспорт новых метрик:
    - session_api_requests_total{provider,model}
    - session_api_tokens_in_total{provider,model}
    - session_api_tokens_out_total{provider,model}
    - session_api_cost_usd_total{provider,model}
    - daily_api_requests_total{provider,model} — gauge, читается из БД для «сегодня» и «вчера» (опционально для последних N дней)
  - Сохранить совместимость с уже существующими метриками.

- src/database.py
  - Добавить функции:
    - ensure_api_usage_schema()
    - insert_api_usage_events(batch: list[ApiUsageEvent])
    - upsert_api_usage_daily(day_utc, provider, model, api_key_hash, deltas)
    - recalc_api_usage_daily_for_range(from_date, to_date)
  - Обеспечить атомарность батч-вставок, индексы, идемпотентность пересчётов.

- src/bot.py
  - На старте генерировать session_id, фиксировать в sessions, инитировать in-memory счётчики и задачу периодического flush в БД (интервал см. конфиг ниже).
  - На graceful shutdown завершать flush и закрывать сессию.

- scripts/manage.py
  - Новые команды CLI:
    - api-usage-show --from-date YYYY-MM-DD --to-date YYYY-MM-DD [--provider ...] [--model ...] [--csv]
    - api-usage-recalc --from-date ... --to-date ...
    - api-usage-today --provider ... --details

- src/webapp/server.py (опционально в MVP, полезно позже)
  - Эндпоинт /admin/api-usage[?from=...&to=...&provider=...], страница с таблицей по дням.
  - SSE-обновления раз в N секунд, если уже есть общий механизм.


## 6) Конфигурация (.env → src/config.py)

- API_USAGE_PERSISTENCE_ENABLED=true|false (default: true)
- API_USAGE_FLUSH_INTERVAL_SEC=60 (периодический сброс in-memory буфера в БД)
- API_USAGE_DAILY_RECALC_CRON=0 * * * * (опционально: ежечасный идемпотентный пересчёт текущего дня)
- API_USAGE_INCLUDE_TELEGRAM=true|false (по умолчанию false, если хотим начать с LLM)


## 7) Логика вычисления стоимости (если применимо)

- В summarizer.py завести таблицу тарифов в конфиге (или простую функцию-мэппинг) по провайдеру/модели: стоимость per 1k tokens (in/out). При отсутствии данных — считать 0.0.
- Стоимость события = (tokens_in/1000)*price_in + (tokens_out/1000)*price_out.
- Суммировать в событиях и в агрегатах.


## 8) Механизм агрегации и идемпотентность

- Для каждого события вычислять day_utc = ts_utc[0:10].
- При вставке batch событий: группировать по (day_utc, provider, model, api_key_hash) и вызывать upsert для api_usage_daily с инкрементами.
- Периодический пересчёт (recalc) берёт сырьё за диапазон дат, полностью пересчитывает соответствующие строки в api_usage_daily (DELETE+INSERT или UPDATE по разнице) — операция идемпотентна.


## 9) «Статистика текущей сессии»

- В памяти держим словарь counters_session[(provider, model, api_key_hash)] с полями req_count, success_count, tokens_in, tokens_out, cost_usd, latency_ms_sum.
- Публикуем в /metrics как session_* метрики.
- На рестарт процесса — счётчики обнуляются (ожидаемо). При этом дневные агрегаты продолжают копиться в БД.


## 10) Изменения в Docker/Compose

- Хранилище уже примонтировано: ./database:/app/database — ничего добавлять не требуется.
- Убедиться, что новые переменные окружения пробрасываются в сервисы telegram-bot и web (env_file: .env).


## 11) Тест-план (pytest)

Юнит-тесты:
- test_api_usage_event_recording: при успешном/ошибочном вызове summarizer провайдера события корректно записываются в буфер, затем во вставке в БД — корректные поля.
- test_api_usage_daily_upsert: инкремент нескольких событий за один день корректно отражается в агрегате.
- test_api_usage_recalc: пересчёт диапазона дат воспроизводит ожидаемые агрегаты при наличии дубликатов/повторных вставок.
- test_session_metrics: метрики session_* отражают счётчики с момента старта.

Интеграционные:
- Через scripts/manage.py: api-usage-show сегодня/вчера даёт ненулевые значения после серии вызовов summarizer.
- Совместимость с METRICS_ENABLED: метрики не ломаются, новые метрики появляются.


## 12) Критерии приёмки

- После пересборки/перезапуска контейнера значения по «сегодня/вчера» в api_usage_daily сохраняются и продолжают расти при новых запросах.
- /metrics одновременно отдаёт session_* (с нуля) и daily_* (из БД) показатели.
- CLI api-usage-show показывает корректную агрегацию за заданный диапазон дат.
- Никаких утечек секретов: в БД хранится только hash ключа.


## 13) Риски и меры

- Повреждение БД при аварийном завершении: использовать транзакции и периодический flush небольшими партиями. SQLite journal_mode=WAL (если приемлемо для окружения).
- Рост объёма таблицы событий: периодически архивировать/очищать сырьё старше N дней после успешного пересчёта агрегатов (конфигурируемо, например, API_USAGE_EVENTS_TTL_DAYS=60).
- Точность стоимости: тарификация моделей меняется — хранить версию тарифов в extra_json либо в отдельной таблице; при изменении — пересчитывать прошлое не обязательно.


## 14) Чек-лист задач для исполнения (пошагово)

1) database.py
   - [+] ensure_api_usage_schema()
   - [+] insert_api_usage_events(batch)
   - [+] upsert_api_usage_daily(...)
   - [+] recalc_api_usage_daily_for_range(...)
2) summarizer.py
   - Обернуть вызовы провайдеров хелпером record_api_event(...).
   - Считать токены/латентность/успех, оценивать cost_usd.
3) metrics.py
   - Добавить session_* и daily_* метрики, чтение daily из БД.
4) bot.py
   - Генерация session_id, старт/стоп логика, периодический flush буфера.
5) scripts/manage.py
   - Команды api-usage-show, api-usage-recalc, api-usage-today, api-usage-export-csv (опц.).
6) webapp/server.py (опц.)
   - Эндпоинт/страница для просмотра агрегатов.
7) Конфиг
   - Новые переменные окружения в .env.example и парсинг в src/config.py.
8) Тесты
   - Юнит/интеграционные тесты (pytest), команды в CI.


## 15) Минимальные интерфейсы/сигнатуры (наметки)

Python типы/сигнатуры (псевдокод):

```python
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ApiUsageEvent:
    ts_utc: str
    provider: str
    model: Optional[str]
    api_key_hash: Optional[str]
    endpoint: Optional[str]
    req_count: int
    success: bool
    http_status: Optional[int]
    latency_ms: Optional[int]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error_code: Optional[str]
    extra_json: Optional[str]
```

```python
def record_api_event(event: ApiUsageEvent) -> None:
    """Добавляет событие в in-memory буфер и обновляет session-счетчики."""
```

```python
def flush_api_events_to_db() -> None:
    """Сбрасывает буфер событий в SQLite одной транзакцией и обновляет дневные агрегаты."""
```


## 16) Набросок SQL для апдейта агрегатов

```sql
INSERT INTO api_usage_daily (
  day_utc, provider, model, api_key_hash,
  req_count, success_count, tokens_in_total, tokens_out_total, cost_usd_total, latency_ms_sum
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(day_utc, provider, model, api_key_hash) DO UPDATE SET
  req_count = req_count + excluded.req_count,
  success_count = success_count + excluded.success_count,
  tokens_in_total = tokens_in_total + excluded.tokens_in_total,
  tokens_out_total = tokens_out_total + excluded.tokens_out_total,
  cost_usd_total = cost_usd_total + excluded.cost_usd_total,
  latency_ms_sum = latency_ms_sum + excluded.latency_ms_sum;
```


## 17) Открытые вопросы (для согласования перед реализацией)

- Какие провайдеры считать обязательными в первой итерации? Предлагаю начать с LLM (Gemini/Mistral).
- Нужен ли учёт Telegram API в MVP? По умолчанию — нет, включается флагом.
- Нужен ли UI сразу или достаточно CLI + Prometheus?
- TTL для очистки сырых событий (по умолчанию 60 дней) — устраивает?


## 18) Проверка и валидация после внедрения

- Запустить локально бот (или интеграционный тест), сгенерировать N обращений к LLM.
- Убедиться, что CLI api-usage-today показывает ненулевые значения.
- Пересобрать контейнер (docker compose up --build -d) и проверять, что значения за «сегодня» сохранились.
- Проверить /metrics: есть session_* и daily_* метрики, значения разумны.


---
Подготовлено как пошаговый план для быстрого исполнения другим ИИ с минимальным количеством уточнений. Все изменения держим в рамках существующей архитектуры, с хранением в SQLite и экспозицией метрик в Prometheus.

