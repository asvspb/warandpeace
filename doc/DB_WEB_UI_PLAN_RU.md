# Веб‑интерфейс навигации по базе статей: оптимизированный план (MVP → Iterations)

## 0) Коротко о целях
- Быстро дать удобный просмотр архива: список, фильтры по дате/поиску, деталка с полным текстом.
- Только чтение. Без риска «сломать» бота/БД.
- Простая установка через docker compose.

## 1) Что делаем / не делаем (MVP)
- ✅ Делаем (MVP):
  - Список статей с фильтрами и пагинацией
  - Детальная страница статьи (полный `content`)
  - Дубликаты по `content_hash` (группы → список)
  - Просмотр DLQ
  - `/healthz`, `/metrics`, базовая авторизация
- ❌ Не делаем (перенос в Iteration 2+):
  - Почти‑дубликаты (Jaccard), графики/дашборды, WebSockets/SSE, редактирование/повторные публикации

## 2) Выбор решений (обоснованно)
- Backend: FastAPI + Jinja2 (SSR)
  - Причина: минимальная сложность, быстрый рендер, не нужен SPA/React.
- Веб‑сервис — отдельный контейнер `web` (тот же образ), читает БД read‑only.
  - Причина: изоляция от бота, отсутствие блокировок БД, чёткие порты.
- БД: существующая SQLite `database/articles.db` (только чтение).
- Аутентификация: Basic Auth по env (вкл/выкл).
- Метрики: `prometheus-client` (уже используется в проекте).
- Поиск: LIKE по `title` и диапазон дат (FTS5 как улучшение позже).

## 3) Пользовательские сценарии и страницы
- Главная `/`
  - Сводка: всего статей; дата последней публикации; ссылки в разделы
- Список `/articles`
  - Фильтры: `from`/`to` (дата), `q` (в заголовке), `has_content` (по умолчанию 1)
  - Колонки: дата, заголовок (ссылка на деталку), оригинальная ссылка, `canonical_link`
  - Пагинация: `page`, `page_size` (по умолчанию 50, максимум 200)
- Деталка `/articles/{id}`
  - Заголовок, даты, ссылки, полный `content` (экранированный)
- Дубликаты `/duplicates`
  - Группы по `content_hash` (хэш, количество) → переход к списку статей группы
- DLQ `/dlq`
  - Таблица элементов (read‑only), фильтры по типу/дате
- Служебные: `/healthz`, `/metrics`

## 4) HTTP API (минимум, выключаемый)
- GET `/api/articles` — список (те же фильтры, что и страница), JSON
- GET `/api/articles/{id}` — деталка, JSON
- Опция: по умолчанию API закрыт (env `WEB_API_ENABLED=false`), работает только SSR

## 5) Безопасность
- Только SELECT‑запросы; примонтировать БД как read‑only
- Basic Auth: `WEB_BASIC_AUTH_USER`, `WEB_BASIC_AUTH_PASSWORD`
- Заголовки безопасности (CSP, X-Frame-Options, Referrer-Policy)
- Экранировать HTML при показе `content`

## 6) Производительность
- Использовать существующие индексы: `published_at`, `content_hash`
- Пагинация `LIMIT/OFFSET` (достаточно для текущих объёмов)
- Максимальный `page_size` ограничить 200
- Улучшение (Iteration 2): FTS5 по (title, content) и keyset pagination

## 7) Переменные окружения
- `WEB_ENABLED=true` — включить приложение
- `WEB_HOST=0.0.0.0`, `WEB_PORT=8080`
- `WEB_PAGE_SIZE=50`, `WEB_MAX_PAGE_SIZE=200`
- `WEB_BASIC_AUTH_USER=admin`, `WEB_BASIC_AUTH_PASSWORD=...`
- `WEB_API_ENABLED=false`

## 8) Структура проекта
- `src/webapp/server.py` — инициализация FastAPI, базовая авторизация, метрики, маршруты
- `src/webapp/routes_articles.py` — список/деталка, `/api/articles*`
- `src/webapp/routes_duplicates.py` — дубликаты, `/api/duplicates`
- `src/webapp/routes_dlq.py` — DLQ, `/api/dlq`
- `src/webapp/services.py` — обращение к БД (через `src.database.get_db_connection()`)
- `src/webapp/templates/` — `base.html`, `index.html`, `articles_list.html`, `article_detail.html`, `duplicates.html`, `dlq.html`
- `src/webapp/static/` — стили

