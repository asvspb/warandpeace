import os
import sys
from pathlib import Path
import pytest

# Глобальная проверка окружения перед запуском любых тестов
# Можно отключить через переменную окружения: SKIP_ENV_CHECK=1


def _inside_container() -> bool:
    # Простейшая эвристика для Docker
    return os.path.exists("/.dockerenv")


def _maybe_skip_db_checks_for_host_env():
    """Если тесты запускаются вне контейнера и DATABASE_URL ссылается на 'postgres',
    пропускаем сетевые проверки, чтобы не падать от недоступного хоста Docker сети.
    """
    try:
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from src.db.engine import get_database_url  # type: ignore
        url = (get_database_url() or "").strip().lower()
    except Exception:
        return
    if not _inside_container() and "@postgres:" in url:
        os.environ.setdefault("SKIP_ENV_DB_CHECKS", "1")


@pytest.fixture(scope="session", autouse=True)
def validate_env_before_tests():
    if os.getenv("SKIP_ENV_CHECK", "0").strip() in ("1", "true", "yes"):
        pytest.skip("Env check disabled via SKIP_ENV_CHECK")

    _maybe_skip_db_checks_for_host_env()

    try:
        import scripts.validate_env as ve  # type: ignore
    except Exception as e:
        pytest.skip(f"Env check module not available: {e}")

    rc = 0
    try:
        rc = ve.main()  # печатает JSON-отчёт и возвращает код 0/1
    except ModuleNotFoundError as e:
        pytest.skip(f"Skipping env check (dependency missing): {e}")
    assert rc == 0, "Проверка окружения (scripts/validate_env.py) провалилась — см. вывод для деталей"