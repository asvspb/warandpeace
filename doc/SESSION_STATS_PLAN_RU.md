# План реализации отслеживания статистики сессии и веб‑интерфейса для администраторов

## Цель и определения
Реализовать систему сбора и отображения статистики **текущей сессии** бота с веб‑интерфейсом для администраторов.

Определения и рамки:
- **Сессия**: период от запуска процесса бота до его завершения/перезапуска.
- **Источник истины для метрик**: Prometheus (через `prometheus_client`). Временный модуль `src/statistics.py` будет заменён/обёрнут.
- **Ключевые метрики сессии**:
  - Внешние HTTP‑вызовы (количество, ошибки, время)
  - Обработанные статьи
  - Потраченные токены (LLM)
  - Время старта сессии и аптайм

## Анализ текущей архитектуры

### Существующие компоненты:
1. **Метрики Prometheus** — уже реализованы в `src/metrics.py` и являются основным источником данных для этого плана.
2. **Веб‑интерфейс** — реализован в `src/webapp/` (FastAPI + Jinja2).
3. **База данных** — SQLite; не используется для метрик реального времени в рамках этой задачи.
4. **Бот** — основной процесс в `src/bot.py`.
5. **Временный модуль статистики** — `src/statistics.py` хранит счётчики в памяти без потокобезопасности и дублирует назначение Prometheus. Требуется консолидация.

### Существующие метрики (референс):
- `articles_ingested_total`
- `articles_posted_total`
- `errors_total`
- `job_duration_seconds`
- `last_article_age_minutes`
- `dlq_size`

## План реализации

### 1. Расширение и консолидация системы метрик

- [ ] **1.1. Добавить новые метрики в `src/metrics.py` и объявить их единым API:**
  ```python
  # src/metrics.py

  from prometheus_client import Counter, Gauge, Histogram
  
  # Внешние HTTP-вызовы (к источникам, LLM-провайдерам и т.п.)
  EXTERNAL_HTTP_REQUESTS_TOTAL = Counter(
      "external_http_requests_total",
      "Total number of outgoing HTTP requests",
      labelnames=("target", "method", "status_group"),  # target: rss|llm|tg|other; status_group: 2xx|4xx|5xx|timeout
  )

  EXTERNAL_HTTP_REQUEST_DURATION_SECONDS = Histogram(
      "external_http_request_duration_seconds",
      "Outgoing HTTP request duration (seconds)",
      labelnames=("target",),
      buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
  )

  # Статистика обработанных новостей за сессию
  SESSION_ARTICLES_PROCESSED = Counter(
      "session_articles_processed_total", "Number of articles processed in current session"
  )

  # Токены LLM (разделяем prompt/completion для большей наглядности)
  TOKENS_CONSUMED_PROMPT_TOTAL = Counter(
      "tokens_consumed_prompt_total", "Total prompt tokens consumed", labelnames=("provider", "model")
  )
  TOKENS_CONSUMED_COMPLETION_TOTAL = Counter(
      "tokens_consumed_completion_total", "Total completion tokens consumed", labelnames=("provider", "model")
  )

  # Время старта сессии (устанавливается один раз при загрузке приложения)
  SESSION_START_TIME_SECONDS = Gauge(
      "session_start_time_seconds", "Process session start time in seconds since UNIX epoch"
  )
  ```

- [ ] **1.2. Интеграция подсчёта в ключевые функции:**
  - Парсинг (`src/parser.py`, `src/async_parser.py`): инкремент `EXTERNAL_HTTP_REQUESTS_TOTAL` и наблюдение `EXTERNAL_HTTP_REQUEST_DURATION_SECONDS` для исходящих запросов; метка `target="rss"`.
  - Бот (`src/bot.py`): инкремент `SESSION_ARTICLES_PROCESSED` при обработке каждой статьи.
  - LLM‑клиент/суммаризатор (единая точка вызова): инкремент `TOKENS_CONSUMED_PROMPT_TOTAL` и `TOKENS_CONSUMED_COMPLETION_TOTAL` с метками `provider`, `model`; `target="llm"` для внешних HTTP.
  - Установить `SESSION_START_TIME_SECONDS.set(time.time())` при инициализации приложения.

- [ ] **1.3. Консолидация с `src/statistics.py`:**
  - Объявить модуль устаревшим и заменить его на тонкую обёртку, делегирующую в Prometheus‑метрики.
  - Исключить конкурентные увеличения счётчиков в двух местах (единственный источник — `metrics.py`).

### 2. Сервис статистики и формат ответов

