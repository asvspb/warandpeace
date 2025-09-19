# STATUS — текущее состояние проекта

Обновлено: 2025-09-19T13:56:53.987030+03:00

## Версия и сборка
- Последний тег: 2.0.0
- Текущий коммит: 13fe5d8
- Docker base image: python:3.12-slim

## Сервисы (docker-compose)
- redis
- wg-client
- postgres
- telegram-bot
- watchdog
- web
- cron

## База данных
- Режим рантайма (по compose): PostgreSQL
- DATABASE_URL в .env: установлена (значение не показывается)

## Ключевые зависимости (requirements.txt)
- beautifulsoup4==4.12.3
- google-generativeai==0.7.2
- python-dotenv==1.0.1
- python-telegram-bot[job-queue]==21.4
- requests==2.32.3
- schedule==1.2.2
- prometheus-client==0.20.0
- aiohttp==3.9.5
- httpx==0.27.0
- tenacity==8.5.0
- click==8.1.7
- fastapi==0.111.0

---
Этот файл сгенерирован скриптом `scripts/docs/generate_status.py`. Не редактируйте вручную.
