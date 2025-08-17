#!/usr/bin/env bash
#
# restore_now.sh — удобный запуск восстановления SQLite из бэкапа
#
# Что делает этот скрипт:
# - Загружает переменные окружения из файла `.env` (если он есть в корне репозитория)
# - Аккуратно подставляет параметры по умолчанию: component=db, engine=sqlite, backend=local, at=latest
# - Вызывает Python-утилиту проекта `tools/restore.py`, которая:
#     * проверяет checksum (если есть файл .sha256)
#     * расшифровывает .age (если нужно; требуется AGE_SECRET_KEY)
#     * распаковывает архив и делает integrity_check для SQLite
#     * при реальном восстановлении заменяет файл БД
#
# ВАЖНО про пути:
# - Если запускаете восстановление НА ХОСТЕ, убедитесь, что в `.env` путь `DB_SQLITE_PATH`
#   указывает на реальный путь хоста (например, `./database/articles.db` с абсолютным путём),
#   а не контейнерный `/app/database/articles.db`.
# - Если запускаете ВНУТРИ КОНТЕЙНЕРА, наоборот, используйте контейнерные пути из `.env.example`.
#
# Ключевые переменные окружения для restore (SQLite + local):
# - DB_SQLITE_PATH    — путь к «живой» базе, которая будет заменена
# - LOCAL_BACKUP_DIR  — корень каталога с бэкапами (например, `./backups` на хосте, `/var/backups/warandpeace` в контейнере)
# - BACKUP_TMP_DIR    — временная директория (по умолчанию `/tmp/restore`)
# - AGE_SECRET_KEY    — приватный ключ age (нужен, если архив `.tar.gz.age`)
#
# Типовой безопасный порядок действий:
# 1) Сухой прогон (ничего не заменяется):
#      ./scripts/restore_now.sh --dry-run
# 2) Остановить зависящие сервисы (если используете Docker Compose):
#      docker compose stop telegram-bot web
# 3) Выполнить восстановление:
#      ./scripts/restore_now.sh
# 4) Запустить сервисы обратно:
#      docker compose up -d telegram-bot web
#
# Подсказки по age:
# - Если «latest» указывает на `.tar.gz.age`, нужен `AGE_SECRET_KEY`.
# - Экспортировать ключ из стандартного файла можно так:
#      export AGE_SECRET_KEY="$(grep -m1 '^AGE-SECRET-KEY' ~/.config/age/keys.txt)"
# - Этот скрипт попробует сам подхватить ключ из `~/.config/age/keys.txt`, если:
#     * `AGE_SECRET_KEY` не установлен
#     * и «latest» указывает на зашифрованный архив
#
# Быстрые решения частых ошибок:
# - "Backup is encrypted, but AGE_SECRET_KEY is not set" — экспортируйте приватный ключ
# - Ошибка расшифровки (exit status 1) — ключ не соответствует публичному ключу, которым зашифрован бэкап
# - "sqlite.db not found in the archive" — бэкап повреждён или не тот компонент; попробуйте другой `--at`

set -Eeuo pipefail

# Красивый вывод ошибки с номером строки
trap 'echo "[restore_now.sh] Ошибка на строке $LINENO" >&2' ERR

# Перейти в корень репозитория (папка со скриптом -> родитель)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Подхватить .env (если есть)
if [[ -f .env ]]; then
  # export всего, что в .env, не засоряя оболочку после
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Значения по умолчанию (можно переопределить как переменными окружения, так и флагами)
COMPONENT_DEFAULT="db"
ENGINE_DEFAULT="sqlite"
BACKEND_DEFAULT="local"
AT_DEFAULT="latest"
DRY_RUN_DEFAULT="false"
BACKUP_TMP_DIR_DEFAULT="/tmp/restore"

COMPONENT="${COMPONENT:-$COMPONENT_DEFAULT}"
ENGINE="${ENGINE:-$ENGINE_DEFAULT}"
BACKEND="${BACKEND:-$BACKEND_DEFAULT}"
AT="${AT:-$AT_DEFAULT}"
DRY_RUN="${DRY_RUN:-$DRY_RUN_DEFAULT}"
BACKUP_TMP_DIR="${BACKUP_TMP_DIR:-$BACKUP_TMP_DIR_DEFAULT}"
VERBOSE="${VERBOSE:-false}"

