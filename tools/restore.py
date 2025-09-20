#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def run(cmd: list[str], env: Optional[dict] = None) -> None:
    logging.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)


def _get_pg_conn_params() -> dict:
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER") or "wp"
    password = os.getenv("POSTGRES_PASSWORD") or ""
    db = os.getenv("POSTGRES_DB") or "warandpeace"
    return {"host": host, "port": port, "user": user, "password": password, "db": db}


def _resolve_backup_file(latest: bool, path: Optional[str]) -> Path:
    if path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Backup file not found: {p}")
        return p
    if latest:
        root = Path(os.getenv("LOCAL_BACKUP_DIR", "/var/backups/warandpeace")) / "db" / "postgres"
        latest_link = root / "latest.dump.age"
        if latest_link.exists():
            return latest_link.resolve()
        latest_plain = root / "latest.dump"
        if latest_plain.exists():
            return latest_plain.resolve()
        candidates = sorted(root.glob("warandpeace-db-postgres-*.dump*"))
        if not candidates:
            raise FileNotFoundError(f"No backups found in {root}")
        return candidates[-1]
    raise ValueError("Either --latest or --backup-file must be provided")


def _maybe_decrypt(src: Path, tmp_dir: Path) -> Path:
    if src.suffix == ".age":
        secret = os.getenv("AGE_SECRET_KEY")
        if not secret:
            raise RuntimeError("AGE_SECRET_KEY is required to decrypt .age backups")
        keyfile = tmp_dir / "age-key.txt"
        keyfile.write_text(secret)
        out_path = tmp_dir / src.with_suffix("").name
        run(["age", "-d", "-i", str(keyfile), "-o", str(out_path), str(src)])
        return out_path
    return src


def ensure_database_exists(params: dict, dbname: str) -> None:
    env = os.environ.copy()
    if params.get("password"):
        env["PGPASSWORD"] = params["password"]
    sql = f"CREATE DATABASE \"{dbname}\" WITH ENCODING 'UTF8';"
    psql = ["psql", "-h", params["host"], "-p", params["port"], "-U", params["user"], "-d", "postgres", "-tc", sql]
    subprocess.run(psql, env=env, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def drop_database_if_exists(params: dict, dbname: str) -> None:
    env = os.environ.copy()
    if params.get("password"):
        env["PGPASSWORD"] = params["password"]
    terminate = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname='{dbname}' AND pid <> pg_backend_pid();"
    )
    run(["psql", "-h", params["host"], "-p", params["port"], "-U", params["user"], "-d", "postgres", "-c", terminate], env)
    run(["psql", "-h", params["host"], "-p", params["port"], "-U", params["user"], "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS \"{dbname}\";"], env)


def restore_dump_to_db(dump_path: Path, params: dict, dbname: str) -> None:
    env = os.environ.copy()
    if params.get("password"):
        env["PGPASSWORD"] = params["password"]
    ensure_database_exists(params, dbname)
    run([
        "pg_restore",
        "-h", params["host"],
        "-p", params["port"],
        "-U", params["user"],
        "-d", dbname,
        "-j", str(os.cpu_count() or 2),
        str(dump_path),
    ], env)


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Restore Postgres database from local backup")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--latest", action="store_true", help="Use latest backup under LOCAL_BACKUP_DIR/db/postgres")
    g.add_argument("--backup-file", help="Path to specific backup file (.dump or .dump.age)")
    ap.add_argument("--db-name", help="Target database name (default: POSTGRES_DB)")
    ap.add_argument("--drop-existing", action="store_true", help="Drop target database before restore (DANGEROUS)")
    ap.add_argument("--list", action="store_true", help="List dump contents and exit (no changes)")
    ap.add_argument("--dry-run", action="store_true", help="Verify backup and print actions without modifying database")
    args = ap.parse_args()

    params = _get_pg_conn_params()
    dbname = args.db_name or params["db"]

    tmp_dir = Path("/tmp/restore")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        src = _resolve_backup_file(args.latest, args.backup_file)
        logging.info("Selected backup: %s", src)
        dump_path = _maybe_decrypt(src, tmp_dir)

        # Safe modes first
        if args.list:
            run(["pg_restore", "--list", str(dump_path)])
            return 0
        if args.dry_run:
            logging.info("[DRY RUN] Would restore to database '%s'", dbname)
            run(["pg_restore", "--list", str(dump_path)])
            return 0

        if args.drop_existing:
            logging.warning("Dropping existing database '%s' before restore", dbname)
            drop_database_if_exists(params, dbname)
        restore_dump_to_db(dump_path, params, dbname)
        logging.info("Restore completed successfully to database '%s'", dbname)
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
