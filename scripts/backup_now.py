#!/usr/bin/env python3
"""
Утилита-обёртка для запуска резервного копирования.

Что делает:
- Загружает переменные из `.env` в корне репозитория (если файл есть)
- Вызывает `tools/backup.py` с понятными значениями по умолчанию
  (component=db, engine=postgres, backend=local, encrypt=auto)

Важные переменные окружения для бэкапа PostgreSQL (local):
- DATABASE_URL — либо набор POSTGRES_HOST/PORT/USER/PASSWORD/DB
- LOCAL_BACKUP_DIR — корень каталога бэкапов (например, `/var/backups/warandpeace`)
- BACKUP_TMP_DIR — временный каталог для сборки бэкапа (например, `/tmp/backup`)
- BACKUP_RETENTION_DAYS — ротация старых бэкапов (0 — отключить)
- LOCAL_MIN_FREE_GB — минимально свободное место на диске (0 — отключить проверку)

Шифрование (age):
- AGE_PUBLIC_KEYS — список публичных ключей (через запятую). Если задан, `--encrypt auto`
  создаст зашифрованный архив `.age` и checksum.
- Для бэкапа компонента `env` шифрование всегда включено, `AGE_PUBLIC_KEYS` обязателен.

Примеры:
- Бэкап БД PostgreSQL локально (custom формат pg_dump):
    ./scripts/backup_now.py

- Явно указать параметры:
    ./scripts/backup_now.py --component db --engine postgres --backend local --encrypt auto

- Бэкап `.env` (всегда шифруется, нужен AGE_PUBLIC_KEYS):
    ./scripts/backup_now.py --component env --backend local

Где смотреть результат:
- Файлы в `LOCAL_BACKUP_DIR/db/postgres` и `LOCAL_BACKUP_DIR/env`
- Симлинк `latest.dump[.age]` указывает на последний успешный бэкап

Советы по устранению проблем:
- "Path not found for free space check" — проверьте, что `LOCAL_BACKUP_DIR` существует и доступен
- "Encryption is enabled, but AGE_PUBLIC_KEYS is not set" — добавьте ключи или запустите с `--encrypt off`
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path
import logging
import time

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # optional


def find_repo_root(start: Path) -> Path:
    # Ensure we start from a directory path
    current = start if start.is_dir() else start.parent
    # Stop at filesystem root
    while True:
        if (current / ".git").exists() or (current / "tools" / "backup.py").exists():
            return current
        if current.parent == current:
            return start
        current = current.parent


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]

    parser = argparse.ArgumentParser(description="Run project backup with sane defaults")
    parser.add_argument("--component", default="db", choices=["db", "env", "media"], help="Component to backup")
    parser.add_argument("--engine", default="postgres", choices=["postgres"], help="Database engine (for component=db)")
    parser.add_argument("--backend", default="local", choices=["s3", "yadisk", "local"], help="Storage backend")
    parser.add_argument("--encrypt", default="auto", choices=["auto", "on", "off"], help="Encrypt policy (ignored for env)")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to use (default: current)")
    parser.add_argument("--verbose", action="store_true", help="Print the effective command before run")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Resolve repo root and .env
    # Resolve repo root (directory that contains .git or tools/*)
    repo_root = find_repo_root(Path(__file__).resolve().parent)
    if (repo_root / ".env").exists() and load_dotenv:
        load_dotenv(repo_root / ".env")

    tools_backup = (repo_root / "tools" / "backup.py").resolve()
    if not tools_backup.exists():
        print(f"FATAL: tools/backup.py not found at {tools_backup}", file=sys.stderr)
        return 2

    cmd = [
        args.__dict__["python"],
        str(tools_backup),
        "--component", args.component,
        "--engine", args.engine,
        "--backend", args.backend,
    ]
    # env always encrypts inside tools/backup.py; keep flag only for others
    if args.component != "env":
        cmd += ["--encrypt", args.encrypt]

    # Log effective env of interest (without secrets)
    # DB_SQLITE_PATH more not used in PG-only setup
    db_sqlite_path = os.getenv("DB_SQLITE_PATH", "")
    local_backup_dir = os.getenv("LOCAL_BACKUP_DIR", "")
    backup_tmp_dir = os.getenv("BACKUP_TMP_DIR", "")
    age_public_keys_set = bool(os.getenv("AGE_PUBLIC_KEYS"))

    logging.info(
        "Backup start: component=%s engine=%s backend=%s encrypt=%s",
        args.component, args.engine, args.backend, (args.encrypt if args.component != "env" else "forced")
    )
    logging.info("Env: DB_SQLITE_PATH=%s", db_sqlite_path)
    logging.info("Env: LOCAL_BACKUP_DIR=%s", local_backup_dir)
    logging.info("Env: BACKUP_TMP_DIR=%s", backup_tmp_dir)
    logging.info("Env: AGE_PUBLIC_KEYS set=%s", age_public_keys_set)

    if args.verbose:
        print("Running:", " ".join(cmd))

    started = time.perf_counter()
    proc = subprocess.run(cmd)
    duration = time.perf_counter() - started
    if proc.returncode == 0:
        logging.info("Backup finished successfully in %.2fs", duration)
    else:
        logging.error("Backup failed with exit code %s after %.2fs", proc.returncode, duration)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