- [ ] **2.1. Добавить в `src/webapp/services.py` функцию сборки агрегированной статистики из Prometheus REGISTRY:**
  ```python
  # src/webapp/services.py
  from prometheus_client import REGISTRY
  from datetime import datetime
  from typing import Dict, Any
  import time

  def get_session_stats() -> Dict[str, Any]:
      """
      Собирает статистику текущей сессии напрямую из регистра метрик Prometheus.
      """
      stats = {
          "external_http_requests": 0,
          "articles_processed": 0,
          "tokens_prompt": 0,
          "tokens_completion": 0,
          "session_start": None,
          "uptime_seconds": 0,
      }

      for metric in REGISTRY.collect():
          if metric.name == "external_http_requests_total":
              stats["external_http_requests"] = int(sum(sample.value for sample in metric.samples))
          elif metric.name == "session_articles_processed_total":
              stats["articles_processed"] = int(sum(sample.value for sample in metric.samples))
          elif metric.name == "tokens_consumed_prompt_total":
              stats["tokens_prompt"] = int(sum(sample.value for sample in metric.samples))
          elif metric.name == "tokens_consumed_completion_total":
              stats["tokens_completion"] = int(sum(sample.value for sample in metric.samples))
          elif metric.name == "session_start_time_seconds":
              # Берём последнее значение gauge
              samples = list(metric.samples)
              if samples:
                  session_start = float(samples[-1].value)
                  stats["session_start"] = datetime.fromtimestamp(session_start).isoformat()
                  stats["uptime_seconds"] = int(max(0, time.time() - session_start))

      return stats
  ```
  **Примечания:**
  - Функция избегает чтения лишних метрик и рассчитывает `uptime_seconds`.
  - Для частых вызовов рекомендуется кэшировать результат на 1–2 секунды, чтобы не перебирать REGISTRY каждый раз.

### 3. Веб‑интерфейс и API

- [ ] **3.1. Добавить маршруты в `src/webapp/routes_api.py`: HTML и JSON:**
  ```python
  # src/webapp/routes_api.py
  from fastapi import Request, Depends
  from fastapi.responses import HTMLResponse
  from fastapi import APIRouter
  from fastapi.responses import JSONResponse
  from . import services
  # ... другие импорты
  router = APIRouter()

  @router.get("/stats", response_class=HTMLResponse)
  async def session_stats(request: Request):
      """Отображает статистику текущей сессии."""
      # Предполагается, что _require_admin_session - это существующий механизм
      # проверки авторизации администратора.
      redir = _require_admin_session(request)
      if redir:
          return redir
      
      stats = services.get_session_stats()
      return templates.TemplateResponse("session_stats.html", {"request": request, "stats": stats})

  @router.get("/api/admin/stats")
  async def session_stats_json(request: Request):
      """JSON со статистикой текущей сессии (для админов)."""
      redir = _require_admin_session(request)
      if redir:
          return redir
      return JSONResponse(services.get_session_stats())
  ```

- [ ] **3.2. Создать шаблон `src/webapp/templates/session_stats.html`:**
  ```html
  {% extends "base.html" %}

  {% block title %}Статистика сессии - {{ super() }}{% endblock %}

  {% block content %}
      <header style="margin-bottom: 24px;">
          <h1>Статистика текущей сессии</h1>
          <p class="muted">Метрики работы бота с момента последнего перезапуска.</p>
      </header>
      
      <section>
          <div class="grid">
              <article>
                  <h4>Исходящих HTTP‑запросов</h4>
                  <h2><b>{{ stats.external_http_requests | int }}</b></h2>
              </article>
              <article>
                  <h4>Обработано новостей</h4>
                  <h2><b>{{ stats.articles_processed | int }}</b></h2>
              </article>
              <article>
                  <h4>Потрачено токенов (prompt)</h4>
                  <h2><b>{{ stats.tokens_prompt | int }}</b></h2>
              </article>
              <article>
                  <h4>Потрачено токенов (completion)</h4>
                  <h2><b>{{ stats.tokens_completion | int }}</b></h2>
              </article>
          </div>
          
          <article>
              <h4>Детали</h4>
              <p>Время начала сессии: {{ stats.session_start or '—' }}</p>
              <p>Аптайм: {{ (stats.uptime_seconds or 0) // 3600 }}ч {{ ((stats.uptime_seconds or 0) % 3600) // 60 }}м</p>
          </article>
      </section>
  {% endblock %}
  ```

- [ ] **3.3. Добавить ссылку в навигацию `src/webapp/templates/base.html`:**
  ```html
  <a href="/stats">Статистика</a>
  ```

### 4. Хранение статистики: Prometheus vs БД

