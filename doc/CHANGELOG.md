# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Circuit Breaker для Telegram API с простыми и понятными сообщениями в логах.
- Ретраи на сетевые/временные ошибки (`NetworkError`, `TimedOut`, `RetryAfter`) c экспоненциальной задержкой (tenacity).
- Очередь отложенных публикаций (`pending_publications`) и фоновая задача флашера.
- Явная инициализация JobQueue для фоновых задач.

### Changed
- Улучшены сообщения логов предохранителя (понятный язык).
- Обновлена документация (`DEPLOYMENT.md`) по новым env-параметрам и надёжности сети.
- Обновлена зависимость: `python-telegram-bot[job-queue]==21.4`.

### Fixed
- Ряд потенциальных ошибок при недоступности Telegram: корректная буферизация, повторная доставка, отсутствие бесконечных ретраев.

