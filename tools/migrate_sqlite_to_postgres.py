#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import math
import json
import argparse
from typing import Iterable, Sequence, Optional, Dict, Any, List, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Tables and keys we migrate
TABLES_ORDER: List[str] = [
    # order matters due to FKs in future versions; now there are none, but keep logical order
    "articles",
    "pending_publications",
    "dlq",
    "digests",
    "api_usage_daily",
    # api_usage_events is optional (can be big)
    "api_usage_events",
    "sessions",
    "session_stats_daily",
    "session_stats_state",
    "webauthn_credential",
    "backfill_progress",
]

UPSERT_RULES_PG: Dict[str, str] = {
    "articles": (
        "INSERT INTO articles (url, canonical_link, title, published_at, content, content_hash, summary_text, created_at, updated_at, backfill_status)\n"
        "VALUES (:url, :canonical_link, :title, :published_at, :content, :content_hash, :summary_text, :created_at, :updated_at, :backfill_status)\n"
        "ON CONFLICT (canonical_link) DO UPDATE SET\n"
        "  url = EXCLUDED.url, title = EXCLUDED.title, published_at = EXCLUDED.published_at,\n"
        "  content = EXCLUDED.content, content_hash = EXCLUDED.content_hash,\n"
        "  summary_text = COALESCE(EXCLUDED.summary_text, articles.summary_text),\n"
        "  updated_at = NOW(), backfill_status = COALESCE(EXCLUDED.backfill_status, articles.backfill_status)"
    ),
    "pending_publications": (
        "INSERT INTO pending_publications (url, title, published_at, summary_text, attempts, last_error, created_at, updated_at)\n"
        "VALUES (:url, :title, :published_at, :summary_text, COALESCE(:attempts, 0), :last_error, :created_at, :updated_at)\n"
        "ON CONFLICT (url) DO UPDATE SET\n"
        "  title = EXCLUDED.title, published_at = EXCLUDED.published_at, summary_text = EXCLUDED.summary_text,\n"
        "  attempts = COALESCE(EXCLUDED.attempts, pending_publications.attempts), last_error = EXCLUDED.last_error,\n"
        "  updated_at = NOW()"
    ),
    "dlq": (
        "INSERT INTO dlq (entity_type, entity_ref, error_code, error_payload, attempts, first_seen_at, last_seen_at)\n"
        "VALUES (:entity_type, :entity_ref, :error_code, :error_payload, COALESCE(:attempts, 1), :first_seen_at, :last_seen_at)\n"
        "ON CONFLICT (id) DO NOTHING"  # id is serial; treat as pure insert
    ),
    "digests": (
        "INSERT INTO digests (period, content, created_at) VALUES (:period, :content, :created_at)\n"
        "ON CONFLICT (id) DO NOTHING"
    ),
    "api_usage_daily": (
        "INSERT INTO api_usage_daily (day_utc, provider, model, api_key_hash, req_count, success_count, tokens_in_total, tokens_out_total, cost_usd_total, latency_ms_sum)\n"
        "VALUES (:day_utc, :provider, COALESCE(:model, ''), COALESCE(:api_key_hash, ''), COALESCE(:req_count,0), COALESCE(:success_count,0), COALESCE(:tokens_in_total,0), COALESCE(:tokens_out_total,0), COALESCE(:cost_usd_total,0.0), COALESCE(:latency_ms_sum,0))\n"
        "ON CONFLICT (day_utc, provider, model, api_key_hash) DO UPDATE SET\n"
        "  req_count = api_usage_daily.req_count + EXCLUDED.req_count,\n"
        "  success_count = api_usage_daily.success_count + EXCLUDED.success_count,\n"
        "  tokens_in_total = api_usage_daily.tokens_in_total + EXCLUDED.tokens_in_total,\n"
        "  tokens_out_total = api_usage_daily.tokens_out_total + EXCLUDED.tokens_out_total,\n"
        "  cost_usd_total = api_usage_daily.cost_usd_total + EXCLUDED.cost_usd_total,\n"
        "  latency_ms_sum = api_usage_daily.latency_ms_sum + EXCLUDED.latency_ms_sum"
    ),
    "api_usage_events": (
        "INSERT INTO api_usage_events (ts_utc, provider, model, api_key_hash, endpoint, req_count, success, http_status, latency_ms, tokens_in, tokens_out, cost_usd, error_code, extra_json)\n"
        "VALUES (:ts_utc, :provider, :model, :api_key_hash, :endpoint, COALESCE(:req_count,1), :success, :http_status, :latency_ms, COALESCE(:tokens_in,0), COALESCE(:tokens_out,0), COALESCE(:cost_usd,0.0), :error_code, :extra_json)\n"
        "ON CONFLICT (id) DO NOTHING"
    ),
    "sessions": (
        "INSERT INTO sessions (session_id, started_at_utc, ended_at_utc, git_sha, container_id, notes)\n"
        "VALUES (:session_id, :started_at_utc, :ended_at_utc, :git_sha, :container_id, :notes)\n"
        "ON CONFLICT (session_id) DO UPDATE SET\n"
        "  ended_at_utc = EXCLUDED.ended_at_utc, git_sha = EXCLUDED.git_sha, container_id = EXCLUDED.container_id, notes = EXCLUDED.notes"
    ),
    "session_stats_daily": (
        "INSERT INTO session_stats_daily (day_utc, http_requests_total, articles_processed_total, tokens_in_total, tokens_out_total, updated_at)\n"
        "VALUES (:day_utc, COALESCE(:http_requests_total,0), COALESCE(:articles_processed_total,0), COALESCE(:tokens_in_total,0), COALESCE(:tokens_out_total,0), :updated_at)\n"
        "ON CONFLICT (day_utc) DO UPDATE SET\n"
        "  http_requests_total = EXCLUDED.http_requests_total, articles_processed_total = EXCLUDED.articles_processed_total,\n"
        "  tokens_in_total = EXCLUDED.tokens_in_total, tokens_out_total = EXCLUDED.tokens_out_total, updated_at = NOW()"
    ),
    "session_stats_state": (
        "INSERT INTO session_stats_state (id, last_session_start, last_http_counter)\n"
        "VALUES (1, :last_session_start, COALESCE(:last_http_counter,0))\n"
        "ON CONFLICT (id) DO UPDATE SET last_session_start = EXCLUDED.last_session_start, last_http_counter = EXCLUDED.last_http_counter"
    ),
    "webauthn_credential": (
        "INSERT INTO webauthn_credential (user_id, credential_id, public_key, sign_count, transports, aaguid, created_at, last_used_at)\n"
        "VALUES (:user_id, :credential_id, :public_key, COALESCE(:sign_count,0), :transports, :aaguid, :created_at, :last_used_at)\n"
        "ON CONFLICT (credential_id) DO NOTHING"
    ),
    "backfill_progress": (
        "INSERT INTO backfill_progress (id, collect_running, collect_until, collect_scanning, collect_scan_page, collect_last_page, collect_processed, collect_last_ts, collect_goal_pages, collect_goal_total, sum_running, sum_until, sum_processed, sum_last_article_id, sum_model, sum_goal_total, updated_at)\n"
        "VALUES (1, :collect_running, :collect_until, :collect_scanning, :collect_scan_page, :collect_last_page, :collect_processed, :collect_last_ts, :collect_goal_pages, :collect_goal_total, :sum_running, :sum_until, :sum_processed, :sum_last_article_id, :sum_model, :sum_goal_total, :updated_at)\n"
        "ON CONFLICT (id) DO UPDATE SET\n"
        "  collect_running = EXCLUDED.collect_running, collect_until = EXCLUDED.collect_until, collect_scanning = EXCLUDED.collect_scanning,\n"
        "  collect_scan_page = EXCLUDED.collect_scan_page, collect_last_page = EXCLUDED.collect_last_page, collect_processed = EXCLUDED.collect_processed,\n"
        "  collect_last_ts = EXCLUDED.collect_last_ts, collect_goal_pages = EXCLUDED.collect_goal_pages, collect_goal_total = EXCLUDED.collect_goal_total,\n"
        "  sum_running = EXCLUDED.sum_running, sum_until = EXCLUDED.sum_until, sum_processed = EXCLUDED.sum_processed,\n"
        "  sum_last_article_id = EXCLUDED.sum_last_article_id, sum_model = EXCLUDED.sum_model, sum_goal_total = EXCLUDED.sum_goal_total, updated_at = NOW()"
    ),
}

