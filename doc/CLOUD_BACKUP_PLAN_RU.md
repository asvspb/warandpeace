Последнее обновление: 2025-08-16
Статус: ready

## План резервного копирования в облако и локально

Цель: надёжно и предсказуемо резервировать данные проекта в удалённое (S3‑совместимое или Яндекс.Диск) и/или локальное файловое хранилище на сервере с проверкой целостности, ротацией и документированной процедурой восстановления. План минимизирует ошибки за счёт чётких чек‑листов, стандартизированных имён файлов и автоматизации.

## 1) Объекты бэкапа (Scope)
In Scope:
- База данных:
  - SQLite: файл БД + при необходимости WAL/SHM (консистентный снимок через API).
  - PostgreSQL: логический дамп `pg_dump` (формат custom) или `pg_basebackup`.
- Конфигурация и состояние:
  - `.env` (только в зашифрованном виде), `.env.example` (справочно).
  - Миграции/алембик (каталог `alembic/`), скрипты в `scripts/`, планы в `doc/` (опц.).
  - Медиа (если используется каталог `/app/media`) — как отдельный профиль бэкапа.

Out of Scope (сейчас):
- Живое хранение базы на удалённом диске/синке (запрещено; только архивы/дампы).
- Снепшоты контейнеров/образов (восстанавливаются пересборкой).

## 2) Хранилища (бэкенды)
Поддерживаются три бэкенда. Выбор — переменной `STORAGE_BACKEND=s3|yadisk|local`. Можно использовать несколько последовательно: локально как первичный (быстрый), затем асинхронная репликация на удалённый.

A) S3‑совместимое (Backblaze B2 / Wasabi / MinIO / AWS S3 / Yandex Object Storage)
- Бакет: `warandpeace-backups`.
- Шифрование: SSE‑S3 (или KMS) +/или клиентское `age`.
- Преимущества: версионирование, lifecycle, метаданные, высокая надёжность.

B) Яндекс.Диск (WebDAV / API)
- Использование только как удалённого хранилища архивов/дампов. Живые файлы БД хранить нельзя.
- Аутентификация: OAuth‑токен (WebDAV: заголовок `Authorization: OAuth <token>`).
- Ограничения: нет lifecycle‑политик, лимиты API, возможные задержки синхронизации.
- Обязательное клиентское шифрование (например, `age`) для `.env` и желательно для архивов БД.

C) Локальное файловое хранилище (на сервере)
- Каталог, например: `/var/backups/warandpeace` (на отдельном диске/томе).
- Преимущества: минимальная задержка, независимость от сети, быстрый доступ для восстановления.
- Ограничения: не защищает от отказа сервера/диска, требуется контроль свободного места и собственная ротация.

## 3) Нотация/структура артефактов
Едино для всех бэкендов (UTC‑время в имени):
- `db/sqlite/warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz[.age]`
- `db/postgres/warandpeace-pg-dump-YYYYMMDDTHHMMSSZ.dump.tar.gz[.age]`
- `env/warandpeace-env-YYYYMMDDTHHMMSSZ.tar.gz.age` (всегда шифруется)
- `media/warandpeace-media-YYYYMMDDTHHMMSSZ.tar.zst[.age]` (опц.)
- `*.sha256` и `manifest.json` (в архиве и/или рядом)

Манифест: `created_at_utc`, `host`, `component`, `db_engine`, `versions` (python, app, pg_dump), `sizes`, `checksums`, `encryption`, `backend` (s3|yadisk|local).

## 4) Переменные окружения
Общие:
- `STORAGE_BACKEND=s3|yadisk|local`
- `BACKUP_ENABLED=true`
- `BACKUP_CRON=0 3 * * *`
- `BACKUP_RETENTION_DAYS=7`
- `BACKUP_RETENTION_WEEKS=4`
- `BACKUP_RETENTION_MONTHS=6`
- `BACKUP_TMP_DIR=/tmp/backup`
- `BACKUP_EXTRA_PATHS=/app/media` (опц.)
- `BACKUP_TAG=prod|stage`
- `AGE_PUBLIC_KEYS=age1...[,age1...]` (получатели)

S3:
- `S3_ENDPOINT=https://s3.eu-central-1.wasabisys.com`
- `S3_BUCKET=warandpeace-backups`
- `S3_REGION=eu-central-1`
- `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- `S3_SSE=auto` (auto|SSE-S3|aws:kms|none)
- `S3_STORAGE_CLASS=STANDARD` (опц.)

Яндекс.Диск (WebDAV):
- `YADISK_WEBDAV_URL=https://webdav.yandex.ru`
- `YADISK_OAUTH_TOKEN=<oauth-token>`
- `YADISK_BASE_DIR=/warandpeace-backups`
- `YADISK_CHUNK_SIZE_MB=16` (опц.)

