# Продакшн-настройка War & Peace (Web + WebAuthn + TLS)

Краткое, пошаговое руководство по развертыванию веб-интерфейса и включению входа по ключам (WebAuthn/Passkeys) за HTTPS. Подходит для Docker Compose на одном хосте с автоматическим TLS через Caddy.

## 0. Предварительные требования
- Домен, указывающий на сервер с публичным IP (A/AAAA-запись): `admin.example.com`.
- Открытые порты 80 и 443 на сервере (файрвол/безопасность).
- Docker и Docker Compose v2 установлены.

## 1. Обновление кода и подготовка окружения
```bash
# Клонирование/обновление
# git clone https://github.com/asv-spb/warandpeace.git && cd warandpeace
# или
git pull

# Скопируйте пример и заполните .env
cp .env.example .env
```

Минимальный набор переменных для продакшна (вставьте в `.env` и замените значения):
```ini
# Веб-режим: включить WebAuthn (Passkeys)
WEB_AUTH_MODE=webauthn
WEB_SESSION_SECRET=<длинный_секрет>   # сгенерируйте: openssl rand -hex 32

# RP ID должен совпадать с доменом админки (без порта)
WEB_RP_ID=admin.example.com
WEB_RP_NAME=War & Peace Admin

# Публикация через Caddy + Let’s Encrypt
CADDY_DOMAIN=admin.example.com
CADDY_EMAIL=you@example.com

# (Опционально) Включить JSON API и защитить ключом
WEB_API_ENABLED=false
WEB_API_KEY=
```

Подсказки:
- `WEB_RP_ID` строго соответствует домену, на котором открывается страница входа.
- `WEB_SESSION_SECRET` должен быть длинным и случайным; не публикуйте его.
- Если нужно оставить Basic Auth на переходный период, используйте `WEB_AUTH_MODE=basic` и `WEB_BASIC_AUTH_USER/PASSWORD`.

## 2. Запуск с TLS через Caddy
Файл `docker-compose.yml` уже содержит сервис `caddy` и обратный прокси на сервис `web`. Файл `Caddyfile` — в корне проекта.

Запуск:
```bash
docker compose up --build -d web caddy
```
Проверка:
- `docker compose ps` — сервисы `web` и `caddy` должны быть в состоянии Up.
- Через 10–60 секунд сертификаты Let’s Encrypt будут выданы автоматически.

## 3. Первичная привязка ключа и вход
1) Откройте в браузере: `https://admin.example.com/register-key`.
2) Нажмите «Привязать ключ», следуйте подсказкам браузера (Touch ID / Windows Hello / YubiKey и т. п.).
3) После успешной регистрации зайдите на `https://admin.example.com/login` и выполните вход по ключу.
4) Рекомендуется привязать минимум два ключа. Управление ключами — на странице «Ключи».

## 4. Метрики и мониторинг
- `https://admin.example.com/healthz` — проверка живости (200 OK).
- `https://admin.example.com/metrics` — метрики Prometheus. При необходимости ограничьте доступ по IP/правилам в `Caddyfile`.

## 5. Безопасность (чеклист)
- Включен HTTPS (Caddy) + корректный `WEB_RP_ID`.
- Включён режим `WEB_AUTH_MODE=webauthn`, сессии защищены `WEB_SESSION_SECRET`.
- Привязаны минимум два ключа администратора; у старых — регулярно проверяйте `sign_count`.
- API выключен или защищён `WEB_API_KEY` (заголовок `X-API-Key` или `Authorization: Api-Key <key>`).
- Обновляйте систему и Docker-образы; используйте firewall/Fail2Ban по необходимости.

## 6. Обновления и деплой
```bash
git pull
docker compose up --build -d web caddy
```

## 7. Трюблшутинг
- Сертификат не выдан: проверьте, что домен резолвится на ваш сервер и порты 80/443 доступны извне.
- Вход по WebAuthn не работает: проверьте соответствие `WEB_RP_ID` ↔ домен, наличие HTTPS, системное время, поддержку WebAuthn в браузере.
- `401` на `/api`: задайте `WEB_API_KEY` и передавайте его в заголовках.

## 8. Альтернативы
- Можно использовать Nginx/Traefik вместо Caddy — принцип тот же: HTTPS терминируется на прокси, а приложение доступно как `web:8080`.
- При наличии внешнего TLS/Ingress измените публикацию домена в соответствующем слое, `WEB_RP_ID` всё равно должен совпадать.
