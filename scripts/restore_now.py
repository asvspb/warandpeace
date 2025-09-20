#!/usr/bin/env python3
"""
Утилита-обёртка для восстановления из бэкапа.

Что делает:
- Загружает переменные из `.env` в корне репозитория (если файл есть)
- Вызывает `tools/restore.py` с понятными значениями по умолчанию
(db, engine=postgres, backend=local, --latest)

Важные переменные окружения для восстановления (PostgreSQL + local):
- DATABASE_URL или POSTGRES_HOST/PORT/USER/PASSWORD/DB
- LOCAL_BACKUP_DIR — корень каталога с бэкапами
- BACKUP_TMP_DIR — временный каталог для распаковки (например, `/tmp/restore`)
- AGE_SECRET_KEY — приватный ключ age (нужен, если архив `.dump.age`)

Безопасная процедура:
1) Сухой прогон (ничего не заменяется):
   ./scripts/restore_now.py --dry-run
2) Остановить сервисы, зависящие от БД (если в Docker Compose):
   docker compose stop telegram-bot web
3) Выполнить восстановление:
   ./scripts/restore_now.py
4) Запустить сервисы обратно:
   docker compose up -d telegram-bot web

Шифрование (age):
- Если архив `latest` указывает на `.dump.age`, нужен `AGE_SECRET_KEY`.
  Пример экспорта из локального файла ключей:
    export AGE_SECRET_KEY="$(grep -m1 '^AGE-SECRET-KEY' ~/.config/age/keys.txt)"
- Проверить, какой файл «latest»:
    readlink -f backups/db/postgres/latest.*

Частые ошибки и решения:
- "Backup is encrypted, but AGE_SECRET_KEY is not set" — экспортируйте корректный приватный ключ
- Ошибка расшифровки (`exit status 1`) — ключ не соответствует публичному ключу, которым зашифрован бэкап
- Ошибки расшифровки или отсутствия файла дампа — проверьте путь и ключ `AGE_SECRET_KEY`, либо укажите конкретный `--backup-file`.
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
    while True:
        if (current / ".git").exists() or (current / "tools" / "restore.py").exists():
            return current
        if current.parent == current:
            return start
        current = current.parent


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]

    parser = argparse.ArgumentParser(description="Run project restore with sane defaults")
    parser.add_argument("--component", default="db", choices=["db", "env", "media"], help="Component to restore")
    parser.add_argument("--engine", default="postgres", choices=["postgres"], help="Database engine")
    parser.add_argument("--backend", default="local", choices=["s3", "yadisk", "local"], help="Storage backend")
    parser.add_argument("--at", default="latest", help="Timestamp (YYYYMMDDTHHMMSSZ) or 'latest'")
    parser.add_argument("--dry-run", action="store_true", help="Do not replace live files")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to use (default: current)")
    parser.add_argument("--verbose", action="store_true", help="Print the effective command before run")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Resolve repo root (directory that contains .git or tools/*)
    repo_root = find_repo_root(Path(__file__).resolve().parent)
    if (repo_root / ".env").exists() and load_dotenv:
        load_dotenv(repo_root / ".env")

    tools_restore = (repo_root / "tools" / "restore.py").resolve()
    if not tools_restore.exists():
        print(f"FATAL: tools/restore.py not found at {tools_restore}", file=sys.stderr)
        return 2

    cmd = [
        args.__dict__["python"],
        str(tools_restore),
        "--component", args.component,
        "--engine", args.engine,
        "--backend", args.backend,
        "--at", args.at,
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    # Log effective env (without secrets)
    local_backup_dir = os.getenv("LOCAL_BACKUP_DIR", "")
    backup_tmp_dir = os.getenv("BACKUP_TMP_DIR", "")
    age_key_set = bool(os.getenv("AGE_SECRET_KEY"))

    logging.info(
        "Restore start: component=%s engine=%s backend=%s at=%s dry_run=%s",
        args.component, args.engine, args.backend, args.at, args.dry_run
    )
    logging.info("Env: LOCAL_BACKUP_DIR=%s", local_backup_dir)
    logging.info("Env: BACKUP_TMP_DIR=%s", backup_tmp_dir)
    logging.info("Env: AGE_SECRET_KEY set=%s", age_key_set)

    if args.verbose:
        print("Running:", " ".join(cmd))

    started = time.perf_counter()
    # Inherit current env; AGE_SECRET_KEY can already be present via .env or user export
    proc = subprocess.run(cmd)
    duration = time.perf_counter() - started
    if proc.returncode == 0:
        logging.info("Restore finished successfully in %.2fs", duration)
    else:
        logging.error("Restore failed with exit code %s after %.2fs", proc.returncode, duration)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
