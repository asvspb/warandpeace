# Руководство по настройке WireGuard для проекта «War & Peace»

Последнее обновление: 2025‑08‑17

## 1. Цель и предпосылки
Это руководство описывает, как развернуть WireGuard‑сервер, сгенерировать клиентский конфиг, подключить проект через контейнер `wg-client` в Docker Compose, проверить работоспособность (рукопожатие, метрики, killswitch) и отладить возможные проблемы.

Требования:
- Доступ к серверу (VPS) для роли WireGuard‑сервера
- Docker + Docker Compose на клиентском хосте с проектом
- Права суперпользователя на обеих машинах

## 2. Генерация ключей (сервер/клиент)
Сгенерируйте пары ключей X25519. Приватные ключи храните в секрет‑хранилище; не коммитьте в git.

```bash
# На сервере
umask 077
wg genkey | tee server_private.key | wg pubkey > server_public.key

# На клиенте
umask 077
wg genkey | tee client_private.key | wg pubkey > client_public.key
```

## 2.1. Только клиент (без собственного WG‑сервера)
Если у вас уже есть внешний WireGuard‑сервер (им управляет другой админ) — серверную часть из этого руководства можно пропустить. Вам нужны только:
- публичный ключ сервера
- endpoint сервера (host:port) или IP:порт
- выделенные для вашего клиента адреса в туннеле (IPv4/IPv6)

Дальнейшие шаги (кратко):
1) Сгенерируйте ключи клиента и передайте администратору сервера ваш public key:
```bash
umask 077
wg genkey | tee client_private.key | wg pubkey > client_public.key
```
2) Заполните `config/wireguard/wg.env` минимально необходимыми полями и срендерьте клиентский конфиг:
```bash
./scripts/wireguard/manage.sh init
$EDITOR config/wireguard/wg.env
./scripts/wireguard/manage.sh render
```
Минимум в `wg.env`:
```env
WG_CLIENT_PRIVATE_KEY=...                # из client_private.key
WG_SERVER_PUBLIC_KEY=...                 # дал админ сервера
WG_SERVER_ENDPOINT=wg.example.com:51820  # или WG_SERVER_IP/WG_SERVER_PORT
WG_CLIENT_ADDR_IPV4=10.0.0.2/24          # адреса в туннеле — дал админ
WG_CLIENT_ADDR_IPV6=fd30:0:0::2/64       # опционально, если выдан IPv6
# опции: WG_CLIENT_DNS, WG_CLIENT_MTU
```
3) Запустите VPN‑клиент и проверьте:
```bash
./scripts/wireguard/manage.sh up
./scripts/wireguard/manage.sh status
./scripts/wireguard/manage.sh logs
```
Примечания: killswitch уже настроен (разрешены только lo, wg0 и UDP к серверу); для ротации ключа используйте `./scripts/wireguard/manage.sh rotate-key` и сообщите новый public key администратору сервера.

## 3. Сервер: генерация и установка `wg0.conf`
Используйте единый управляющий скрипт. Он соберёт конфигурацию из ENV/файла и системной информации (egress‑интерфейс определит автоматически, если не задан).

Вариант A (через переменные окружения текущей сессии):
```bash
# Обязательные переменные
export WG_SERVER_PRIVATE_KEY="$(cat server_private.key)"
export WG_CLIENT_PUBLIC_KEY="$(cat client_public.key)"

# Необязательные (есть дефолты)
export WG_LISTEN_PORT=51820
export WG_EGRESS_INTERFACE="eth0"            # если пропустить — определится автоматически
export WG_SERVER_ADDR_IPV4="10.0.0.1/24"
export WG_SERVER_ADDR_IPV6="fd30:0:0::1/64"  # опционально
export WG_CLIENT_ADDR_IPV4="10.0.0.2/32"
export WG_CLIENT_ADDR_IPV6="fd30:0:0::2/128" # опционально

./scripts/wireguard/manage.sh render-server
```

Вариант B (через файл конфигурации `config/wireguard/wg.server.env`):
```bash
cat > config/wireguard/wg.server.env <<'ENV'
WG_SERVER_PRIVATE_KEY=...
WG_CLIENT_PUBLIC_KEY=...
WG_LISTEN_PORT=51820
WG_EGRESS_INTERFACE=eth0
WG_SERVER_ADDR_IPV4=10.0.0.1/24
WG_SERVER_ADDR_IPV6=fd30:0:0::1/64
WG_CLIENT_ADDR_IPV4=10.0.0.2/32
WG_CLIENT_ADDR_IPV6=fd30:0:0::2/128
ENV

./scripts/wireguard/manage.sh render-server
```

Полученный файл: `config/wireguard/wg0.server.conf`. Скопируйте его на сервер:

```bash
sudo install -m 600 -o root -g root config/wireguard/wg0.server.conf /etc/wireguard/wg0.conf

# Включите форвардинг
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward >/dev/null
echo 1 | sudo tee /proc/sys/net/ipv6/conf/all/forwarding >/dev/null

# Запустите сервис
sudo systemctl enable --now wg-quick@wg0

# Проверка
sudo wg show
```

Откройте UDP 51820 в файрволе. При возможности ограничьте доступ по исходящему IP клиента.

## 4. Клиент: генерация `wg0.conf`
Рекомендуется хранить настройки клиента в `config/wireguard/wg.env` и использовать управляющий скрипт.