Локально:
- `LOCAL_BACKUP_DIR=/var/backups/warandpeace`
- `LOCAL_MIN_FREE_GB=5` (минимально допустимый свободный объём; предупреждение/алёрт)
- `LOCAL_MAX_TOTAL_GB=50` (мягкий лимит на суммарный объём каталога бэкапов для проактивной очистки)

БД:
- `DB_ENGINE=sqlite|postgres`
- SQLite: `DB_SQLITE_PATH=/app/database/articles.db`
- PostgreSQL: `DATABASE_URL=postgresql://user:pass@host:5432/dbname` или `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`
- `PG_DUMP_OPTS=--format=custom --no-owner --no-privileges`

Наблюдаемость:
- `BACKUP_METRICS_PATH=/app/metrics/backup.prom`
- `HEALTHCHECKS_URL=https://hc-ping.com/<uuid>` (опц.)

## 5) Алгоритм бэкапа (единый)
`tools/backup.py`:
1) Проверка окружения/зависимостей и подготовка `BACKUP_TMP_DIR`.
2) Сбор данных:
   - SQLite: `sqlite3 <db> ".backup '<tmp>/sqlite.db'"` или Python API.
   - PostgreSQL: `pg_dump "$DATABASE_URL" $PG_DUMP_OPTS -f '<tmp>/pg.dump'`.
   - `.env`/`.env.example` и доп. пути.
3) Упаковка/манифест/чексумма (`sha256`).
4) Шифрование (`age`) по политике: `.env` — всегда; БД — рекомендуется.
5) Выгрузка в бэкенд:
   - `s3`: PutObject с метаданными; ретраи с экспоненциальной задержкой.
   - `yadisk`: WebDAV MKCOL/PUT/PROPFIND; ретраи и таймауты (см. раздел 5.1).
   - `local`: атомарное перемещение артефактов из `BACKUP_TMP_DIR` в `LOCAL_BACKUP_DIR` с созданием подкаталогов.
6) Ротация:
   - `s3`: lifecycle (рекомендуется) или внутренняя.
   - `yadisk`: внутренняя ротация (скрипт по префиксам и датам).
   - `local`: внутренняя ротация (скрипт; см. раздел 5.3).
7) Отчёт/метрики/healthcheck.

### 5.1 Загрузка на Яндекс.Диск (WebDAV)
Создание каталога (идемпотентно):
```bash
curl -X MKCOL -H "Authorization: OAuth $YADISK_OAUTH_TOKEN" \
  "$YADISK_WEBDAV_URL$YADISK_BASE_DIR/db/sqlite/"
```
Загрузка файла (PUT):
```bash
curl -T "$BACKUP_TMP_DIR/archive.tar.gz.age" \
  -H "Authorization: OAuth $YADISK_OAUTH_TOKEN" \
  "$YADISK_WEBDAV_URL$YADISK_BASE_DIR/db/sqlite/warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz.age"
```
(Опция) rclone: использовать backend `yandex` или `webdav` (vendor=yandex) для `copy`/`sync`.

### 5.2 Локальная выгрузка
- Убедиться, что каталог существует и имеет права: `install -d -m 0750 "$LOCAL_BACKUP_DIR"`.
- Создать структуру подкаталогов: `db/sqlite`, `db/postgres`, `env`, `media`.
- Переместить файлы атомарно: `mv "$BACKUP_TMP_DIR/archive.tar.gz.age" "$LOCAL_BACKUP_DIR/db/sqlite/<имя>"`.
- Создать/обновить симлинк `latest` на последний бэкап в каждом подпрофиле для быстрого восстановления.
- При нехватке места: попытаться выполнить внеплановую ротацию; если не удалось — зафейлить бэкап (метрики+алёрт).

Пример команд:
```bash
install -d -m 0750 "$LOCAL_BACKUP_DIR/db/sqlite" || true
mv "$BACKUP_TMP_DIR/archive.tar.gz.age" "$LOCAL_BACKUP_DIR/db/sqlite/warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz.age"
ln -sfn "$LOCAL_BACKUP_DIR/db/sqlite/warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz.age" \
       "$LOCAL_BACKUP_DIR/db/sqlite/latest.tar.gz.age"
```

### 5.3 Внутренняя ротация (локально и Яндекс.Диск)
- Алгоритм Grandfather‑Father‑Son:
  - Дневные: оставить `BACKUP_RETENTION_DAYS`.
  - Недельные: 1 на неделю, `BACKUP_RETENTION_WEEKS`.
  - Месячные: 1 на месяц, `BACKUP_RETENTION_MONTHS`.
- Для локального каталога можно начать с простой политики по времени (пример ниже) и отдельно реализовать недельные/месячные снапшоты как симлинки/теги.

