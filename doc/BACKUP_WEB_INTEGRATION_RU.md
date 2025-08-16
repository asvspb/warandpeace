# Интеграция резервного копирования в веб‑интерфейс и инструкции по операциям

Последнее обновление: 2025‑08‑16
Статус: draft/ready for implementation

## 1. Цели и UX
- Для администраторов доступна страница «Backups»:
  - Список бэкапов: компонент, имя файла, дата/размер, шифрование, отметка latest.
  - Действия: скачать, удалить (с подтверждением), запустить новый бэкап, восстановить из выбранного (dry‑run/боевое).
  - Статусы: последний успешный бэкап, длительность, размер; свободное место в `LOCAL_BACKUP_DIR`.
  - Безопасность: доступ только под админом (Basic Auth уже есть).

## 2. Архитектура/эндпойнты (FastAPI)
- Шаблон: `src/webapp/templates/backup.html`
- Роуты в `src/webapp/server.py`:
  - `GET /admin/backups` — страница списка бэкапов.
  - `POST /admin/backups/run` — запуск бэкапа: параметры `component=db|env`, `engine=sqlite`, `encrypt=auto|on|off`.
  - `POST /admin/backups/restore` — восстановление: параметры `at=latest|YYYYMMDDTHHMMSSZ`, `dry_run=true|false`.
  - `POST /admin/backups/delete` — удаление файла (с подтверждением и защитой путей).
  - `GET /admin/backups/download?file=…` — скачивание файла.
  - (Опц.) `GET /admin/backups/status` — статус последней операции.
- Фоновые задачи: `BackgroundTasks` или Celery/RQ (не обязательно). Ответ — сразу 202/redirect, страница подтягивает статус.
- Интеграция со скриптами: дергать `tools/backup.py` и `tools/restore.py` через `subprocess`.

## 3. Скан каталога и модель данных
- Источник: `LOCAL_BACKUP_DIR`.
- Подкаталоги: `db/sqlite`, `env`.
- Маски:
  - DB: `warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz[.age]` (+ `*.sha256`), симлинк `latest.tar.gz[.age]`.
  - ENV: `warandpeace-env-YYYYMMDDTHHMMSSZ.tar.gz.age` (+ `*.sha256`), симлинк `latest.tar.gz.age`.
- Поля списка: компонент, имя, дата из имени, размер, шифрован ли (`.age`), наличие чексуммы и is_latest.

## 4. Валидация и безопасность
- Доступ — только к белым подкаталогам (`db/sqlite`, `env`).
- Проверка `Path.resolve()` на принадлежность `LOCAL_BACKUP_DIR`.
- Все деструктивные действия — через подтверждение (modal) и POST.

## 5. Метрики и логи (по мере готовности)
- Показать: `backup_last_success_timestamp`, `backup_duration_seconds`, `backup_size_bytes`, `backup_failures_total`.
- Отображать краткий лог последней операции (tail файла или in‑memory ring buffer).

## 6. Порядок внедрения
1) Добавить серверные ручки и фоновую обвязку.
2) Реализовать страницу списка и действий; защита путей и подтверждения.
3) Добавить статус/логи и базовые метрики.
4) (Опц.) Интегрировать удалённые бэкенды и healthchecks.

---

# Инструкция: создание и восстановление бэкапов

## Требования окружения
- Обязательные: `LOCAL_BACKUP_DIR`, `DB_SQLITE_PATH`, `BACKUP_TMP_DIR`.
- Для `.env`: обязательно `AGE_PUBLIC_KEYS`.
- Для расшифровки: `AGE_SECRET_KEY`.
- Опции: `BACKUP_RETENTION_DAYS`, `LOCAL_MIN_FREE_GB`.

## Через веб‑интерфейс
1) Откройте `/admin/backups`.
2) Создать бэкап:
   - «Создать бэкап БД»: выберите `encrypt=auto|on|off`; рекомендовано `auto` при заданных `AGE_PUBLIC_KEYS`.
   - «Создать бэкап .env»: всегда шифруется; требуется `AGE_PUBLIC_KEYS`.