## 9) План работ (чётко и коротко)
- Шаг 1 (MVP каркас): сервер, базовая авторизация, `/healthz`, `/metrics`, каркас шаблонов — 2–3 часа
- Шаг 2 (Статьи): `/articles` (фильтры, пагинация), `/articles/{id}` — 3–4 часа
- Шаг 3 (Дубликаты, DLQ) — 2–3 часа
- Шаг 4 (API, выключаемое), документация, тесты — 2 часа
- Итого MVP: 1 день чистого времени

## 10) docker‑compose (фрагмент)
```yaml
web:
  build: .
  command: uvicorn src.webapp.server:app --host 0.0.0.0 --port ${WEB_PORT:-8080}
  env_file: .env
  environment:
    - WEB_ENABLED=true
    - WEB_PORT=${WEB_PORT:-8080}
  volumes:
    - ./database:/app/database:ro
  ports:
    - "${WEB_PORT:-8080}:8080"
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"]
    interval: 30s
    timeout: 3s
    retries: 3
```

## 11) Критерии приёмки (Definition of Done)
- Открывается `/`, список и деталка работают, фильтры корректны, пагинация ограничивает объём
- Дубликаты и DLQ отображаются, без ошибок SQL
- Доступ защищён базовой аутентификацией (при включенной опции)
- Метрики на `/metrics`, `/healthz` возвращает 200
- Docker‑сервис `web` запускается одной командой, БД примонтирована read‑only

## 12) Iteration 2 (после MVP)
- FTS5 (полнотекстовый поиск), keyset pagination
- Экспорт CSV/JSON из списка
- Примитивные графики (Chart.js) на `/` — динамика публикаций, доля с резюме
- Почти‑дубликаты (Jaccard) как отчёт on‑demand
- WebSockets/SSE для «живого» обновления (необязательно)

—
Этот план отобрал оптимальные предложения: отдельный лёгкий SSR‑веб, read‑only доступ к SQLite, базовая авторизация, минимум зависимостей и быстрый путь к результату. Улучшения (FTS5/графики) предусмотрены отдельной итерацией без усложнения MVP.

## 13) План устранения недочётов (Action Plan)

- **Статика (`/static`)**
  - Создать каталог `src/webapp/static/` и файл `src/webapp/static/styles.css`.
  - Оставить монтирование `StaticFiles` в приложении.
  - В `templates/base.html` подключить локальные стили.

- **Базовая авторизация (исправить способ подключения)**
  - Удалить попытку добавления `HTTPBasic` как middleware.
  - Использовать зависимость `basic_auth_dependency` при подключении роутеров:
    ```python
    from fastapi import Depends
    # ...
    if auth_user and auth_pass:
        app.include_router(routes_articles.router, tags=["Frontend"], dependencies=[Depends(basic_auth_dependency)])
        app.include_router(routes_duplicates.router, tags=["Frontend"], dependencies=[Depends(basic_auth_dependency)])
        app.include_router(routes_dlq.router, tags=["Frontend"], dependencies=[Depends(basic_auth_dependency)])
        if os.getenv("WEB_API_ENABLED", "false").lower() == "true":
            app.include_router(routes_api.router, tags=["API"], dependencies=[Depends(basic_auth_dependency)])
    else:
        app.include_router(routes_articles.router, tags=["Frontend"])
        app.include_router(routes_duplicates.router, tags=["Frontend"])
        app.include_router(routes_dlq.router, tags=["Frontend"])
        if os.getenv("WEB_API_ENABLED", "false").lower() == "true":
            app.include_router(routes_api.router, tags=["API"])
    ```
  - Оставить `/healthz` и `/metrics` публичными.

- **Заголовки безопасности**
  - Добавить middleware, проставляющее заголовки:
    - `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'`
    - `X-Frame-Options: DENY`
    - `Referrer-Policy: no-referrer`
    - `X-Content-Type-Options: nosniff`
    - `Permissions-Policy: geolocation=()`

- **Фильтр `has_content` (включён по умолчанию)**
  - В `services.get_articles(...)` добавить параметр `has_content: int = 1` и условие в `SELECT`/`COUNT`:
    `AND content IS NOT NULL AND content <> ''` при `has_content == 1`.
  - В `routes_articles.list_articles` добавить `has_content: int = Query(1, ge=0, le=1)` и передавать его в сервис.
  - В форме на `/articles` добавить чекбокс "Только с текстом" (включён по умолчанию).

- **Колонка `canonical_link` в списке**
  - В `templates/articles_list.html` добавить колонку и ссылку на канонический URL (если есть).

- **docker-compose: порт из ENV**
  - В команде запуска использовать `${WEB_PORT:-8080}`:
    ```yaml
    command: uvicorn src.webapp.server:app --host 0.0.0.0 --port ${WEB_PORT:-8080}
    ```