Примеры (простая очистка по времени для локальных дневных):
```bash
# удалить .tar.gz.age старше 7 дней
find "$LOCAL_BACKUP_DIR/db/sqlite" -type f -name 'warandpeace-db-sqlite-*.tar.gz.age' -mtime +7 -delete
```
Расширенный GFS: скрипт группировки имён по ISO‑неделям/месяцам и выбор одного файла на период; остальные — удалить.

## 6) Процедура восстановления (`tools/restore.py`)
Общие шаги: выбрать бэкап (latest/по времени), получить файл (скачать или прочитать локально), проверить `sha256`, расшифровать (`age`), разархивировать, прочитать `manifest.json`.

Получение артефакта:
- `s3`: скачать `archive.*` и `*.sha256` (awscli/boto3).
- `yadisk`: скачать по WebDAV (curl/rclone).
- `local`: найти файл в `$LOCAL_BACKUP_DIR/<subdir>/` или использовать `latest.*`.

SQLite:
- Остановить сервисы, сделать локальную копию текущего файла, заменить `data/sqlite.db`, `PRAGMA integrity_check;`, запустить сервисы.

PostgreSQL:
- Создать пустую БД или `restore_<ts>`, `pg_restore -d <db> --clean --if-exists --no-owner data/pg.dump`.

`.env`:
- Всегда вручную и осознанно (секреты), сверить с `.env.example`.

Media:
- Распаковать в `/app/media`, проверить владельца/права.

## 7) Ротация: стратегии
- S3: Lifecycle (рекомендуется) или внутренняя ротация.
- Яндекс.Диск: внутренняя ротация (скриптом) по префиксам/датам.
- Локально: внутренняя ротация (скриптом) + контроль свободного места.

## 8) План внедрения (чек‑лист)
- [x] Выбрать `STORAGE_BACKEND=local` (или стратегию «local→remote» двумя задачами).
- Для S3:
  - [ ] Создать бакет, настроить IAM, переменные S3, при необходимости lifecycle.
- Для Яндекс.Диска:
  - [ ] Получить OAuth‑токен и заполнить `YADISK_*`.
  - [ ] (Опц.) Настроить `rclone` remote `yadisk:`.
- Для локального бэкапа:
  - [ ] Создать каталог `LOCAL_BACKUP_DIR` на отдельном томе, дать права 0750.
  - [x] Настроить мониторинг свободного места и лимиты `LOCAL_MIN_FREE_GB`/`LOCAL_MAX_TOTAL_GB`.
  - [x] Реализовать внутреннюю ротацию (cron/script) и симлинк `latest`.
- [ ] Установить зависимости: `age`, `sqlite3`, `pg_dump`/`pg_restore`, `python3` (`boto3`/`requests`/`xmltodict`), `curl`, `rclone` (опц.).
- [x] Реализовать `tools/backup.py`/`tools/restore.py` с бэкендом `local`.
- [ ] Настроить расписание (cron/systemd) и метрики.
- [ ] Провести тест‑восстановление (drill) на stage.

## 9) Расписание (cron/systemd)
Примеры (ежедневно 03:00 UTC):
```
# /etc/cron.d/warandpeace-backup (один из вариантов бэкенда)
0 3 * * * root /usr/bin/docker exec -t telegram-bot python3 tools/backup.py --component db --engine ${DB_ENGINE} --backend local
# Ротация уже встроена в скрипт, отдельная команда не нужна.
```

## 10) Наблюдаемость и алёртинг
Метрики (Prometheus textfile):
- `backup_last_success_timestamp{component="db"}`
- `backup_duration_seconds{component="db"}`
- `backup_size_bytes{component="db"}`
- `backup_failures_total{component}`
- `backup_backend{backend="s3|yadisk|local"} 1`
- Для локального: `backup_local_free_bytes`, `backup_local_used_bytes`
Алерты: нет успешного бэкапа >24ч; ≥3 провала подряд; скачок размера >50% WoW; свободное место < `LOCAL_MIN_FREE_GB`.
Healthchecks: ping `HEALTHCHECKS_URL` при успехе.

## 11) Тест‑план (drill)
- [x] Сухой прогон: создать бэкап, выгрузить в `local`, проверить `sha256`.
- [x] Восстановление SQLite (в отдельные копии/БД) из `local`.
- [ ] Инъекция сетевой ошибки (для удалённых): убедиться в ретраях и корректном fail‑логировании.
- [x] Ротация: сгенерировать бэкапы за 10 дней → проверить политику очистки.
- [ ] Шифрование: проверить недоступность содержимого без ключей.
- [ ] Производительность: измерить длительность; локальная выгрузка должна быть fastest.
- [x] Локальное пространство: тест низкого Free Space → корректная реакция и алёрт.

