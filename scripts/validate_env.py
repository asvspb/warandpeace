#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List

# We will not print secret values. This script only prints statuses/messages.


def _load_dotenv_if_present() -> Dict[str, str]:
    """Load .env into process env (non-destructive) and also return parsed kv.

    - If .env exists, we load it with override=False so existing env wins.
    - Return a dict of parsed key/value for checks that don't require os.environ.
    """
    try:
        from dotenv import dotenv_values, load_dotenv  # type: ignore
    except Exception:
        dotenv_values = None  # type: ignore
        def load_dotenv(*args: Any, **kwargs: Any) -> bool:  # type: ignore
            return False

    env_path = Path.cwd() / ".env"
    parsed: Dict[str, str] = {}
    if env_path.exists():
        try:
            load_dotenv(dotenv_path=str(env_path), override=False)
            if dotenv_values:
                parsed = dict(dotenv_values(dotenv_path=str(env_path)) or {})
        except Exception:
            parsed = {}
    return parsed


def _truthy(v: str | None) -> bool:
    return bool((v or "").strip())


def _get_effective(parsed: Dict[str, str], key: str) -> str:
    """Return value from process env or parsed .env (without exposing it)."""
    v = os.environ.get(key)
    if _truthy(v):
        return v  # do not print
    v = parsed.get(key, "")
    return v


def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    # Ensure we can import project modules like src.db.engine
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    parsed_env = _load_dotenv_if_present()

    results: Dict[str, Any] = {"checks": [], "recommended": [], "summary": {}}

    def add_check(name: str, ok: bool, message: str = "") -> None:
        results["checks"].append({"name": name, "ok": bool(ok), "message": message})

    # 1) .env presence
    env_present = (Path.cwd() / ".env").exists()
    add_check("env_file_present", env_present, ".env найден" if env_present else ".env не найден — создайте из .env.example")

    # 2) Mandatory vars: either DATABASE_URL or POSTGRES_* triplet
    database_url = _get_effective(parsed_env, "DATABASE_URL")
    pg_user = _get_effective(parsed_env, "POSTGRES_USER")
    pg_pass = _get_effective(parsed_env, "POSTGRES_PASSWORD")
    pg_db = _get_effective(parsed_env, "POSTGRES_DB")

    has_url = _truthy(database_url)
    has_triplet = _truthy(pg_user) and _truthy(pg_pass) and _truthy(pg_db)
    add_check("db_vars_present", has_url or has_triplet, "DATABASE_URL или POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB должны быть заданы")

    # 3) POSTGRES_PASSWORD must be non-empty and reasonably long
    pass_len_ok = len((pg_pass or "").strip()) >= 8
    add_check("postgres_password_length", pass_len_ok, "POSTGRES_PASSWORD должен быть не короче 8 символов")

    # 4) Resolve effective DB URL via app logic and ensure it's Postgres
    try:
        from src.db.engine import get_database_url, create_engine_from_env  # type: ignore
        url = get_database_url()
        is_pg = url.strip().lower().startswith("postgresql+")
        add_check("db_url_resolves_postgres", is_pg, "DATABASE_URL должен начинаться с postgresql+psycopg://")
    except Exception as e:
        add_check("db_url_resolves_postgres", False, f"Ошибка построения DATABASE_URL: {type(e).__name__}: {e}")
        url = ""

    # 5) Try connecting and SELECT 1 (can be skipped)
    skip_db_checks = _to_bool(os.getenv("SKIP_ENV_DB_CHECKS"), default=False)
    db_connect_ok = False
    try:
        if url and not skip_db_checks:
            engine = create_engine_from_env()
            with engine.connect() as c:
                val = c.execute(__import__("sqlalchemy").text("SELECT 1")).scalar_one()
                db_connect_ok = (int(val) == 1)
        add_check(
            "db_connect",
            True if skip_db_checks else db_connect_ok,
            "Пропущена проверка подключения (SKIP_ENV_DB_CHECKS=1)" if skip_db_checks else (
                "Успешное подключение к БД и SELECT 1" if db_connect_ok else "Не удалось подключиться к БД"
            ),
        )
    except Exception as e:
        add_check("db_connect", False, f"Ошибка подключения к БД: {type(e).__name__}: {e}")

    # 6) Ensure schema can be created/exists (idempotent)
    schema_ok = False
    try:
        if url and (db_connect_ok and not skip_db_checks):
            from src.db.schema import create_all_schema  # type: ignore
            create_all_schema(engine)
            schema_ok = True
        add_check(
            "db_schema_ensure",
            True if skip_db_checks else schema_ok,
            "Пропущена проверка схемы (SKIP_ENV_DB_CHECKS=1)" if skip_db_checks else (
                "Схема проверена/создана" if schema_ok else "Схема не проверена"
            ),
        )
    except Exception as e:
        add_check("db_schema_ensure", False, f"Ошибка при создании схемы: {type(e).__name__}: {e}")

    # 7) Recommended: WEB_SESSION_SECRET present and not default
    wss = _get_effective(parsed_env, "WEB_SESSION_SECRET")
    wss_ok = _truthy(wss) and wss not in {"change-me-please", "dev-session-secret-change-me"}
    results["recommended"].append({
        "name": "web_session_secret",
        "ok": bool(wss_ok),
        "message": "WEB_SESSION_SECRET установлен и не дефолтный" if wss_ok else "Рекомендуется установить WEB_SESSION_SECRET и не оставлять дефолт"
    })

    # 8) Recommended: If WEB_API_ENABLED true -> WEB_API_KEY present
    api_enabled = _to_bool(_get_effective(parsed_env, "WEB_API_ENABLED"), default=False)
    if api_enabled:
        api_key_ok = _truthy(_get_effective(parsed_env, "WEB_API_KEY"))
        results["recommended"].append({
            "name": "web_api_key",
            "ok": bool(api_key_ok),
            "message": "WEB_API_KEY задан" if api_key_ok else "WEB_API_ENABLED=true, требуется WEB_API_KEY"
        })

    # 9) Recommended: If WEB_AUTH_MODE=webauthn -> WEB_RP_ID present
    auth_mode = (_get_effective(parsed_env, "WEB_AUTH_MODE") or "").strip().lower()
    if auth_mode == "webauthn":
        rp_ok = _truthy(_get_effective(parsed_env, "WEB_RP_ID"))
        results["recommended"].append({
            "name": "webauthn_rp_id",
            "ok": bool(rp_ok),
            "message": "WEB_RP_ID задан" if rp_ok else "WEB_AUTH_MODE=webauthn, требуется WEB_RP_ID"
        })

    # 10) Optional: Telegram token sanity
    tg = _get_effective(parsed_env, "TELEGRAM_BOT_TOKEN")
    if _truthy(tg):
        tok_ok = len(tg) >= 40 and ":" in tg  # простая эвристика формата
        results["recommended"].append({
            "name": "telegram_bot_token_format",
            "ok": bool(tok_ok),
            "message": "Формат TELEGRAM_BOT_TOKEN выглядит корректно" if tok_ok else "Проверьте формат TELEGRAM_BOT_TOKEN"
        })

    # Summary
    mandatory_ok = all(c.get("ok") for c in results["checks"])
    results["summary"] = {
        "mandatory_passed": mandatory_ok,
        "failed": [c for c in results["checks"] if not c.get("ok")],
    }

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if mandatory_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())