- **ENV уточнение**
  - `WEB_ENABLED` влияет только на запуск через `python src/webapp/server.py`. В Docker сервис стартует через `uvicorn`, переменная не используется.

- **Тесты (обязательные)**
  - Auth: 401 без заголовка, 200 с корректными данными.
  - Security headers: присутствуют на HTML‑ответах.
  - Фильтр `has_content`: исключает пустые статьи.
  - Наличие колонки `canonical_link` на странице.
  - Статика: `GET /static/styles.css` → 200.

- **Документация**
  - Обновить `DEPLOYMENT.md`, `doc/PLANNING.md` и этот файл с учётом auth, портов, фильтров, стилей.

## 14) UI в стиле «Джобс / iOS» (гайд по дизайну)

- **Принципы**
  - Минимализм, фокус на контенте, визуальная иерархия.
  - Мягкие скругления, деликатные тени, отсутствие визуального шума.

- **Типографика**
  - Шрифтовой стек: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", Inter, "Segoe UI", Roboto, system-ui, sans-serif`.
  - Базовый размер 16–17px, увеличенные межстрочные интервалы.

- **Цвета (переменные CSS)**
  - `--bg: #FFFFFF; --fg: #111111; --muted: #6B7280; --accent: #007AFF; --border: #E5E7EB;`
  - Акцент iOS Blue: `#007AFF` для ссылок и кнопок.

- **Компоненты**
  - Навигация: тонкая верхняя панель, бренд слева, ссылки справа.
  - Карточки: скругление 12px, лёгкая тень.
  - Таблицы: тонкие горизонтальные разделители, большой line‑height, без тяжёлых рамок.
  - Формы: мягкие поля, скругление 10–12px, контрастный фокус.
  - Пагинация: минималистичные ссылки, текущая страница — полужирно/приглушённо.

- **Микровзаимодействия**
  - Плавные hover/active (transition 150–200ms), фокус‑кольцо в акцентном цвете.

- **Реализация стилей**
  - Создать `src/webapp/static/styles.css` и подключить в `base.html`.
  - Использовать классы: `.container`, `.card`, `.table`, `.btn`, `.muted`, `.grid`.
  - Поддержать тёмную тему позже через `@media (prefers-color-scheme: dark)`.

- **Скелет `styles.css` (фрагмент)**
  ```css
  :root { --bg:#fff; --fg:#111; --muted:#6B7280; --accent:#007AFF; --border:#E5E7EB; --radius:12px; --radius-sm:10px; --shadow:0 6px 24px rgba(0,0,0,0.06); }
  *{ box-sizing:border-box; }
  html,body{ margin:0; padding:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",Inter,"Segoe UI",Roboto,system-ui,sans-serif; line-height:1.45; }
  nav{ display:flex; justify-content:space-between; align-items:center; padding:12px 20px; border-bottom:1px solid var(--border); }
  .container{ max-width:1100px; margin:0 auto; padding:24px 16px; }
  h1,h2,h3{ margin:0 0 12px; letter-spacing:-0.01em; }
  a{ color:var(--accent); text-decoration:none; }
  a:hover{ filter:brightness(0.9); }
  .card{ background:#fff; border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:16px; }
  .table{ width:100%; border-collapse:collapse; }
  .table tr{ border-bottom:1px solid var(--border); }
  .table th,.table td{ padding:12px 8px; text-align:left; }
  input,select,button{ border:1px solid var(--border); border-radius:var(--radius-sm); padding:10px 12px; background:#fff; }
  button,.btn{ background:var(--accent); color:#fff; border:none; padding:10px 14px; border-radius:var(--radius-sm); }
  button:hover,.btn:hover{ filter:brightness(0.9); cursor:pointer; }
  .muted{ color:var(--muted); }
  ```

- **Адаптация шаблонов**
  - Обернуть панели статистики в `.card` на `/`.
  - Таблицам добавить класс `.table`; кнопкам — `.btn`.
  - Упростить навигацию до бренда и трёх ссылок.

- **Текущее состояние и задачи**
  • Исправил Basic Auth: добавлен middleware с проверкой заголовка и исключениями для /healthz, /metrics, /static.
  • Добавил security headers.
  • Создал src/webapp/static/styles.css и подключил в base.html.
  • Добавил fallback в get_dashboard_stats при отсутствии таблиц (тестовый стенд).
  • Все тесты проходят: 31 passed.

  Коротко:
  • Готово к локальному и docker-прогону.
  • Дальше по плану: внедрить фильтр has_content и колонку canonical_link в список, выкатить стили iOS-гайда, и поправить
    docker-compose порт на ${WEB_PORT:-8080} (эти правки еще не внесены).