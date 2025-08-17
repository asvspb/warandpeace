## Подробная инструкция: как сохранять и восстанавливать базу (SQLite)

Ниже описан рабочий процесс для локальной разработки и продакшн-контейнеров из этого репозитория. База — SQLite, лежит в `./database/articles.db`. Скрипты: `tools/backup.py` и `tools/restore.py`.

### Что сохраняется и куда
- **База данных**: файл `./database/articles.db`
- **Формат бэкапа**: tar.gz (снимок `sqlite.db`) с опциональным шифрованием `age` — `warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz[.age]`
- **Контрольная сумма**: `*.sha256` рядом с артефактом
- **Симлинк на последний бэкап**: `latest.tar.gz[.age]`
- **Каталог бэкапов (на хосте)**: `./backups` → внутри контейнера монтируется в `/var/backups/warandpeace`
  - Директория БД: `/var/backups/warandpeace/db/sqlite`

### Важные переменные окружения
Задаются в `.env` (или через `env_file`/`-e`):
- `DB_SQLITE_PATH=/app/database/articles.db`
- `LOCAL_BACKUP_DIR=/var/backups/warandpeace`
- `BACKUP_TMP_DIR=/tmp/backup` (или `/tmp/restore` для восстановления)
- `BACKUP_RETENTION_DAYS=7` (ротация старых бэкапов; 0 — выкл)
- `LOCAL_MIN_FREE_GB=1` (минимум свободного места; 0 — выкл)
- Шифрование:
  - `AGE_PUBLIC_KEYS=age1...` (получатели; чтобы включить шифрование бэкапов)
  - `AGE_SECRET_KEY=AGE-SECRET-KEY-...` (нужен только для восстановления зашифрованных бэкапов)

Совет: ключи и токены держите вне Git (Docker secrets/ENV).

### Подготовка (папки и права)
- Убедитесь, что существуют директории на хосте:
  - `./database` — будет содержать рабочий `articles.db`
  - `./backups` — сюда складываются бэкапы
- В `docker-compose.yml` должны быть volume:
  - `./database:/app/database`
  - `./backups:/var/backups/warandpeace`

## Ручное резервное копирование (Docker)
Создаёт снимок БД, архивирует, при наличии `AGE_PUBLIC_KEYS` зашифрует и положит контрольную сумму.

```bash
docker compose run --rm \
  -e DB_SQLITE_PATH=/app/database/articles.db \
  -e LOCAL_BACKUP_DIR=/var/backups/warandpeace \
  -e BACKUP_TMP_DIR=/tmp/backup \
  -e LOCAL_MIN_FREE_GB=1 \
  -e BACKUP_RETENTION_DAYS=7 \
  -e AGE_PUBLIC_KEYS="${AGE_PUBLIC_KEYS}" \
  -v "$(pwd)/database:/app/database" \
  -v "$(pwd)/backups:/var/backups/warandpeace" \
  telegram-bot \
  python3 tools/backup.py --component db --engine sqlite --backend local --encrypt auto
```

Где взять `AGE_PUBLIC_KEYS`:
- Если хотите шифровать — сгенерируйте `age` ключи и укажите публичные ключи (через запятую).
- Если не укажете — будет незашифрованный tar.gz (при `--encrypt auto`).

Проверка результата:
- Файл в `./backups/db/sqlite/warandpeace-db-sqlite-*.tar.gz[.age]`
- Симлинк `./backups/db/sqlite/latest.tar.gz[.age]`
- Контрольная сумма `*.sha256`

Проверка контрольной суммы:
```bash
cd backups/db/sqlite
sha256sum -c warandpeace-db-sqlite-*.sha256
```

## Автоматические бэкапы (cron контейнер)
В `docker-compose.yml` есть сервис `cron`, который по расписанию выполняет:
- `python3 /app/tools/backup.py --component db --backend local`

Что сделать:
- Убедиться, что каталог `./backups` смонтирован, а переменные окружения доступны сервису `cron` (см. `env_file`/`environment`).
- Расписание задаётся `BACKUP_CRON` (например, `0 3 * * *`).

Просмотр логов cron:
```bash
docker compose logs -f cron
```

## Восстановление из бэкапа (Docker)
1) Остановите сервисы, которые используют БД:
```bash
docker compose stop telegram-bot cron
```

2) Запустите одноразовый контейнер восстановления:
- Вариант “последний бэкап”:
```bash
docker compose run --rm \
  -e DB_SQLITE_PATH=/app/database/articles.db \
  -e LOCAL_BACKUP_DIR=/var/backups/warandpeace \
  -e BACKUP_TMP_DIR=/tmp/restore \
  -e AGE_SECRET_KEY="${AGE_SECRET_KEY}" \
  -v "$(pwd)/database:/app/database" \
  -v "$(pwd)/backups:/var/backups/warandpeace" \
  telegram-bot \
  python3 tools/restore.py --component db --engine sqlite --backend local --at latest
```

- Вариант “по времени” (подставьте метку из имени файла, например `20250816T142134Z`):
```bash
python3 tools/restore.py --component db --engine sqlite --backend local --at 20250816T142134Z
```

