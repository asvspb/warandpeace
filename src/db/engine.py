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


def _build_sqlite_url(sqlite_path: str) -> str:
    # Use pysqlite driver; absolute path inside container is like /app/database/articles.db
    # For SQLite, three slashes mean absolute path
    return f"sqlite+pysqlite:///{sqlite_path.lstrip('/')}" if sqlite_path.startswith('/') else f"sqlite+pysqlite:///{sqlite_path}"


def get_database_url() -> str:
    """Return DATABASE_URL if set, otherwise build SQLite URL from config.DB_SQLITE_PATH.

    Examples:
    - postgresql+psycopg://wp:***@postgres:5432/warandpeace
    - sqlite+pysqlite:////app/database/articles.db
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    return _build_sqlite_url(getattr(config, "DB_SQLITE_PATH", "/app/database/articles.db"))


def create_engine_from_env(echo: bool = False, pool_pre_ping: bool = True) -> Engine:
    url = get_database_url()
    if url.startswith("sqlite+"):
        return create_engine(
            url,
            echo=echo,
            pool_pre_ping=False,  # not needed for SQLite
            connect_args={"check_same_thread": False},
            future=True,
        )
    # Postgres or others
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