- **Вариант 1: Только в памяти (Prometheus)** — **выбран для этой задачи.**
  - **Плюсы:** простота, отсутствие лишних зависимостей, идеально для RT‑метрик; доступны через `/metrics` и веб‑страницу.
  - **Минусы:** сброс при перезапуске приложения — соответствует определению «текущая сессия».

- **Вариант 2: В БД (Для будущего развития)**
  - **Назначение:** Сбор и хранение *исторических* данных для анализа трендов.
  - **Реализация:** Потребует создания таблицы `session_history` или аналогичной, и периодической записи метрик в БД. Это выходит за рамки текущей задачи, но является логичным следующим шагом.

## Безопасность
- [ ] Убедиться, что эндпоинты `/stats` и `/api/admin/stats` защищены существующей аутентификацией администраторов.
- [ ] Исключить чувствительные данные из метрик и ответов (API‑ключи, user‑IDs и т.п.).
- [ ] Ограничить кардинальность меток: заранее фиксированные значения `target`/`status_group`.

## Тестирование
- [ ] **Модульное:**
  - [ ] Использовать отдельный `CollectorRegistry` в тестах, регистрировать нужные метрики локально.
  - [ ] Проверить агрегацию `get_session_stats()` и вычисление `uptime_seconds`.
- [ ] **Интеграционное:**
  - [ ] Запустить бота, выполнить несколько операций (парсинг, обработка, LLM‑вызовы).
  - [ ] Проверить `/stats` и `/api/admin/stats` на корректные значения и формат.
  - [ ] Убедиться, что неавторизованный доступ отклоняется.

## План реализации по этапам

- [ ] **Этап 1: Подготовка (1–2 часа)**
  - [ ] Расширить `src/metrics.py` новыми метриками; установить `SESSION_START_TIME_SECONDS` при старте.
  - [ ] Добавить HTML и JSON‑маршруты; создать шаблон `src/webapp/templates/session_stats.html` и ссылку в `base.html`.
  - [ ] Обновить `src/statistics.py`: пометить deprecated и/или сделать обёрткой над Prometheus.

- [ ] **Этап 2: Интеграция подсчёта (3–4 часа)**
  - [ ] Интегрировать метрики в `src/parser.py`, `src/async_parser.py` (исходящие HTTP).
  - [ ] Интегрировать `SESSION_ARTICLES_PROCESSED` в `src/bot.py`.
  - [ ] Интегрировать учёт токенов в точке вызова LLM (обновить адаптер/клиент).

- [ ] **Этап 3: Веб‑интерфейс (2–3 часа)**
  - [ ] Реализовать `get_session_stats()` с кэшированием результата (опционально, 1–2 с).
  - [ ] Подключить сервис к HTML/JSON маршрутам и шаблону.
  - [ ] Добавить автообновление на странице (meta refresh или JS раз в 5–10 с; опционально).

- [ ] **Этап 4: Тестирование и отладка (2–3 часа)**
  - [ ] Провести модульные и интеграционные тесты.
  - [ ] Отладить замеченные проблемы.

## Дополнительно (опционально, позже)
- [ ] SSE/WebSocket для live‑обновления карточек без перезагрузки.
- [ ] Мини‑графики (sparklines) для скорости статей и запросов.
- [ ] Prometheus recording rules и готовые PromQL:
  - Средняя скорость статей за 5м: `sum(rate(session_articles_processed_total[5m]))`.
  - Ошибки внешних HTTP за 5м: `sum(rate(external_http_requests_total{status_group=~"4..|5..|timeout"}[5m]))`.
  - Аптайм: `time() - session_start_time_seconds`.

## Ограничения и подводные камни
- При мультипроцессном запуске (Gunicorn) нужен `prometheus_multiproc_dir` и специальная инициализация клиента.
- Избыточные метки могут вызвать высокую кардинальность. Использовать фиксированные значения `target` и агрегацию по группам статусов.
- Сканирование `REGISTRY` может быть относительно дорогим — использовать кэширование или прямые ссылки на метрики при необходимости.

## Ожидаемый результат
- Администраторы могут просматривать ключевые метрики производительности бота в реальном времени через защищенный веб-интерфейс.
- Доступна JSON‑версия статистики для автоматизации/интеграций.
- Система реализована с использованием существующих инструментов (Prometheus, FastAPI) и готова к расширению.

## Критерии приёмки
- Отображаются корректные значения на `/stats` и корректный JSON на `/api/admin/stats`.
- При перезапуске приложения `session_start_time_seconds` обновляется, счётчики сессии обнуляются.
- В отчётах отсутствуют чувствительные данные; доступ закрыт для неавторизованных пользователей.