usage() {
  cat <<'USAGE'
Использование: scripts/restore_now.sh [опции]

Опции:
  --component db|env|media     (по умолчанию: db)
  --engine sqlite|postgres     (по умолчанию: sqlite)
  --backend local|s3|yadisk    (по умолчанию: local)
  --at latest|YYYYMMDDTHHMMSSZ (по умолчанию: latest)
  --dry-run                    (по умолчанию: выкл)
  --tmp <dir>                  BACKUP_TMP_DIR (по умолчанию: /tmp/restore)
  --verbose                    печатать исполняемую команду
  -h | --help                  показать эту справку

Примеры:
  DRY_RUN=true scripts/restore_now.sh
  scripts/restore_now.sh --at 20250816T142134Z --verbose
USAGE
}

# Простейший парсер аргументов
while [[ $# -gt 0 ]]; do
  case "$1" in
    --component) COMPONENT="$2"; shift 2;;
    --engine) ENGINE="$2"; shift 2;;
    --backend) BACKEND="$2"; shift 2;;
    --at) AT="$2"; shift 2;;
    --dry-run) DRY_RUN="true"; shift 1;;
    --tmp) BACKUP_TMP_DIR="$2"; shift 2;;
    --verbose) VERBOSE="true"; shift 1;;
    -h|--help) usage; exit 0;;
    *) echo "Неизвестный аргумент: $1" >&2; usage; exit 2;;
  esac
done

# Проверка наличия основного скрипта восстановления
if [[ ! -f tools/restore.py ]]; then
  echo "FATAL: tools/restore.py не найден. Текущая директория: $(pwd)" >&2
  exit 2
fi

# Если ключ не задан и последний бэкап зашифрован, попробуем подхватить ключ из файла
if [[ -z "${AGE_SECRET_KEY:-}" ]]; then
  # Вычислим директорию с бэкапами для проверки latest
  # Порядок приоритета: $LOCAL_BACKUP_DIR/db/sqlite -> ./backups/db/sqlite
  backup_base="${LOCAL_BACKUP_DIR:-}"
  candidate_dir=""
  if [[ -n "$backup_base" && -d "$backup_base/db/sqlite" ]]; then
    candidate_dir="$backup_base/db/sqlite"
  elif [[ -d "backups/db/sqlite" ]]; then
    candidate_dir="backups/db/sqlite"
  fi

  if [[ -n "$candidate_dir" ]]; then
    latest_target="$(readlink -f "$candidate_dir"/latest.* 2>/dev/null || true)"
    if [[ "$latest_target" =~ \.age$ ]] && [[ -f "${HOME}/.config/age/keys.txt" ]]; then
      export AGE_SECRET_KEY="$(grep -m1 '^AGE-SECRET-KEY' "${HOME}/.config/age/keys.txt" || true)"
      if [[ -z "${AGE_SECRET_KEY}" ]]; then
        echo "Внимание: не удалось прочитать AGE_SECRET_KEY из ~/.config/age/keys.txt" >&2
      fi
    fi
  fi
fi

# Соберём аргументы для запуска restore.py
args=(
  --component "$COMPONENT"
  --engine "$ENGINE"
  --backend "$BACKEND"
  --at "$AT"
)
[[ "$DRY_RUN" == "true" ]] && args+=( --dry-run )

# Показать команду при необходимости
if [[ "$VERBOSE" == "true" ]]; then
  echo "Запуск: BACKUP_TMP_DIR=\"$BACKUP_TMP_DIR\" AGE_SECRET_KEY=\"${AGE_SECRET_KEY:+***hidden***}\" python3 tools/restore.py ${args[*]}"
fi

# Запустить восстановление, передав временную директорию и (если задан) ключ
BACKUP_TMP_DIR="$BACKUP_TMP_DIR" AGE_SECRET_KEY="${AGE_SECRET_KEY:-}" \
  python3 tools/restore.py "${args[@]}"
