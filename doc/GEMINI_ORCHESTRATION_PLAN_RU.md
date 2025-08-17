Последнее обновление: 2025-08-16
Статус: ready

## План оркестрации Gemini в Linux (CLI + операционные процедуры)

Цель: обеспечить удобное и надежное управление Google Gemini из Linux-консоли для локальных задач (промптинг, суммаризация файлов, проверка моделей/ключей, ротация ключей), с учетом ограничений квот и отказоустойчивости (fallback на Mistral).

### 1) Окружение и секреты
- Переменные в `.env` (см. `.env.example`):
  - `GOOGLE_API_KEYS=key1,key2,...` — список ключей через запятую (приоритетно)
  - `GOOGLE_API_KEY=...` — одиночный ключ (legacy)
  - `GEMINI_MODEL=gemini-2.0-flash` — модель по умолчанию
  - (опционально) `MISTRAL_API_KEY` и `MISTRAL_MODEL_NAME=mistral-large-latest`
- Python-зависимости уже есть в `requirements.txt`: `google-generativeai`, `python-dotenv`, `mistralai` (fallback при необходимости).

### 2) Инструмент CLI
- Примечание: упоминавшийся ранее `scripts/gemini_cli.py` в текущей кодовой базе отсутствует (план/идея).
- Фактические возможности доступны через:
  - `scripts/manage.py` — команды для backfill/summarize и вспомогательные операции.
  - `src/summarizer.py` — прямой вызов функций суммаризации Gemini/Mistral из Python.
- При необходимости отдельный CLI может быть добавлен позднее; примеры команд в данном документе следует считать планом.

### 3) Практика использования
- Базовые примеры:
  - `python3 scripts/gemini_cli.py prompt -q "Кратко опиши проект"`
  - `python3 scripts/gemini_cli.py summarize-file README.md`
  - `python3 scripts/gemini_cli.py models:list`
  - `python3 scripts/gemini_cli.py keys:check`
- Режим JSON для автоматизированных пайплайнов: `--json` возвращает структурированный вывод.

### 4) Ротация ключей и устойчивость
- Если встречаются ошибки `400 User location is not supported` или `429 Resource has been exhausted`:
  - Переключитесь на следующий ключ: `keys:rotate --current-index N` → вернет новый индекс.
  - Повторите команду с `--key-index` (или обновите `.env`).
- Fallback на Mistral:
  - Для критичных операций в коде оставляем fallback (см. `doc/GEMINI.md`);
  - В CLI можно добавить опцию `--fallback-mistral` в будущем (не обязательно сейчас).

### 5) Интеграция с Linux
- Удобные алиасы в шелле (`~/.bashrc`) — пример для manage.py:
```bash
alias wnp-sumrange='docker compose run --rm telegram-bot python3 scripts/manage.py summarize-range'
```
- Systemd‑таймеры (пример периодической проверки ключей):
```ini
# /etc/systemd/system/gemini-keys-check.service
[Unit]
Description=Gemini keys health check

[Service]
Type=oneshot
WorkingDirectory=/app
EnvironmentFile=/app/.env
ExecStart=/usr/bin/true
# Примечание: CLI для Gemini в текущем репозитории отсутствует; таймер/юнит оставлен как шаблон.

# /etc/systemd/system/gemini-keys-check.timer
[Unit]
Description=Run gemini keys check hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```
- Логи systemd: `journalctl -u gemini-keys-check.service -n 100 -f`

### 6) Эксплуатация и ограничения
- Соблюдать квоты — при больших объёмах использовать батч‑обработку с задержками (добавить `--sleep-ms` при необходимости).
- Хранить ключи только в `.env` (не коммитить).
- При ошибках сети/HTTP — повторять с экспоненциальной задержкой; CLI уже логирует статус‑коды и класс ошибок.

### 7) Наблюдаемость
- В CLI выводить метрики времени ответа и размер входа/выхода (в stderr или с `--json` в stdout).
- Для регулярных прогонов отправлять статус в системный журнал (systemd) и/или писать в лог‑файл.

### 8) Чек‑лист внедрения
- [ ] Заполнить `.env` ключами `GOOGLE_API_KEYS`
- [ ] Прогнать `python3 scripts/gemini_cli.py models:list`
- [ ] Проверить ключи: `python3 scripts/gemini_cli.py keys:check`
- [ ] Настроить алиасы или шорткаты в оболочке
- [ ] (Опционально) Включить systemd‑таймер

### 9) Риски и откат
- Блокировки/квоты — переключение ключей, снижение частоты запросов.
- Ошибки совместимости версии библиотеки — зафиксированы версии в `requirements.txt`.
- Нетворкинг — проверять доступность, при необходимости использовать VPN (см. `doc/WIREGUARD_INTEGRATION_PLAN_RU.md`).
