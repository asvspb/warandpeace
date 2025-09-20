### 📘 Project Best Practices

#### 1. Project Purpose
This repository hosts a Telegram bot and data-processing pipeline that tracks new articles on the Russian geopolitical news website “warandpeace.ru”, stores raw articles in a local database, generates AI-based summaries (Google Gemini / Mistral), and posts both instant updates and periodic digests to a Telegram channel.

#### 2. Project Structure
- `src/` – production source code
  - `bot.py` – main entry-point; starts the Telegram bot and schedules background jobs.
  - `parser.py`, `async_parser.py` – scrape web pages, normalise dates, return metadata + full text.
  - `summarizer.py` – helpers to call external LLM providers and compose prompts.
- `database.py` – low-level persistence helpers (PostgreSQL via SQLAlchemy).
  - `config.py` – loads `.env` variables and centralises runtime configuration.
  - `healthcheck.py` – planned helper to verify selectors (not present in current repo).
- `tests/` – pytest suite covering parsing, summarisation and DB helpers.
- `scripts/` – one-off CLI tools (DB migrations, manual re-ingest, etc.).
- `doc/` – architecture specs (e.g. `ALGORITHM_NEWS_DB.md`).
- `Dockerfile`, `docker-compose.yml` – containerisation & local orchestration.

Key separation of concerns:
1. **Domain logic** (scraping, summarisation, digest composition).
2. **Infrastructure / I/O** (Telegram API, HTTP requests, database, Docker).
3. **Orchestration** (job queue and scheduling in `bot.py`).

#### 3. Test Strategy
- **Framework**: Pytest (+ `unittest.mock`).
- **Layout & naming**: tests live in `tests/`, file names start with `test_`.
- **Philosophy**
  - Unit-test critical pure functions (`_parse_custom_date`, summariser helpers, DB utils).
  - Mock external HTTP requests and Telegram API to keep tests deterministic.
- **Integration tests** run against a PostgreSQL service (Docker) when needed.
- **Coverage target**: ≥ 80 % lines for core modules (`parser`, `summarizer`, `database`).
- **Fixtures**: use pytest fixtures for HTML snippets and monkey-patching requests.
- **CI**: run `pytest -q` inside Docker or GitHub Actions on every PR.

#### 4. Code Style
- **Language**: Python 3.12 + with full type hints for all public functions.
- **Async IO**: use `asyncio` for network-bound code; avoid blocking the event loop.
- **Naming**: `snake_case` for variables & functions, `PascalCase` for classes, `UPPER_SNAKE` for constants.
- **Logging**: standard `logging` module; never use `print` in production code.
- **Docstrings**: Google-style docstrings on all public modules & functions; describe return types and raised exceptions.
- **Error handling**: catch **expected** errors close to the source; log and re-raise or wrap in domain-specific exceptions. Use `tenacity` for retry logic on flaky I/O.

#### 5. Common Patterns
- **Factory / Adapter**: helper modules wrap external services (LLM, Telegram) to keep internals loosely coupled.
- **Task scheduling**: `Application.job_queue.run_repeating` is the canonical way to schedule recurring jobs.
- **Dependency injection**: config (API keys, URLs) is passed through `config.py`, not hard-coded.
- **Retry decorators**: `tenacity` handles exponential back-off and jitter for network calls.
- **DTOs**: article dictionaries follow a uniform schema `{title, link, published_at}` across the codebase.

#### 6. Do's and Don'ts
- ✅ **Do** separate async and blocking code; wrap blocking calls with `asyncio.to_thread`.
- ✅ **Do** validate all external HTML with BeautifulSoup before processing.
- ✅ **Do** write tests for every bug-fix or new feature.
- ✅ **Do** pin versions for new dependencies in `requirements.txt`.
- ✅ **Do** load secrets from environment variables; never hard-code tokens.
- ❌ **Don’t** commit `.env` files or database dumps to VCS.
- ❌ **Don’t** swallow bare `Exception` without re-raising/logging.
- ❌ **Don’t** log sensitive data (API keys, personal info).
- ❌ **Don’t** block the event loop with long `time.sleep`; use `asyncio.sleep` instead.

#### 7. Tools & Dependencies
| Library | Purpose |
|---------|---------|
| `python-telegram-bot` | Telegram API client & job queue |
| `google-generativeai`, `mistralai` | LLM providers for summarisation |
| `requests`, `beautifulsoup4` | HTTP scraping & parsing |
| `feedparser` | (Future) RSS/Atom ingestion |
| `pytest` | Test framework |
| `tenacity` | Resilient retry decorators |
| `SQLAlchemy`, `alembic` | ORM & migrations for PostgreSQL |

