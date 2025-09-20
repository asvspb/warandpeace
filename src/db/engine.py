from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

# Support both package and module execution contexts
try:
    from .. import config  # type: ignore
except Exception:
    import config  # type: ignore

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Connection


def get_database_url() -> str:
    """Return a Postgres DATABASE_URL, or construct it from POSTGRES_* env vars.

    Strict Postgres mode: SQLite URLs are not supported.

    Examples:
    - postgresql+psycopg://wp:***@postgres:5432/warandpeace
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    # Try to construct from POSTGRES_* variables
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB")
    if user and password and db:
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
    raise RuntimeError(
        "DATABASE_URL is not set. Provide DATABASE_URL or set POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB (optional: POSTGRES_HOST, POSTGRES_PORT)."
    )


def create_engine_from_env(echo: bool = False, pool_pre_ping: bool = True) -> Engine:
    url = get_database_url()
    # Strict Postgres: no SQLite branch
    return create_engine(url, echo=echo, pool_pre_ping=pool_pre_ping, future=True)


@contextmanager
def get_connection(echo: Optional[bool] = None) -> Iterator[Connection]:
    """Yield SQLAlchemy Connection with an active transaction.

    Usage:
        with get_connection() as conn:
            conn.execute(text("SELECT 1"))
    """
    engine = create_engine_from_env(echo=bool(echo))
    conn: Optional[Connection] = None
    trans = None
    try:
        conn = engine.connect()
        trans = conn.begin()
        yield conn
        if trans.is_active:
            trans.commit()
    except Exception:
        if trans and trans.is_active:
            trans.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
