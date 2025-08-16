#!/usr/bin/env python3
# tools/backup.py
"""
Usage: backup.py --component db|env|media --engine sqlite|postgres --backend s3|yadisk|local [--encrypt auto|on|off]
"""
import argparse
import logging
import os
import re
import subprocess
import tarfile
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
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

def is_executable_available(executable_name: str) -> bool:
    """Check if an executable exists in PATH."""
    return shutil.which(executable_name) is not None

def calculate_sha256(file_path):
    """Calculate and return the SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def check_free_space(check_path: Path, min_gb_str: str):
    """
    Checks if there is enough free space on the device hosting check_path.
    Exits if the check fails.
    """
    if not min_gb_str or not min_gb_str.isdigit() or int(min_gb_str) <= 0:
        logging.debug("Skipping free space check (LOCAL_MIN_FREE_GB is not a positive integer).")
        return

    min_gb = int(min_gb_str)
    logging.info(f"Checking for at least {min_gb}GB free space at {check_path}")
    
    try:
        usage = shutil.disk_usage(check_path)
        free_gb = usage.free / (1024**3)
        
        if free_gb < min_gb:
            logging.error(f"Free space check failed: {free_gb:.2f}GB remaining, but {min_gb}GB required.")
            exit(1)
        
        logging.info(f"Free space check passed: {free_gb:.2f}GB available.")
    except FileNotFoundError:
        logging.error(f"Path not found for free space check: {check_path}. Cannot perform backup.")
        exit(1)

def rotate_backups(directory: Path, retention_days: int):
    """
    Deletes old backups in a directory based on a retention period.
    """
    if retention_days <= 0:
        logging.info("Rotation is disabled (retention_days <= 0).")
        return

    logging.info(f"Starting rotation in {directory}, keeping backups for {retention_days} days.")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    # Regex to extract timestamp from filenames like:
    # warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz
    # warandpeace-env-YYYYMMDDTHHMMSSZ.tar.gz.age
    pattern = re.compile(r".*-(\d{8}T\d{6}Z)\..*")
    
    files_deleted = 0
    for backup_file in directory.iterdir():
        if backup_file.is_file() and not backup_file.name.startswith('latest.'):
            match = pattern.match(backup_file.name)
            if match:
                timestamp_str = match.group(1)
                try:
                    backup_date = datetime.strptime(timestamp_str, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                    if backup_date < cutoff_date:
                        logging.info(f"Deleting old backup: {backup_file.name}")
                        backup_file.unlink()
                        files_deleted += 1
                        
                        # Also delete the checksum file
                        checksum_file = directory / f"{backup_file.name}.sha256"
                        if checksum_file.exists():
                            logging.info(f"Deleting checksum file: {checksum_file.name}")
                            checksum_file.unlink()
                except ValueError:
                    logging.warning(f"Could not parse timestamp from filename: {backup_file.name}")

    logging.info(f"Rotation complete. Deleted {files_deleted} old backup(s).")


def backup_env_local():
    """
    Performs a local, always-encrypted backup of the .env file.
    """
    # 1. Get configuration
    app_dir = Path(get_env_var("APP_DIR", default="/app"))
    tmp_dir = Path(get_env_var("BACKUP_TMP_DIR", default="/tmp/backup"))
    local_backup_dir = Path(get_env_var("LOCAL_BACKUP_DIR"))
    age_public_keys_str = get_env_var("AGE_PUBLIC_KEYS", required=True) # Encryption is mandatory

    # Ensure destination root exists and check free space before proceeding
    local_backup_dir.mkdir(parents=True, exist_ok=True)
    min_free_gb_str = get_env_var("LOCAL_MIN_FREE_GB", required=False, default="0")
    check_free_space(local_backup_dir, min_free_gb_str)

    env_path = app_dir / ".env"
    env_example_path = app_dir / ".env.example"

    if not env_path.exists():
        logging.warning(f".env file not found at {env_path}, skipping backup.")
        return

    # 2. Prepare directories
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = local_backup_dir / "env"
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 3. Generate timestamp and filenames
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        base_filename = f"warandpeace-env-{timestamp}"
        archive_path = tmp_dir / f"{base_filename}.tar.gz"
        encrypted_archive_path = tmp_dir / f"{base_filename}.tar.gz.age"
        checksum_path = tmp_dir / f"{base_filename}.tar.gz.age.sha256"

        # 4. Create a tarball with .env and .env.example
        logging.info(f"Creating tarball: {archive_path}")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(env_path, arcname=".env")
            if env_example_path.exists():
                tar.add(env_example_path, arcname=".env.example")

        # 5. Encrypt the tarball (mandatory)
        logging.info(f"Encrypting archive to {encrypted_archive_path}")
        recipients = [key.strip() for key in age_public_keys_str.split(',')]
        age_cmd = ['age', '--encrypt']
        for r in recipients:
            age_cmd.extend(['-r', r])
        age_cmd.extend(['-o', str(encrypted_archive_path), str(archive_path)])
        run_command(age_cmd)

        # 6. Calculate checksum of the encrypted file
        logging.info(f"Calculating SHA256 checksum for {encrypted_archive_path}")
        checksum = calculate_sha256(encrypted_archive_path)
        with open(checksum_path, 'w') as f:
            f.write(f"{checksum}  {encrypted_archive_path.name}\n")
        logging.info(f"Checksum: {checksum}")

        # 7. Move artifacts to the final destination
        final_path = dest_dir / encrypted_archive_path.name
        final_checksum_path = dest_dir / checksum_path.name
        
        logging.info(f"Moving {encrypted_archive_path.name} to {final_path}")
        shutil.move(encrypted_archive_path, final_path)
        
        logging.info(f"Moving {checksum_path.name} to {final_checksum_path}")
        shutil.move(checksum_path, final_checksum_path)

        # 8. Update 'latest' symlink
        latest_symlink = dest_dir / "latest.tar.gz.age"
        logging.info(f"Updating 'latest' symlink to point to {final_path.name}")
        if latest_symlink.exists() or latest_symlink.is_symlink():
            latest_symlink.unlink()
        latest_symlink.symlink_to(final_path.name)

        # 9. Rotation
        retention_days_str = get_env_var("BACKUP_RETENTION_DAYS", required=False, default="0")
        try:
            retention_days = int(retention_days_str)
            if retention_days > 0:
                rotate_backups(dest_dir, retention_days)
        except ValueError:
            logging.warning(f"Invalid BACKUP_RETENTION_DAYS value: '{retention_days_str}'. Skipping rotation.")

        logging.info("Env backup completed successfully.")

    finally:
        # 10. Cleanup
        logging.info(f"Cleaning up temporary directory: {tmp_dir}")
        shutil.rmtree(tmp_dir)


def backup_sqlite_local(encrypt_policy):
    """
    Performs a local backup of the SQLite database.
    """
    # 1. Get configuration from environment variables
    db_path = Path(get_env_var("DB_SQLITE_PATH"))
    tmp_dir = Path(get_env_var("BACKUP_TMP_DIR", default="/tmp/backup"))
    local_backup_dir = Path(get_env_var("LOCAL_BACKUP_DIR"))
    age_public_keys_str = get_env_var("AGE_PUBLIC_KEYS", required=False)

    # Ensure destination root exists and check free space before proceeding
    local_backup_dir.mkdir(parents=True, exist_ok=True)
    min_free_gb_str = get_env_var("LOCAL_MIN_FREE_GB", required=False, default="0")
    check_free_space(local_backup_dir, min_free_gb_str)

    if not db_path.exists():
        logging.error(f"Database file not found at: {db_path}")
        return

    # 2. Prepare directories
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = local_backup_dir / "db" / "sqlite"
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 3. Generate timestamp and filenames
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        base_filename = f"warandpeace-db-sqlite-{timestamp}"
        
        tmp_db_snapshot_path = tmp_dir / "sqlite.db"
        archive_path = tmp_dir / f"{base_filename}.tar.gz"

        # 4. Create a consistent database snapshot
        logging.info(f"Creating SQLite snapshot from {db_path} to {tmp_db_snapshot_path}")
        if is_executable_available('sqlite3'):
            # Pass the dot-command as a single argument without shell quotes
            run_command(['sqlite3', str(db_path), f".backup {tmp_db_snapshot_path}"])
        else:
            # Fallback to Python API
            logging.info("sqlite3 CLI not found. Using Python sqlite3 backup API.")
            with sqlite3.connect(str(db_path)) as src_conn, sqlite3.connect(str(tmp_db_snapshot_path)) as dst_conn:
                src_conn.backup(dst_conn)

        # 5. Create a tarball
        logging.info(f"Creating tarball: {archive_path}")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_db_snapshot_path, arcname="sqlite.db")

        # 6. Encryption
        final_artifact_path = archive_path
        should_encrypt = (encrypt_policy == 'on') or (encrypt_policy == 'auto' and age_public_keys_str)
        
        if should_encrypt:
            if not age_public_keys_str:
                raise ValueError("Encryption is enabled, but AGE_PUBLIC_KEYS is not set.")
            
            encrypted_archive_path = tmp_dir / f"{base_filename}.tar.gz.age"
            logging.info(f"Encrypting archive to {encrypted_archive_path}")
            
            recipients = [key.strip() for key in age_public_keys_str.split(',')]
            age_cmd = ['age', '--encrypt']
            for r in recipients:
                age_cmd.extend(['-r', r])
            age_cmd.extend(['-o', str(encrypted_archive_path), str(archive_path)])
            
            run_command(age_cmd)
            final_artifact_path = encrypted_archive_path

        # 7. Calculate checksum of the final artifact
        logging.info(f"Calculating SHA256 checksum for {final_artifact_path}")
        checksum = calculate_sha256(final_artifact_path)
        checksum_path = tmp_dir / f"{final_artifact_path.name}.sha256"
        with open(checksum_path, 'w') as f:
            f.write(f"{checksum}  {final_artifact_path.name}\n")
        logging.info(f"Checksum: {checksum}")
        
        # 8. Move artifact and checksum to the final destination
        final_path = dest_dir / final_artifact_path.name
        final_checksum_path = dest_dir / checksum_path.name
        
        logging.info(f"Moving {final_artifact_path.name} to {final_path}")
        shutil.move(final_artifact_path, final_path)
        
        logging.info(f"Moving {checksum_path.name} to {final_checksum_path}")
        shutil.move(checksum_path, final_checksum_path)

        # 9. Update 'latest' symlink
        latest_symlink_name = f"latest.tar.gz{'.age' if should_encrypt else ''}"
        latest_symlink = dest_dir / latest_symlink_name
        logging.info(f"Updating '{latest_symlink_name}' symlink to point to {final_path.name}")
        if latest_symlink.exists() or latest_symlink.is_symlink():
            latest_symlink.unlink()
        latest_symlink.symlink_to(final_path.name)

        # 10. Rotation
        retention_days_str = get_env_var("BACKUP_RETENTION_DAYS", required=False, default="0")
        try:
            retention_days = int(retention_days_str)
            if retention_days > 0:
                rotate_backups(dest_dir, retention_days)
        except ValueError:
            logging.warning(f"Invalid BACKUP_RETENTION_DAYS value: '{retention_days_str}'. Skipping rotation.")

        logging.info("Backup completed successfully.")

    finally:
        # 11. Cleanup
        logging.info(f"Cleaning up temporary directory: {tmp_dir}")
        shutil.rmtree(tmp_dir)

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Backup tool for WarAndPeace project.")
    parser.add_argument("--component", required=True, choices=["db", "env", "media"], help="Component to backup.")
    parser.add_argument("--engine", default="sqlite", choices=["sqlite", "postgres"], help="Database engine.")
    parser.add_argument("--backend", required=True, choices=["s3", "yadisk", "local"], help="Storage backend.")
    parser.add_argument("--encrypt", default="auto", choices=["auto", "on", "off"], help="Encryption policy (ignored for 'env' component, which is always encrypted).")
    
    args = parser.parse_args()

    logging.info(f"Starting backup for component '{args.component}' using engine '{args.engine}' to backend '{args.backend}'.")

    if args.backend == 'local':
        if args.component == 'db' and args.engine == 'sqlite':
            backup_sqlite_local(args.encrypt)
        elif args.component == 'env':
            backup_env_local()
        else:
            logging.error(f"Component '{args.component}' with engine '{args.engine}' is not supported for the local backend.")
            exit(1)
    else:
        logging.error(f"Backend '{args.backend}' is not yet implemented.")
        exit(1)

if __name__ == "__main__":
    main()