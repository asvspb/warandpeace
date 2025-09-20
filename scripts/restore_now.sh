#!/usr/bin/env bash
#
# restore_now.sh — удобный запуск восстановления Postgres из бэкапа
#
# Что делает этот скрипт:
# - Загружает переменные окружения из файла `.env` (если он есть в корне репозитория)
# - Подставляет параметры по умолчанию для восстановления последнего дампа
# - Вызывает Python-утилиту проекта `tools/restore.py` (pg_restore под капотом)
#
# Ключевые переменные окружения:
# - DATABASE_URL ИЛИ POSTGRES_HOST/PORT/USER/PASSWORD/DB
# - LOCAL_BACKUP_DIR  — корень каталога с бэкапами
# - BACKUP_TMP_DIR    — временная директория (по умолчанию `/tmp/restore`)
# - AGE_SECRET_KEY    — приватный ключ age (нужен, если архив `.dump.age`)
#
# Типовой безопасный порядок действий:
# 1) Сухой прогон (ничего не меняем в БД):
#      ./scripts/restore_now.sh --dry-run
# 2) Остановить зависящие сервисы (если используете Docker Compose):
#      docker compose stop telegram-bot web
# 3) Выполнить восстановление (опционально с дропом БД):
#      ./scripts/restore_now.sh [--drop-existing]
# 4) Запустить сервисы обратно:
#      docker compose up -d telegram-bot web

set -Eeuo pipefail
trap 'echo "[restore_now.sh] Ошибка на строке $LINENO" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Подхватить .env (если есть)
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Значения по умолчанию
USE_LATEST=true
BACKUP_FILE=""
DB_NAME=""
DROP_EXISTING=false
DO_LIST=false
DRY_RUN=false
BACKUP_TMP_DIR="${BACKUP_TMP_DIR:-/tmp/restore}"
VERBOSE="${VERBOSE:-false}"

usage() {
  cat <<'USAGE'
Использование: scripts/restore_now.sh [опции]

Опции:
  --latest                      использовать последний бэкап (по умолчанию)
  --backup-file <path>          путь к конкретному файлу .dump или .dump.age
  --db-name <name>              имя целевой БД (по умолчанию POSTGRES_DB)
  --drop-existing               дропнуть БД перед восстановлением (ОПАСНО)
  --list                        вывести содержимое дампа и выйти
  --dry-run                     проверить бэкап и вывести план без изменений
  --tmp <dir>                   BACKUP_TMP_DIR (по умолчанию: /tmp/restore)
  --verbose                     печатать исполняемую команду
  -h | --help                   показать эту справку

Примеры:
  scripts/restore_now.sh --list
  scripts/restore_now.sh --latest --dry-run
  scripts/restore_now.sh --backup-file backups/db/postgres/warandpeace-db-postgres-20250101T000000Z.dump.age --drop-existing
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest) USE_LATEST=true; shift;;
    --backup-file) BACKUP_FILE="$2"; USE_LATEST=false; shift 2;;
    --db-name) DB_NAME="$2"; shift 2;;
    --drop-existing) DROP_EXISTING=true; shift;;
    --list) DO_LIST=true; shift;;
    --dry-run) DRY_RUN=true; shift;;
    --tmp) BACKUP_TMP_DIR="$2"; shift 2;;
    --verbose) VERBOSE=true; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Неизвестный аргумент: $1" >&2; usage; exit 2;;
  esac
done

# Проверка наличия основного скрипта восстановления
if [[ ! -f tools/restore.py ]]; then
  echo "FATAL: tools/restore.py не найден. Текущая директория: $(pwd)" >&2
  exit 2
fi

# Если ключ не задан и последний бэкап зашифрован, попробуем подхватить ключ из стандартного файла
if [[ -z "${AGE_SECRET_KEY:-}" ]]; then
  local_dir="${LOCAL_BACKUP_DIR:-backups}/db/postgres"
  latest_target="$(readlink -f "$local_dir"/latest.* 2>/dev/null || true)"
  if [[ "$latest_target" =~ \.age$ ]] && [[ -f "${HOME}/.config/age/keys.txt" ]]; then
    export AGE_SECRET_KEY="$(grep -m1 '^AGE-SECRET-KEY' "${HOME}/.config/age/keys.txt" || true)"
  fi
fi

# Соберём аргументы для запуска restore.py
args=()
[[ "$USE_LATEST" == true ]] && args+=( --latest )
[[ -n "$BACKUP_FILE" ]] && args+=( --backup-file "$BACKUP_FILE" )
[[ -n "$DB_NAME" ]] && args+=( --db-name "$DB_NAME" )
[[ "$DROP_EXISTING" == true ]] && args+=( --drop-existing )
[[ "$DO_LIST" == true ]] && args+=( --list )
[[ "$DRY_RUN" == true ]] && args+=( --dry-run )

if [[ "$VERBOSE" == true ]]; then
  echo "Запуск: BACKUP_TMP_DIR=\"$BACKUP_TMP_DIR\" AGE_SECRET_KEY=\"${AGE_SECRET_KEY:+***hidden***}\" python3 tools/restore.py ${args[*]}"
fi

BACKUP_TMP_DIR="$BACKUP_TMP_DIR" AGE_SECRET_KEY="${AGE_SECRET_KEY:-}" \
  python3 tools/restore.py "${args[@]}"