Шаг 1. Инициализация файла настроек и заполнение:
```bash
./scripts/wireguard/manage.sh init
$EDITOR config/wireguard/wg.env
# Минимум нужно заполнить: WG_CLIENT_PRIVATE_KEY, WG_SERVER_PUBLIC_KEY, и один из WG_SERVER_ENDPOINT или WG_SERVER_IP/WG_SERVER_PORT
```

Шаг 2. Рендер конфига клиента:
```bash
./scripts/wireguard/manage.sh render
```

Файл создаётся: `config/wireguard/wg0.conf` (killswitch уже настроен: разрешены `lo`, `wg0` и UDP к серверу; остальное DROP, включая IPv6 при наличии настроек).

Важное:
- Для строгого killswitch в `wg0.conf` клиента Endpoint должен быть IP, а не DNS‑имя. Используйте `WG_SERVER_ENDPOINT` для резолва на этапе генерации.

## 5. Docker Compose: включение `wg-client` и бота
В `docker-compose.yml` уже есть сервис `wg-client` и `telegram-bot` с `network_mode: "service:wg-client"`. Убедитесь, что:
- `wg-client` имеет `cap_add: NET_ADMIN`, `devices: /dev/net/tun:/dev/net/tun`
- Примонтирован `./config/wireguard:/config` (там лежит `wg0.conf`)
- Порт метрик `8000:8000` выставлен на `wg-client`
- У `telegram-bot` отсутствует секция `ports`
- Healthcheck `wg-client` проверяет «давность рукопожатия»

Проверка синтаксиса:
```bash
docker compose config -q
```

## 6. Подъём туннеля и проверка
Поднимите только VPN‑клиент:
```bash
docker compose up -d wg-client
docker compose logs -f wg-client
```
Проверьте состояние:
```bash
docker compose exec wg-client sh -lc 'ip addr show wg0 || true'
docker compose exec wg-client sh -lc 'wg show'
docker inspect --format '{{.State.Health.Status}}' wg-client
```
Ожидаемо: интерфейс `wg0` активен, есть последнее рукопожатие, status: `healthy`.

Запустите бота через VPN и проверьте метрики:
```bash
docker compose up -d telegram-bot
docker compose ps
curl -fsS http://localhost:8000/metrics | head
```

## 7. Проверка killswitch
Имитируйте падение туннеля, убедитесь, что трафик блокируется (кроме UDP к серверу):
```bash
docker compose exec wg-client sh -lc 'wg-quick down wg0'
docker compose exec wg-client sh -lc 'curl -m2 -sS https://1.1.1.1 || echo "blocked (expected)"'
docker compose exec wg-client sh -lc 'wg-quick up wg0'
```

## 8. Диагностика и частые проблемы
- Нет интерфейса `wg0` / ошибка создания:
  - На хосте должен быть доступен `/dev/net/tun`; в Compose заданы `devices` и `NET_ADMIN`
  - Если модуль WG не загружен — загрузите (`modprobe wireguard`) или оставьте том `/lib/modules`
- Нет рукопожатия:
  - UDP 51820 открыт, корректный egress‑интерфейс на сервере
  - Ключи соответствуют peer’ам, адреса AllowedIPs совпадают
  - Endpoint клиента — IP (для жёсткого killswitch)
- Метрики недоступны:
  - При `network_mode: service:wg-client` порт пробрасывается из `wg-client`
- Healthcheck «флапает»:
  - Увеличьте порог (например, до 300 сек) или интервал
- DNS‑утечки:
  - В клиентском `wg0.conf` задан `DNS=...`; проверьте резолвер контейнера

## 9. Безопасность ключей
- Приватные ключи — только в секрет‑хранилище (Vault, GitHub/GitLab Secrets)
- В CI/Compose подавайте их через переменные окружения/секреты
- Регулярная ротация и ограничение доступа по принципу минимально необходимого

## 10. Управление через `manage.sh`
```bash
# Проверка и инициализация
./scripts/wireguard/manage.sh validate
./scripts/wireguard/manage.sh init

# Рендеры
./scripts/wireguard/manage.sh render           # клиент
./scripts/wireguard/manage.sh render-server    # сервер

# Управление жизненным циклом клиента
./scripts/wireguard/manage.sh up
./scripts/wireguard/manage.sh status
./scripts/wireguard/manage.sh logs
./scripts/wireguard/manage.sh restart
./scripts/wireguard/manage.sh stop

# Ротация ключа и переустановка
./scripts/wireguard/manage.sh rotate-key
./scripts/wireguard/manage.sh reinstall --rotate
```

## 11. Полезные команды (низкоуровневые)
```bash
# Проверка compose и логов
docker compose config -q
docker compose logs -f wg-client

# Отладка маршрутизации и правил
docker compose exec wg-client sh -lc 'wg show; ip route; ip rule'

# Давность рукопожатия (сек)
docker compose exec wg-client sh -lc 'v=$(wg show wg0 latest-handshakes | awk "{print $2}"); echo $(( $(date +%s) - v ))'
```

## 12. Обновление конфигов
При изменении ENV перегенерируйте конфиги и перезапустите клиента через управляющий скрипт:
```bash
./scripts/wireguard/manage.sh render
./scripts/wireguard/manage.sh render-server  # при необходимости
./scripts/wireguard/manage.sh restart
```
