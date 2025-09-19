# War & Peace — Новости, суммаризация и публикации

Этот репозиторий содержит Telegram-бота и пайплайн для сбора, суммаризации и публикации новостей. 

Документация:
- DEPLOYMENT.md — как запустить
- WARP.md — обзор архитектуры и правила
- doc/STATUS.md — текущее состояние (генерируется: `python3 scripts/docs/generate_status.py`)
- doc/PLANNING.md — агрегатор планов
- doc/ROADMAP.md — направления на 1–2 квартала
- doc/RELEASELOG.md — заметки о релизах

Git hooks:
- Включить версионируемые хуки: `git config core.hooksPath .githooks`
- Pre-commit хук автоматически генерирует doc/STATUS.md и БЛОКИРУЕТ коммит, если документация не обновлена (можно временно обойти `--no-verify`).