Setup (local):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...  # plus other env vars
python -m src.bot
```
Docker compose:
```bash
docker compose up -d --build
```

#### 8. Other Notes
- Target site uses Windows-1251 encoding; always set `response.encoding` before reading `.text`.
- Parser selectors are fragile; keep `healthcheck.py` up-to-date after any site redesign.
- LLM usage must respect token limits (equiv. GPT-4); chunk long texts when necessary.
- When adding new bot commands, group logically and register them in `post_init`.
- Keep DB migrations incremental; avoid destructive schema changes in production.
- PostgreSQL is the production backend; schema is managed via SQLAlchemy (see `src/db/schema.py`).

#### 9. Observability & Metrics
- Enable Prometheus metrics server via env: `METRICS_ENABLED=true`, `METRICS_PORT=8000` (default). The bot exposes 8000 inside the container; by default metrics are published on the host via `wg-client` port mapping at `http://localhost:9090/metrics`.
- Exported metrics (see `src/metrics.py`):
  - `articles_ingested_total` (Counter)
  - `articles_posted_total` (Counter)
  - `errors_total{type}` (Counter)
  - `job_duration_seconds` (Histogram)
  - `last_article_age_minutes` (Gauge)
  - `dlq_size` (Gauge)
- In test/dev without `prometheus_client`, metrics degrade gracefully (no-op).

#### 10. Ingest vs Summarisation
- Keep raw-ingest and summarisation decoupled. Ingest should not depend on LLM quotas.
- Store canonical URL, title, `published_at`, and full cleaned `content` first. Summaries are written later.
- Provide separate CLI for each stage (`ingest-page`, `backfill-range`, `reconcile`, `summarize-range`).

#### 11. DLQ (Dead-letter Queue)
- Send persistent errors to `dlq` with `entity_type`, `entity_ref`, `error_code`, payload, and increment `attempts`.
- Monitor with `dlq-show`; retry with `dlq-retry` (bounded batch, backoff). Track size via `dlq_size` gauge.
- Budget retries and avoid hot-looping (respect exponential backoff in scrapers).

#### 12. URL Canonicalisation
- Always canonicalise with `src/url_utils.canonicalize_url` before any DB upsert or duplicate check.
- Rules: force https, lowercase host, strip fragments and tracking params, sort query, normalise path and ports.

#### 13. Database & Migrations (PostgreSQL runtime)
- Схема создаётся через SQLAlchemy (`scripts/manage.py db-init-sqlalchemy`). Везде используется PostgreSQL.
- Предпочитать аддитивные изменения. Для PG использовать `ON CONFLICT` для идемпотентных upsert.
- Полезные индексы: `(published_at)`, `(backfill_status)`, `(content_hash)`; для PG дополнительно FTS/pg_trgm по необходимости.

#### 14. Duplicates & Near-duplicates
- Compute and persist `content_hash` (SHA-256) for exact duplicate detection and reporting.
- Use `content-hash-report` to list groups; `near-duplicates` for shingled Jaccard similarity over recent content.
- When merging duplicates, keep the earliest `published_at` and higher-quality `content`.

#### 15. Scheduling & Backpressure
- For periodic jobs, use bounded parallelism and rate limits; implement exponential backoff on network errors.
- Use scheduler settings like `coalesce`, `misfire_grace_time`, `max_instances=1`, add jitter to avoid thundering herd.
- Persist checkpoints for long backfills (date/page/last_link) to allow resumption.

#### 16. Security & Compliance
- Treat logs and scraped content as potentially sensitive; avoid logging PII, mask secrets.
- Keep secrets in `.env`/vault; never commit real tokens.
- Define retention windows for logs and raw content where applicable.

#### 17. CLI Quick Reference
- Ingest latest page: `python scripts/manage.py ingest-page --page 1 --limit 10`
- Backfill range: `python scripts/manage.py backfill-range --from-date 2025-08-01 --to-date 2025-08-07`
- Reconcile last N days: `python scripts/manage.py reconcile --since-days 7`
- Summarise range: `python scripts/manage.py summarize-range --from-date 2025-08-01 --to-date 2025-08-07`
- DLQ: `dlq-show`, `dlq-retry`
- Duplicate reports: `content-hash-report`, `near-duplicates`

Tip: backfill «с начала года по сегодня» (Docker Compose):
```bash
docker compose run --rm telegram-bot \
  python3 scripts/manage.py backfill-range \
  --from-date "$(date +%Y)-01-01" --to-date "$(date +%F)"
```