## 12) Риски и снижения
- Секреты: `.env` всегда шифруется; ключи/пароли только в секрет‑хранилище/переменных окружения.
- Консистентность SQLite: использовать `.backup`/API; избегать копирования «на лету».
- Консистентность PG: фиксировать версию `pg_dump`, тестировать `pg_restore`.
- S3 vs Яндекс.Диск: у Диска нет lifecycle; обязательна внутренняя ротация и аккуратные ретраи.
- Локальное хранилище: единая точка отказа (сервер/диск). Митигировать — хранить минимум один удалённый бэкап (S3/Диск) параллельно, мониторить SMART/свободное место, использовать отдельный том.
- Стоимость/квоты: следить за размером, сжимать (`zstd`), снижать частоту медиа‑бэкапов.

## 13) Критерии приемки (DoD)
- Ежедневный бэкап БД успешен 7/7 последних дней на выбранном бэкенде.
- Успешное тест‑восстановление на stage (из локального и из одного удалённого бэкенда).
- Метрики/алерты включены и валидированы искусственным сбоем/низким свободным местом.
- Ротация соответствует политике; локальное свободное место ≥ `LOCAL_MIN_FREE_GB`.
- Документация `.env.example`/`DEPLOYMENT.md` обновлена.

## 14) Откат (Rollback)
- `BACKUP_ENABLED=false`, отключить cron/systemd timer.
- Временно перейти на ручные бэкапы.
- При проблемах с удалённой выгрузкой — оставлять локальные бэкапы и настроить отложенную синхронизацию (`rclone copy` по расписанию).

## 15) Артефакты и документация
- Обновить `.env.example` (переменные раздела 4).
- Обновить `DEPLOYMENT.md` (установка `age`, `sqlite3`, `pg_dump`, `curl`/`rclone`, расписание, метрики, локальный каталог и ротация).
- Добавить в README раздел «Бэкапы и восстановление».

## Приложения

### Приложение A: Пример IAM для S3 (минимальные права)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow","Action": ["s3:PutObject","s3:GetObject","s3:DeleteObject"],"Resource": "arn:aws:s3:::warandpeace-backups/*"},
    {"Effect": "Allow","Action": ["s3:ListBucket","s3:GetBucketLocation"],"Resource": "arn:aws:s3:::warandpeace-backups"}
  ]
}
```

### Приложение B: Lifecycle S3 (пример)
```json
{"Rules": [{"ID": "ExpireDailyDB","Filter": {"Prefix": "db/sqlite/"},"Status": "Enabled","Expiration": {"Days": 7}}]}
```

### Приложение C: WebDAV примеры для Яндекс.Диска
```bash
# Создать каталог (идемпотентно)
curl -X MKCOL -H "Authorization: OAuth $YADISK_OAUTH_TOKEN" \
  "$YADISK_WEBDAV_URL$YADISK_BASE_DIR/db/sqlite/"

# Загрузка файла
curl -T "archive.tar.gz.age" -H "Authorization: OAuth $YADISK_OAUTH_TOKEN" \
  "$YADISK_WEBDAV_URL$YADISK_BASE_DIR/db/sqlite/warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz.age"

# Список содержимого (PROPFIND)
curl -X PROPFIND -H "Depth: 1" -H "Authorization: OAuth $YADISK_OAUTH_TOKEN" \
  "$YADISK_WEBDAV_URL$YADISK_BASE_DIR/db/sqlite/"

# Удаление
curl -X DELETE -H "Authorization: OAuth $YADISK_OAUTH_TOKEN" \
  "$YADISK_WEBDAV_URL$YADISK_BASE_DIR/db/sqlite/<filename>"
```

### Приложение D: Скелет CLI скриптов
```text
# tools/backup.py
usage: backup.py --component db|env|media --engine sqlite|postgres --backend s3|yadisk|local [--encrypt auto|on|off]

# tools/restore.py
usage: restore.py --component db|env|media --engine sqlite|postgres --backend s3|yadisk|local --at ISO8601|latest [--dry-run]
```

### Приложение E: Проверка места и очистка (локально)
```bash
# свободное место (ГБ)
FREE_GB=$(df -BG --output=avail "$LOCAL_BACKUP_DIR" | tail -n1 | tr -dc '0-9')
if [ "$FREE_GB" -lt "${LOCAL_MIN_FREE_GB:-5}" ]; then
  echo "Low free space: ${FREE_GB}G < ${LOCAL_MIN_FREE_GB}G" >&2
  # попробовать внеплановую очистку дневных старше 7 дней
  find "$LOCAL_BACKUP_DIR/db/sqlite" -type f -name 'warandpeace-db-sqlite-*.tar.gz.age' -mtime +7 -delete || true
fi
```