INSERT_OR_IGNORE_SQLITE: Dict[str, str] = {
    # Fallback for dry-run to SQLite destination (for local validation without PG)
    t: UPSERT_RULES_PG[t]
    .replace("ON CONFLICT (", " /* sqlite fallback */ ON CONFLICT(")
    .replace("DO UPDATE SET", "DO NOTHING")
    for t in UPSERT_RULES_PG
}


def chunked(seq: Sequence[dict], size: int) -> Iterable[Sequence[dict]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def fetch_source_batch(src: Engine, table: str, offset: int, limit: int) -> List[Dict[str, Any]]:
    with src.connect() as c:
        rows = c.execute(text(f"SELECT * FROM {table} ORDER BY ROWID LIMIT :limit OFFSET :offset"), {"limit": limit, "offset": offset}).mappings().all()
        return [dict(r) for r in rows]


def count_rows(engine: Engine, table: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def upsert_batch(dst: Engine, table: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    dialect = dst.dialect.name
    sql = None
    if dialect == "postgresql":
        sql = UPSERT_RULES_PG.get(table)
    elif dialect == "sqlite":
        sql = INSERT_OR_IGNORE_SQLITE.get(table)
    else:
        raise RuntimeError(f"Unsupported destination dialect: {dialect}")
    if not sql:
        raise RuntimeError(f"No upsert rule for table {table}")
    with dst.begin() as c:
        c.execute(text(sql), rows)
    return len(rows)


def migrate_table(src: Engine, dst: Engine, table: str, batch_size: int, limit: Optional[int]) -> Tuple[int, int]:
    total_src = count_rows(src, table)
    to_copy = total_src if limit is None else min(total_src, limit)
    copied = 0
    offset = 0
    while copied < to_copy:
        left = to_copy - copied
        take = min(batch_size, left)
        batch = fetch_source_batch(src, table, offset=offset, limit=take)
        if not batch:
            break
        upsert_batch(dst, table, batch)
        copied += len(batch)
        offset += len(batch)
        print(f"  {table}: {copied}/{to_copy}")
    return to_copy, copied


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL using SQLAlchemy")
    ap.add_argument("--sqlite-path", default=os.getenv("DB_SQLITE_PATH", "./database/articles.db"), help="Path to source SQLite file")
    ap.add_argument("--pg-url", default=os.getenv("DATABASE_URL", ""), help="Destination DATABASE_URL (Postgres). For dry-run can be SQLite URL")
    ap.add_argument("--tables", nargs="*", default=TABLES_ORDER, help="Tables to migrate in order")
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--limit", type=int, default=0, help="Limit rows per table (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="If set, do not write to destination (still connects)")
    args = ap.parse_args()

    src_url = f"sqlite+pysqlite:///{os.path.abspath(args.sqlite_path)}"
    dst_url = args.pg_url.strip()
    if not dst_url:
        print("ERROR: --pg-url or DATABASE_URL must be provided", file=sys.stderr)
        return 2

    print(f"Source: {src_url}")
    print(f"Destination: {dst_url}")

    src = create_engine(src_url, future=True)
    dst = create_engine(dst_url, future=True)

    # Quick connectivity check
    try:
        with src.connect() as c:
            c.execute(text("SELECT 1")).scalar_one()
        with dst.connect() as c:
            c.execute(text("SELECT 1")).scalar_one()
    except Exception as e:
        print(f"Connectivity error: {e}", file=sys.stderr)
        return 3

    summary: Dict[str, Dict[str, int]] = {}
    for t in args.tables:
        print(f"Migrating table: {t}")
        total_src = count_rows(src, t)
        lim = None if args.limit <= 0 else args.limit
        if args.dry_run:
            print(f"  DRY-RUN: would copy up to {total_src if lim is None else lim} rows from {t}")
            summary[t] = {"source": total_src, "copied": 0}
            continue
        to_copy, copied = migrate_table(src, dst, t, batch_size=args.batch_size, limit=lim)
        summary[t] = {"source": to_copy, "copied": copied}

    print("Summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
