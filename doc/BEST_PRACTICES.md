### 📘 Project Best Practices

#### 1. Project Purpose  
The project is a Telegram bot that monitors the Russian geopolitics news site "warandpeace.ru", parses new articles, generates short AI-based summaries (using Google Gemini & OpenRouter LLMs), and posts them automatically to a Telegram channel.  
Additional features include periodic digests, health-checks for the parser and API keys, statistics, and a Dockerised deployment workflow.

#### 2. Project Structure
- `src/` – production application code
  - `bot.py` – main entry point; starts the Telegram bot, schedules jobs and command handlers.
  - `parser.py` / `async_parser.py` – scrape the web-site, convert dates, return article metadata and full text.
  - `summarizer.py` – local & remote LLM summarisation utilities.
  - `database.py` – SQLite helper functions (init, CRUD, statistics) used by the bot.
  - `config.py` – loads environment variables, API keys and settings.
  - `healthcheck.py` – validates that the parser CSS selectors still match the target site.
  - Aux files (`get_todays_articles.py`, etc.) – one-off helpers.
- `tests/` – pytest test-suite for parser, summariser and DB helpers.
- `scripts/` – CLI helpers (e.g. DB migrations, manual triggers).
- `database/` – SQLite database file lives here (mounted volume in Docker).
- `logs/` – runtime logs (Docker volume).
- `Dockerfile`, `docker-compose.yml` – containerisation and orchestration.
- `.env` – secrets & runtime configuration (never commit real values).

Key separation of concerns:
- **Domain logic**: article parsing, summarisation, digest creation.
- **Infrastructure/IO**: Telegram API, HTTP requests, database, Docker.
- **Orchestration**: job-queue scheduling in `bot.py`.

#### 3. Test Strategy
- **Framework**: pytest (+ unittest.mock).
- **Location & Naming**: tests live in `tests/`, file names start with `test_`.
- **Philosophy**:
  - Unit test critical pure functions (`_parse_custom_date`, summariser helpers, DB helpers).
  - Mock external HTTP requests and Telegram API to keep tests deterministic.
  - Integration tests (optional) may spin up a temporary SQLite DB or Docker service.
- **Coverage Goal**: ≥80 % lines for core modules (`parser`, `summarizer`, `database`).
- **Fixtures**: use pytest fixtures for mock HTML snippets & monkey-patching requests.
- **CI**: run `pytest -q` in Docker build or GitHub Actions.

#### 4. Code Style
- **Language**: Python 3.11+, favour type hints (`typing`) for all public functions.
- **Asynchronous IO**: use `asyncio` in bot handlers & heavy IO (HTTP calls, DB) – avoid blocking operations in event loop.
- **Naming**: snake_case for variables & functions, PascalCase for classes, UPPER_SNAKE for constants.
- **Logging**: use the stdlib `logging` module; never `print` in production code.
- **Docstrings**: Google-style docstrings for public modules & functions; describe return types and exceptions.
- **Error Handling**: catch **expected** errors close to the source; log and re-raise or convert to domain-specific errors. Use `tenacity` for retries on flaky IO.

#### 5. Common Patterns
- **Factory / Adapter**: helper functions wrap external services (LLMs, Telegram) so internals are decoupled.
- **Job Scheduling**: `Application.job_queue.run_repeating` is the canonical way to schedule recurring tasks.
- **Dependency Injection**: configuration (API keys, URLs) flows via `config.py` instead of hard-coding.
- **Retry Logic**: `tenacity` decorators for network calls.
- **DTOs**: article dicts have a consistent shape `{title, link, published_at}` throughout the codebase.

#### 6. Do's and Don'ts
- ✅ DO keep async & blocking code separate; wrap blocking calls with `asyncio.to_thread`.
- ✅ DO validate all external HTML with BeautifulSoup before processing.
- ✅ DO write tests for any bug fix or new feature.
- ✅ DO commit new dependencies to `requirements.txt` and pin versions.
- ✅ DO use environment variables for secrets; never hard-code tokens.
- ❌ DON’T publish `.env` or database files to VCS.
- ❌ DON’T catch bare `Exception` without re-raising/logging.
- ❌ DON’T log sensitive information (API keys, personal data).
- ❌ DON’T block the event loop with long `time.sleep`; use `asyncio.sleep`.

#### 7. Tools & Dependencies
- **python-telegram-bot** – interaction with Telegram API & job queue.
- **google-generativeai / OpenRouter** – LLM summarisation.
- **requests & BeautifulSoup4** – HTTP scraping & parsing.
- **feedparser** – RSS/Atom feeds (future use).
- **pytest** – testing framework.
- **tenacity** – retry logic for unreliable networks.

Setup:
```bash
# Local dev
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=... # plus other envs
python -m src.bot

# Docker
docker-compose up -d --build
```

#### 8. Other Notes
- The target site (`warandpeace.ru`) uses Windows-1251 encoding; always set `response.encoding` before `.text`.
- Parser selectors are brittle; keep `healthcheck.py` up to date after any site redesign.
- LLM usage must stay within GPT-4-equivalent token limits; summarise long texts progressively.
- When adding new bot commands, group them logically and register in `post_init`.
- Keep database migrations incremental; avoid destructive schema changes in production.

##### Planned Migration to PostgreSQL
We currently rely on SQLite for simplicity. To prepare for future traffic growth and advanced search features, we plan to migrate the persistence layer to PostgreSQL. Key points:

1. **Roadmap**
   - Phase 0 (now) — keep schema neutral (ANSI SQL) and wrap DB access via helper functions.
   - Phase 1 — introduce SQLAlchemy and Alembic migrations while still talking to SQLite.
   - Phase 2 — spin up a Postgres instance (Docker), apply the same migrations, run tests and the bot in staging.
   - Phase 3 — update production `.env` to `postgresql://` DSN and deprecate SQLite.

2. **Schema v3 Highlights**
   - `sources`, `articles`, `article_texts`, `digests` tables (see design doc).
   - Use `ENUM` for status fields, `BOOLEAN` for flags, and indexes on `(published_at)` and `(status)`.
   - Heavy columns (`original_content`, `summary_long`) live in `article_texts` to keep `articles` hot.

3. **Benefits we expect**
   - Full-text search (`GIN` index on `article_texts.original_content`).
   - Ability to store embeddings (`pgvector`) and run semantic search.
   - Replication & point-in-time restore for better reliability.
   - ENUM + CHECK constraints for stricter data consistency.

4. **Backwards compatibility**
   - All read/write helpers will use SQLAlchemy sessions, so switching engines requires only DSN change.
   - Test suite will run for both SQLite and Postgres in CI to guarantee parity.

5. **Trigger to decide migration**
   - >50 k articles *or* requirement for full-text/semantic search.
   - Multi-source expansion beyond `warandpeace.ru`.
