## План перевода проекта на московское время (Europe/Moscow)

Цель: согласовать поведение приложения с московским временем для пользовательского вывода и календарных границ (день/неделя/месяц), сохранив хранение времени в БД в UTC.

Ключевые принципы:
- Хранить время в БД строго в UTC (ISO 8601 с суффиксом Z или явно tz-aware UTC).
- Все пользовательские расчеты «вчера/неделя/месяц» — в таймзоне Europe/Moscow.
- На входных/выходных границах конвертировать UTC ↔ Europe/Moscow.
- В логах и контейнере — локальная TZ Europe/Moscow для удобства поддержки.

### 1) Инфраструктура и окружение
- **Docker/Compose**:
  - Добавить переменную окружения TZ и пробрасывать ее в сервисы.
  - Обновить `docker-compose.yml`:
```yaml
services:
  telegram-bot:
    # ...
    environment:
      - TZ=${TZ:-Europe/Moscow}
      # остальные переменные...
  web:
    # ...
    environment:
      - TZ=${TZ:-Europe/Moscow}
      # остальные переменные...
```
  - В `.env` оставить/зафиксировать:
```env
# Прикладная таймзона
TIMEZONE=Europe/Moscow
# Системная таймзона контейнеров
TZ=Europe/Moscow
```
- **Базовый образ**: установить системные таблицы часовых поясов.
  - Debian/Ubuntu: `apt-get update && apt-get install -y tzdata`
  - Alpine: `apk add --no-cache tzdata`
- **Python zoneinfo**:
  - Для Linux с tzdata ничего ставить через pip не нужно.
  - Для минимальных/нестандартных окружений можно добавить зависимость `tzdata` (pip) как fallback.

### 2) Конфигурация приложения
- В `config.py` (или модуле загрузки окружения) добавить чтение `TIMEZONE` и подготовить объект таймзоны:
```python
import os
from zoneinfo import ZoneInfo

APP_TZ_NAME = os.getenv("TIMEZONE", "Europe/Moscow")
APP_TZ = ZoneInfo(APP_TZ_NAME)
```
- Добавить утилиты для времени (новый модуль, напр. `src/time_utils.py`):
```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def now_msk(app_tz: ZoneInfo) -> datetime:
    return datetime.now(app_tz)

def to_utc(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)

def utc_to_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(tz)
```

### 3) Логи
- Поскольку системная TZ в контейнере будет Europe/Moscow, текущее форматирование логов в `src/bot.py` останется корректным: вывод уже идет в локальном времени.
- Проверить, что другие процессы (uvicorn/FastAPI) наследуют TZ (да, при пробросе `TZ`).

### 4) Хранение и миграция времени в БД
- Текущее состояние:
  - SQLite поля `created_at/updated_at` используют `CURRENT_TIMESTAMP` (UTC по спецификации SQLite).
  - Поля вроде `published_at` приходят как ISO-строки из пайплайна парсинга/публикации и могут быть naive.
- Решение:
  - Нормализовать сохранение во всех путях записи в БД строго в UTC (ISO 8601 с `Z`), конвертируя из Europe/Moscow при необходимости.
  - Примеры мест:
    - `src/database.py`: функции `add_article`, `upsert_raw_article` — перед вставкой приводить `published_at` к UTC (`to_utc(...)`).
- Ретро-миграция (по желанию):
  - Если в БД уже лежат naive-значения, считаем их московскими и преобразуем в UTC:
    - Экспорт → корректировка → импорт, или одноразовый скрипт на Python, проходящий по строкам и обновляющий `published_at = to_utc(parsed_dt, APP_TZ)`.
  - Сделать бэкап через уже имеющуюся `backup_database_copy()` до миграции.

### 5) Бизнес-логика и границы периодов (MSK)
- Команды дайджестов в `src/bot.py` используют `datetime.now()` без TZ.
  - Заменить на `now_msk(APP_TZ)` и расчеты границ периода выполнять в MSK.
  - Пример (фрагмент для daily):
```python
from config import APP_TZ
from time_utils import now_msk

now = now_msk(APP_TZ)
yesterday = (now - timedelta(days=1))
start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
# Перед запросом в БД конвертировать в UTC ISO
from time_utils import to_utc
start_utc = to_utc(start_date, APP_TZ).isoformat()
end_utc = to_utc(end_date, APP_TZ).isoformat()
```
  - В `database.get_summaries_for_date_range()` ожидать UTC-строки. Если сегодня используются SQLite-выражения `datetime('now', ...)`, помнить, что это UTC — это хорошо и совместимо.
- Форматирование дат для вывода пользователю:
  - В `status()` и ответах для дайджестов: конвертировать UTC → MSK перед `strftime`.
```python
from time_utils import utc_to_local

# last_posted_article['published_at'] хранится в UTC ISO
utc_dt = datetime.fromisoformat(last_posted['published_at'].replace("Z", "+00:00"))
local_dt = utc_to_local(utc_dt, APP_TZ)
date_str = local_dt.strftime('%d %B %Y в %H:%M')
```

### 6) Планировщик задач
- `python-telegram-bot` `JobQueue.run_repeating` планирует по секундам — не зависит от TZ.
- Если появятся задачи «запуск в 09:00 по Москве», использовать явные расчеты следующего запуска в MSK с конвертацией в UTC.

### 7) Метрики и health
- Метрики Prometheus не требуют конвертации; значения — числа, а временные метки ставит Prometheus/клиентская библиотека (UTC).
- Поле `LAST_ARTICLE_AGE_MIN` уже считает от `datetime.now(timezone.utc)` — оставить без изменений.

### 8) Тесты и регрессия
- Добавить юнит-тесты на конвертации:
  - naive(MSK) → UTC; UTC → MSK; границы дня/недели/месяца.
- Проверить сценарии:
  - Создание daily/weekly/monthly дайджестов для дат около полуночи MSK.
  - Отображение `status` и форматирование дат.

### 9) Чек-лист внедрения
- [ ] Обновить `docker-compose.yml` (проброс `TZ`).
- [ ] Обновить `.env` (убедиться, что `TIMEZONE` и `TZ` заданы).
- [ ] Установить `tzdata` в образ.
- [ ] Добавить `config.APP_TZ` и модуль `time_utils`.
- [ ] Привести все записи в БД к UTC при вставке/апдейте (`add_article`, `upsert_raw_article`, очереди и т.д.).
- [ ] Конвертация UTC → MSK в пользовательском выводе (бот, веб-интерфейс при нужде).
- [ ] Пересчитать границы периодов для дайджестов в MSK, запросы к БД — в UTC.
- [ ] (Опционально) Скрипт одноразовой корректировки исторических данных.
- [ ] Тесты конвертаций и e2e-проверка команд бота.

### 10) Риски и откат
- Если исторические `published_at` были сохранены как локальные без TZ, существует риск смещения при интерпретации. Решение — одноразовая миграция.
- Откат прост: вернуть `TZ` в контейнерах к прежнему значению, убрать конвертации в коде (хотя рекомендуется оставить хранение в UTC как стандарт).

### 11) Примечания
- Europe/Moscow не использует летнее/зимнее время — дополнительных переходов нет.
- Для API и внешних интеграций всегда документировать, что вход/выход в UTC, если не оговорено иначе.
