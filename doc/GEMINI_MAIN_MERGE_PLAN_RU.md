Последнее обновление: 2025-08-16
Статус: ready

## План слияния изменений по Gemini в главную ветку (`main`)

Цель: безопасно выпустить в `main` изменения, связанные с Gemini (обновления `doc/GEMINI.md`, плейбуки ИИ, CLI‑утилита `scripts/gemini_cli.py`, оркестрация и сопутствующие правки), подготовив документацию и артефакты релиза.

### 1) Область и зависимости
- В рамках релиза войдут:
  - `doc/GEMINI.md`, `doc/AI_EXECUTION_PLAYBOOK_RU.md`, `doc/GPT5.md` (правила и сценарии)
  - `doc/GEMINI_ORCHESTRATION_PLAN_RU.md` (операционные процедуры)
  - `scripts/gemini_cli.py` (CLI)
- Зависимости (проверить в `requirements.txt`): `google-generativeai`, `click`, `python-dotenv`, `mistralai` (fallback)

### 2) Предрелизная проверка (develop)
- [ ] Тесты: `pytest -q` — все зелёные
- [ ] Сборка: `docker-compose build` проходит
- [ ] CLI Gemini:
  - [ ] `python3 scripts/gemini_cli.py models:list`
  - [ ] `python3 scripts/gemini_cli.py keys:check`
  - [ ] `python3 scripts/gemini_cli.py prompt -q "ok?"`
- [ ] `.env.example` содержит `GOOGLE_API_KEYS`, `GEMINI_MODEL`, комментарии по `TZ`/`TIMEZONE`
- [ ] Нет секретов/ключей в git

### 3) Документация релиза
  - Перенести секцию `Unreleased` в `## [vX.Y.Z] - YYYY-MM-DD`
  - Оставить пустую секцию `Unreleased` для следующего цикла
- [ ] Создать/обновить `doc/RELEASELOG.md` с кратким резюме релиза (что и зачем)
- [ ] В `doc/PLANNING.md` отметить статус плана оркестрации как «выпущено в main vX.Y.Z»

### 4) Подготовка PR `develop` → `main`
- [ ] Заголовок: "Release: Gemini orchestration and CLI"
- [ ] Тело PR (кратко):
  - Summary: 1–3 пункта ключевых изменений
  - Test plan: список проверок из п.2
  - Risks & Rollback (см. ниже)

### 5) Слияние и теги
- [ ] После одобрения — выполнить merge без squash (сохранить историю)
- [ ] Создать тег: `git tag -a vX.Y.Z -m "Release vX.Y.Z: Gemini orchestration and CLI"`
- [ ] `git push --tags`
- [ ] (Опционально) Создать GitHub Release на основе тега, вложить выдержку из `RELEASELOG.md`

### 6) Пост‑релиз
- [ ] Мониторинг после релиза (логи, метрики; проверить CLI ключей на прод‑хосте)

### 7) Риски и откат
- Проблемы совместимости зависимостей — быстрый rollback: `git revert` коммита релиза, снять тег/поставить новый
- Сбой Gemini (квоты/гео) — использовать Mistral (fallback), ротация ключей (`keys:rotate`)

### 8) Команды‑шпаргалки
```bash
# Проверки
pytest -q
python3 scripts/gemini_cli.py keys:check --json

# Теги
git tag -a vX.Y.Z -m "Release vX.Y.Z: Gemini orchestration and CLI"
git push --tags

# Создание release (через gh)
# gh release create vX.Y.Z -t "vX.Y.Z" -F doc/RELEASELOG.md
```