3) Дождитесь статуса «успешно»; проверьте появление файла и обновление `latest`.
4) Восстановление:
   - «Восстановить (dry‑run)»: проверка `sha256`, расшифровка (если `.age` и есть `AGE_SECRET_KEY`), распаковка, `PRAGMA integrity_check`, без замены живой БД.
   - «Восстановить (боевое)»: те же проверки, затем переименование текущей БД в `.db.bak-<ts>` и установка восстановленного файла.

## Через CLI (локально/в контейнере)

### Бэкап БД (локально, без шифрования)
```bash
export LOCAL_BACKUP_DIR="$(pwd)/backups"
export BACKUP_TMP_DIR="$(pwd)/temp/backup_tmp"
export DB_SQLITE_PATH="$(pwd)/database/articles.db"
export LOCAL_MIN_FREE_GB=0
python3 tools/backup.py --component db --engine sqlite --backend local --encrypt off
```

### Бэкап БД (с шифрованием)
```bash
export AGE_PUBLIC_KEYS="age1..."
python3 tools/backup.py --component db --engine sqlite --backend local --encrypt auto
```

### Бэкап .env
```bash
export LOCAL_BACKUP_DIR="/var/backups/warandpeace"
export BACKUP_TMP_DIR="/tmp/backup"
export AGE_PUBLIC_KEYS="age1..."  # обязательно
python3 tools/backup.py --component env --backend local
```

### Через Docker Compose
```bash
docker compose exec telegram-bot \
  env BACKUP_TMP_DIR=/tmp/backup \
  python3 tools/backup.py --component db --engine sqlite --backend local --encrypt auto
```

### Где искать результат
- `LOCAL_BACKUP_DIR/db/sqlite/warandpeace-db-sqlite-YYYYMMDDTHHMMSSZ.tar.gz[.age]`
- `LOCAL_BACKUP_DIR/env/warandpeace-env-YYYYMMDDTHHMMSSZ.tar.gz.age`
- Рядом: `*.sha256` и симлинк `latest.*`.

## Восстановление БД (SQLite)

### Предостережения
- Выполняйте в окно обслуживания: остановите запись в БД.
- Для `.age` архивов нужен `AGE_SECRET_KEY`.

### Dry‑run
```bash
export LOCAL_BACKUP_DIR="/var/backups/warandpeace"
export BACKUP_TMP_DIR="/tmp/restore"
export DB_SQLITE_PATH="/app/database/articles.db"
# Для зашифрованных архивов:
# export AGE_SECRET_KEY="AGE-SECRET-KEY-..."
python3 tools/restore.py --component db --engine sqlite --backend local --at latest --dry-run
```

### Боевое восстановление
```bash
python3 tools/restore.py --component db --engine sqlite --backend local --at latest
```

### Восстановление из конкретного времени
```bash
python3 tools/restore.py --component db --engine sqlite --backend local --at 20250816T031500Z
```

## Восстановление `.env`
- Веб: скачать нужный архив `.age`, расшифровать локально, вручную обновить `.env`.
- CLI:
```bash
age --decrypt -i <(echo "$AGE_SECRET_KEY") -o env.tar.gz /path/to/warandpeace-env-YYYYMMDDTHHMMSSZ.tar.gz.age
tar -xzvf env.tar.gz
# Сверьте .env с .env.example и внесите изменения вручную
```

## Проверки после восстановления
- `PRAGMA integrity_check` (выполняется скриптом автоматически).
- Базовые sanity‑тесты приложения.
- Сделайте новый бэкап как «точку после восстановления».

## Частые проблемы
- Нет места: увеличьте свободное место в `LOCAL_BACKUP_DIR` или уменьшите `BACKUP_RETENTION_DAYS`.
- Нет `AGE_SECRET_KEY`: зашифрованные архивы не восстановить без ключа.
- "file is not a database": убедитесь, что выбран архив БД, а не `.env`.