3) Запустите сервисы обратно:
```bash
docker compose up -d telegram-bot cron
```

4) Проверка:
```bash
docker compose ps
docker compose logs --tail=200 telegram-bot
```

Примечания:
- Для зашифрованных бэкапов обязательно нужен `AGE_SECRET_KEY`. Без него восстановление прервётся.
- Скрипт делает проверку целостности SQLite (`PRAGMA integrity_check;`) и заменяет рабочий файл.

## Восстановление в “dry-run”
Посмотреть, что будет сделано, но не менять живую БД:
```bash
python3 tools/restore.py --component db --engine sqlite --backend local --at latest --dry-run
```

## Локальный запуск без Docker (опционально)
1) Установите зависимости:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
2) Экспортируйте переменные окружения, соответствующие вашему пути БД и каталогу бэкапов:
```bash
export DB_SQLITE_PATH="$(pwd)/database/articles.db"
export LOCAL_BACKUP_DIR="$(pwd)/backups"
export BACKUP_TMP_DIR="/tmp/backup"
export AGE_PUBLIC_KEYS="age1..."
export AGE_SECRET_KEY="AGE-SECRET-KEY-..."
```
3) Команды:
```bash
python tools/backup.py --component db --engine sqlite --backend local --encrypt auto
python tools/restore.py --component db --engine sqlite --backend local --at latest
```

## Частые ошибки и решения
- **InvalidToken в боте / перезапуски контейнера**: проверьте `TELEGRAM_BOT_TOKEN` в `.env` и что `telegram-bot` читает именно `.env` (см. `env_file`).
- **Нет прав/файлов**: проверьте, что `./database` и `./backups` существуют и доступны пользователю Docker/хоста.
- **Не найден checksum**: не критично; это предупреждение. Можно сгенерировать заново или игнорировать.
- **Нет `age` при локальном запуске**: установите `age` в систему или запускайте через Docker, где он уже предустановлен.
- **Недостаточно места**: измените `LOCAL_MIN_FREE_GB` или освободите место.

## Полезные команды
- Список бэкапов:
```bash
ls -l ./backups/db/sqlite
```
- Проверка здоровья веб-сервиса:
```bash
curl -fsS http://localhost:8080/healthz
```
- Пересборка образов и рестарт:
```bash
docker compose build
docker compose up -d
```
- Просмотр последних логов:
```bash
docker compose logs --tail=200 telegram-bot
docker compose logs --tail=200 cron
```
- Принудительная ротация: через `BACKUP_RETENTION_DAYS` > 0; иначе удаляйте старые файлы вручную.
- Проверка целостности SQLite-файла вручную:
```bash
sqlite3 ./database/articles.db 'PRAGMA integrity_check;'
```
- Создать мгновенный небезопасный файлобэкап рядом с БД:
```bash
python -c 'from src.database import backup_database_copy; print(backup_database_copy())'
```
- Изменить симлинк `latest` вручную:
```bash
cd backups/db/sqlite
ln -sfn warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz[.age] latest.tar.gz[.age]
```
- Включить/отключить шифрование: управляйте `AGE_PUBLIC_KEYS` (есть ключи — шифруем при `--encrypt auto`, нет — не шифруем).
- Точка восстановления “на время”: укажите метку времени из имени файла бэкапа через `--at`.
- “Сухой прогон” восстановления: добавьте `--dry-run`.
- После восстановления перезапустите сервисы, использующие БД.
- Для долгих задач делайте восстановление при остановленных сервисах, чтобы исключить запись в БД во время замены файла.
- Никогда не редактируйте `articles.db` вручную — используйте скрипты/SQLite-инструменты.
- Храните `AGE_SECRET_KEY` только там, где есть право на восстановление; не добавляйте в Git.
- Для защиты `.env` используйте Docker secrets или переменные окружения CI/CD вместо коммита в репозиторий.
- Регулярно тестируйте восстановление из свежих бэкапов на стенде.
- При переходе между окружениями убедитесь, что путь к БД и монтирования совпадают с теми, что ожидают скрипты.
- Следите за временем на хосте — метки времени в именах файлов используют UTC-формат `YYYYMMDDTHHMMSSZ`.
- Если меняете структуру БД, делайте бэкап перед миграцией.
- При ошибках запуска `cron` проверьте, что в образ установлен `cron` и создан файл `/var/log/cron.log` (в `docker-compose.yml` это делается командой сервиса `cron`).
- Если нужно включить бэкап `.env`, используйте `tools/backup.py --component env` (всегда шифруется; потребуется `AGE_PUBLIC_KEYS`).
- Чтобы ограничить размер каталога бэкапов, используйте `BACKUP_RETENTION_DAYS` и периодически проверяйте дисковое пространство.

### Коротко
- **Сохранить**: одноразовый контейнер с `tools/backup.py`, опционально `age`-шифрование, артефакт + checksum в `./backups/db/sqlite`, актуальный — `latest`.
- **Восстановить**: остановить сервисы → `tools/restore.py --at latest` (или по метке) → `integrity_check=ok` → запустить сервисы.
