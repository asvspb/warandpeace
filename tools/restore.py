#!/usr/bin/env python3
# tools/restore.py
"""
Usage: restore.py --component db|env|media --engine sqlite|postgres --backend s3|yadisk|local --at ISO8601|latest [--dry-run]
"""
import argparse
import logging
import os
import subprocess
import tarfile
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import shutil

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_env_var(var_name, required=True, default=None):
    """Get an environment variable, exiting if it's required and not found."""
    value = os.getenv(var_name)
    if required and not value:
        logging.error(f"FATAL: Required environment variable '{var_name}' is not set.")
        exit(1)
    return value if value else default

def run_command(command, **kwargs):
    """Run a shell command and handle errors."""
    logging.info(f"Running command: {' '.join(command)}")
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)
        if result.stdout:
            logging.info(f"STDOUT: {result.stdout.strip()}")
        if result.stderr:
            logging.warning(f"STDERR: {result.stderr.strip()}")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with exit code {e.returncode}: {' '.join(command)}")
        logging.error(f"STDOUT: {e.stdout.strip()}")
        logging.error(f"STDERR: {e.stderr.strip()}")
        raise

def calculate_sha256(file_path):
    """Calculate and return the SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def restore_sqlite_local(at_timestamp, dry_run):
    """
    Restores the SQLite database from a local backup.
    """
    # 1. Get configuration
    db_path = Path(get_env_var("DB_SQLITE_PATH"))
    tmp_dir = Path(get_env_var("BACKUP_TMP_DIR", default="/tmp/restore"))
    local_backup_dir = Path(get_env_var("LOCAL_BACKUP_DIR"))
    age_secret_key = get_env_var("AGE_SECRET_KEY", required=False)

    backup_src_dir = local_backup_dir / "db" / "sqlite"
    if not backup_src_dir.exists():
        logging.error(f"Backup source directory not found: {backup_src_dir}")
        exit(1)

    # 2. Find the backup file
    if at_timestamp == 'latest':
        # Find the 'latest' symlink, could be .age or .tar.gz
        latest_links = list(backup_src_dir.glob('latest.*'))
        if not latest_links:
            logging.error(f"No 'latest' symlink found in {backup_src_dir}")
            exit(1)
        backup_file_path = backup_src_dir / os.readlink(latest_links[0])
    else:
        # Find by timestamp (simplified glob)
        found_files = list(backup_src_dir.glob(f"*{at_timestamp}*"))
        if not found_files:
            logging.error(f"No backup found for timestamp '{at_timestamp}' in {backup_src_dir}")
            exit(1)
        backup_file_path = found_files[0]

    if not backup_file_path.exists():
        logging.error(f"Backup file not found: {backup_file_path}")
        exit(1)

    logging.info(f"Found backup file: {backup_file_path}")

    # 3. Prepare temporary directory
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    try:
        # 4. Copy to temp and verify checksum
        tmp_backup_path = tmp_dir / backup_file_path.name
        shutil.copy(backup_file_path, tmp_backup_path)

        # The checksum file is expected to be named after the backup artifact,
        # e.g., 'backup.tar.gz.age.sha256' for 'backup.tar.gz.age'.
        checksum_file_path = backup_src_dir / f"{backup_file_path.name}.sha256"

        if not checksum_file_path.exists():
            logging.warning(f"Checksum file not found at {checksum_file_path}. Skipping verification.")
        else:
            logging.info(f"Verifying checksum of {tmp_backup_path.name} using {checksum_file_path.name}")
            local_checksum = calculate_sha256(tmp_backup_path)
            with open(checksum_file_path, 'r') as f:
                stored_checksum = f.read().split()[0]

            if local_checksum != stored_checksum:
                logging.error(f"Checksum mismatch! The backup file may be corrupt. Expected {stored_checksum}, got {local_checksum}.")
                exit(1)
            logging.info("Checksum verified successfully.")

        # 5. Decrypt if necessary
        is_encrypted = '.age' in backup_file_path.suffixes
        archive_path = tmp_backup_path
        if is_encrypted:
            if not age_secret_key:
                logging.error("Backup is encrypted, but AGE_SECRET_KEY is not set.")
                exit(1)
            
            decrypted_path = tmp_dir / tmp_backup_path.stem # Removes .age
            logging.info(f"Decrypting {tmp_backup_path.name} to {decrypted_path.name}")
            
            # Pass key via stdin for security
            age_cmd = ['age', '--decrypt', '-i', '-', '-o', str(decrypted_path), str(tmp_backup_path)]
            subprocess.run(age_cmd, input=age_secret_key, text=True, check=True, capture_output=True)
            archive_path = decrypted_path

        # 6. Unpack the tarball
        logging.info(f"Unpacking archive: {archive_path.name}")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=tmp_dir)
        
        restored_db_path = tmp_dir / "sqlite.db"
        if not restored_db_path.exists():
            logging.error("sqlite.db not found in the archive.")
            exit(1)

        # 7. Perform integrity check on the restored DB
        logging.info("Performing integrity check on the restored database file.")
        try:
            # Prefer CLI if available for parity with prod images
            if shutil.which('sqlite3'):
                run_command(['sqlite3', str(restored_db_path), 'PRAGMA integrity_check;'])
            else:
                with sqlite3.connect(str(restored_db_path)) as conn:
                    result = conn.execute('PRAGMA integrity_check;').fetchone()
                    if not result or result[0] != 'ok':
                        logging.error(f"Integrity check failed: {result}")
                        exit(1)
        except Exception as e:
            logging.error(f"Integrity check error: {e}")
            exit(1)

        # 8. Replace the live database file
        if dry_run:
            logging.info(f"[DRY RUN] Would replace {db_path} with the restored database.")
        else:
            logging.info(f"Replacing live database at {db_path}")
            # It's safer to move the old one away than to delete it
            db_path.rename(db_path.with_suffix(f".db.bak-{datetime.now(timezone.utc).isoformat()}"))
            shutil.move(restored_db_path, db_path)
        
        logging.info("Restore completed successfully.")

    finally:
        # 9. Cleanup
        logging.info(f"Cleaning up temporary directory: {tmp_dir}")
        shutil.rmtree(tmp_dir)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Restore tool for WarAndPeace project.")
    parser.add_argument("--component", required=True, choices=["db", "env", "media"], help="Component to restore.")
    parser.add_argument("--engine", default="sqlite", choices=["sqlite", "postgres"], help="Database engine.")
    parser.add_argument("--backend", required=True, choices=["s3", "yadisk", "local"], help="Storage backend.")
    parser.add_argument("--at", default="latest", help="Timestamp (ISO8601) or 'latest' to restore from.")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without actual restoration.")

    args = parser.parse_args()

    logging.info(f"Starting restore for component '{args.component}' from backend '{args.backend}' at '{args.at}'. Dry run: {args.dry_run}")

    if args.backend == 'local':
        if args.component == 'db' and args.engine == 'sqlite':
            restore_sqlite_local(args.at, args.dry_run)
        else:
            logging.error(f"Restore for component '{args.component}' with engine '{args.engine}' is not supported for the local backend.")
            exit(1)
    else:
        logging.error(f"Restore from backend '{args.backend}' is not yet implemented.")
        exit(1)

if __name__ == "__main__":
    main()