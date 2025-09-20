from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    MetaData, Table, Column,
    BigInteger, Integer, String, Text, DateTime, LargeBinary, Boolean, Float,
    Index, UniqueConstraint, CheckConstraint, func, text as sql_text
)
from sqlalchemy.engine import Connection, Engine


metadata = MetaData()

# --- Tables ---
articles = Table(
    "articles",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False),
    Column("canonical_link", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("content", Text),
    Column("content_hash", Text),
    Column("summary_text", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("backfill_status", String, nullable=True),
    UniqueConstraint("canonical_link", name="uq_articles_canonical_link"),
)
Index("idx_articles_published_at", articles.c.published_at)
Index("idx_articles_backfill_status", articles.c.backfill_status)
Index("idx_articles_content_hash", articles.c.content_hash)


dlq = Table(
    "dlq",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("entity_type", Text, nullable=False),
    Column("entity_ref", Text, nullable=False),
    Column("error_code", Text),
    Column("error_payload", Text),
    Column("attempts", Integer, server_default="1"),
    Column("first_seen_at", DateTime(timezone=True), server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), server_default=func.now()),
)
Index("idx_dlq_entity", dlq.c.entity_type, dlq.c.entity_ref)


digests = Table(
    "digests",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("period", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


pending_publications = Table(
    "pending_publications",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("summary_text", Text, nullable=False),
    Column("attempts", Integer, server_default="0"),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("url", name="uq_pending_publications_url"),
)
Index("idx_pending_publications_created_at", pending_publications.c.created_at)


webauthn_credential = Table(
    "webauthn_credential",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=False),
    Column("credential_id", LargeBinary, nullable=False),
    Column("public_key", LargeBinary, nullable=False),
    Column("sign_count", Integer, nullable=False, server_default="0"),
    Column("transports", Text),
    Column("aaguid", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("last_used_at", DateTime(timezone=True)),
    UniqueConstraint("credential_id", name="uq_webauthn_credential_id"),
)
Index("idx_webauthn_user", webauthn_credential.c.user_id)


api_usage_events = Table(
    "api_usage_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ts_utc", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text),
    Column("api_key_hash", Text),
    Column("endpoint", Text),
    Column("req_count", Integer, server_default="1"),
    Column("success", Integer, nullable=False),
    Column("http_status", Integer),
    Column("latency_ms", Integer),
    Column("tokens_in", Integer, server_default="0"),
    Column("tokens_out", Integer, server_default="0"),
    Column("cost_usd", Float, server_default="0.0"),
    Column("error_code", Text),
    Column("extra_json", Text),
)
Index("idx_api_usage_events_ts", api_usage_events.c.ts_utc)
Index("idx_api_usage_events_provider_model", api_usage_events.c.provider, api_usage_events.c.model)
Index("idx_api_usage_events_api_key_hash", api_usage_events.c.api_key_hash)


api_usage_daily = Table(
    "api_usage_daily",
    metadata,
    Column("day_utc", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text),
    Column("api_key_hash", Text),
    Column("req_count", Integer, server_default="0"),
    Column("success_count", Integer, server_default="0"),
    Column("tokens_in_total", Integer, server_default="0"),
    Column("tokens_out_total", Integer, server_default="0"),
    Column("cost_usd_total", Float, server_default="0.0"),
    Column("latency_ms_sum", Integer, server_default="0"),
)

Index("idx_api_usage_daily_provider", api_usage_daily.c.provider)

# Composite PK: we emulate via a UNIQUE + explicit PK where supported by SQLAlchemy using PrimaryKeyConstraint
from sqlalchemy import PrimaryKeyConstraint
api_usage_daily.append_constraint(
    PrimaryKeyConstraint(
        api_usage_daily.c.day_utc,
        api_usage_daily.c.provider,
        api_usage_daily.c.model,
        api_usage_daily.c.api_key_hash,
        name="pk_api_usage_daily"
    )
)


sessions = Table(
    "sessions",
    metadata,
    Column("session_id", Text, primary_key=True),
    Column("started_at_utc", Text, nullable=False),
    Column("ended_at_utc", Text),
    Column("git_sha", Text),
    Column("container_id", Text),
    Column("notes", Text),
)


session_stats_daily = Table(
    "session_stats_daily",
    metadata,
    Column("day_utc", Text, primary_key=True),
    Column("http_requests_total", Integer, nullable=False, server_default="0"),
    Column("articles_processed_total", Integer, nullable=False, server_default="0"),
    Column("tokens_in_total", Integer, nullable=False, server_default="0"),
    Column("tokens_out_total", Integer, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)


session_stats_state = Table(
    "session_stats_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("last_session_start", Float),
    Column("last_http_counter", Integer, nullable=False, server_default="0"),
    CheckConstraint("id = 1", name="chk_session_stats_state_singleton"),
)


backfill_progress = Table(
    "backfill_progress",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("collect_running", Integer, server_default="0"),
    Column("collect_until", Text),
    Column("collect_scanning", Integer, server_default="0"),
    Column("collect_scan_page", Integer, server_default="0"),
    Column("collect_last_page", Integer, server_default="0"),
    Column("collect_processed", Integer, server_default="0"),
    Column("collect_last_ts", Text),
    Column("collect_goal_pages", Integer),
    Column("collect_goal_total", Integer),
    Column("sum_running", Integer, server_default="0"),
    Column("sum_until", Text),
    Column("sum_processed", Integer, server_default="0"),
    Column("sum_last_article_id", Integer),
    Column("sum_model", Text),
    Column("sum_goal_total", Integer),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("id = 1", name="chk_backfill_progress_singleton"),
)


def create_all_schema(conn: Connection | Engine) -> None:
    """Создаёт все необходимые таблицы/индексы для приложения.

    Принимает SQLAlchemy Connection или Engine.
    После создания таблиц гарантирует наличие singleton-строк (id=1) в таблицах состояния.
    """
    engine: Engine = conn if isinstance(conn, Engine) else conn.engine  # type: ignore
    metadata.create_all(engine)

    # Ensure singleton rows (PostgreSQL-only)
    with (engine.connect() if isinstance(conn, Engine) else conn) as c:
        c.execute(sql_text(
            "INSERT INTO backfill_progress (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        ))
        c.execute(sql_text(
            "INSERT INTO session_stats_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        ))
        c.commit()
