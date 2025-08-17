Последнее обновление: 2025-08-16
Статус: ready

# План внедрения WireGuard VPN в проект «War & Peace» (оптимизированная версия)

## 1. Цели внедрения
1. Сокрытие реального публичного IP-адреса бота Telegram и связанных микросервисов.
2. Шифрование трафика между контейнерами/сервером и внешними API (Telegram, внешние БД, сторонние HTTP-ресурсы).
3. Реализация механизма отказоустойчивости: при падении VPN-туннеля трафик автоматически переключается на прямое соединение.

## 2. Текущее состояние инфраструктуры
- Приложение развёрнуто в контейнере `telegram-bot` (Docker Compose) на VPS.
- Другие сервисы отсутствуют или работают в той же Compose-сети.

## 3. Целевая архитектура сети с WireGuard
```
┌───────────────────────────────── VPS ─────────────────────────────────┐
│                                                                       │
│  [docker0]                                                            │
│    │                                                                   │
│    │ docker-compose              ┌───────────┐                         │
│    ├──────── telegram-bot -------► wg-client │ (healthcheck & fallback)│
│    │                              └───────────┘                         │
│    │                                                                   │
│    └──────── other services …                                         ▲│
│                                                                       ││ WireGuard tunnel (UDP/51820)
└────────────────────────────────────────────────────────────────────────┘│
                                                                          │
                                   ┌────────────── Cloud WG server ───────┘
                                   │  wg-server (public IP)               │
                                   └───────────────────────────────────────┘
```
- `wg-server` — облачный VPS-узел на выбранном хостинге, принимающий туннель.
- `wg-client` — sidecar-контейнер в Compose, который маршрутизирует трафик и управляет переключением на резервный канал.
- `telegram-bot` направляет весь исходящий трафик через `wg-client` при помощи `network_mode: "service:wg-client"`.

## 4. Подготовительные работы
1. Анализ трафика — определить домены/IP, куда обращается бот.
2. Подготовить доступы к выбранному хостинг-провайдеру для развертывания `wg-server`.
3. Оценка MTU/пропускной способности — подобрать оптимальный MTU (обычно 1420).

## 5. Развёртывание WireGuard-сервера (shell-скрипты)
Развертывание будет осуществляться через shell-скрипт, который создает конфигурацию на основе переменных окружения.

1.  **Подготовка переменных окружения на сервере:**
    ```bash
    # Внешний сетевой интерфейс сервера (например, eth0, ens3)
    export WG_EGRESS_INTERFACE="eth0"
    # Адреса сервера в туннеле
    export WG_SERVER_ADDR_IPV4="10.0.0.1/24"
    export WG_SERVER_ADDR_IPV6="fd30:0:0::1/64"
    # Приватный ключ сервера (сгенерировать и сохранить в безопасном месте)
    export WG_SERVER_PRIVATE_KEY="<server_private_key>"
    # Публичный ключ клиента
    export WG_CLIENT_PUBLIC_KEY="<client_public_key>"
    # Адреса клиента в туннеле
    export WG_CLIENT_ADDR_IPV4="10.0.0.2/32"
    export WG_CLIENT_ADDR_IPV6="fd30:0:0::2/128"
    ```

2.  **Скрипт создания конфигурации и запуска сервера:**
    ```bash
    #!/bin/bash
    set -e
    # 1. Установка WireGuard и сопутствующих утилит
    apt update && apt install -y wireguard wireguard-tools wireguard-tools
    # 2. Создание конфигурации из переменных окружения
    cat << EOF > /etc/wireguard/wg0.conf
    [Interface]
    Address = \${WG_SERVER_ADDR_IPV4}, \${WG_SERVER_ADDR_IPV6}
    ListenPort = 51820
    PrivateKey = \${WG_SERVER_PRIVATE_KEY}
    PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o \${WG_EGRESS_INTERFACE} -j MASQUERADE; ip6tables -A FORWARD -i wg0 -j ACCEPT; ip6tables -t nat -A POSTROUTING -o \${WG_EGRESS_INTERFACE} -j MASQUERADE
    PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o \${WG_EGRESS_INTERFACE} -j MASQUERADE; ip6tables -D FORWARD -i wg0 -j ACCEPT; ip6tables -t nat -D POSTROUTING -o \${WG_EGRESS_INTERFACE} -j MASQUERADE
    SaveConfig = true
    [Peer]
    PublicKey = \${WG_CLIENT_PUBLIC_KEY}
    AllowedIPs = \${WG_CLIENT_ADDR_IPV4}, \${WG_CLIENT_ADDR_IPV6}
    EOF
    # 3. Включение IP Forwarding
    sysctl -w net.ipv4.ip_forward=1
    sysctl -w net.ipv6.conf.all.forwarding=1
    # 4. Запуск сервиса
    systemctl enable --now wg-quick@wg0
    ```

## 6. Настройка WireGuard-клиента в Docker Compose
1.  **Обновленный `docker-compose.yml`:**
    ```yaml
    services:
      wg-client:
        image: linuxserver/wireguard:latest
        container_name: wg-client
        cap_add:
          - NET_ADMIN
        devices:
          - /dev/net/tun:/dev/net/tun
        sysctls:
          - net.ipv4.conf.all.src_valid_mark=1
        volumes:
          # Том /lib/modules может быть не нужен, если модуль WireGuard уже загружен на хосте
          - /lib/modules:/lib/modules:ro
          - ./config/wireguard:/config
        environment:
          - PUID=1000
          - PGID=1000
          - TZ=Europe/Moscow
        restart: unless-stopped
        ports:
          - "8000:8000" # Пробрасываем порт метрик бота
        healthcheck:
          test: ["CMD-SHELL", "wg show wg0 latest-handshakes | awk '{print $2}' | grep -qE '^[0-9]+$'"]
          interval: 30s
          timeout: 3s
          retries: 3

      telegram-bot:
        # ... (ваши остальные настройки)
        # УБЕДИТЕСЬ, ЧТО СЕКЦИЯ 'ports' ЗДЕСЬ ОТСУТСТВУЕТ
        network_mode: "service:wg-client"
        depends_on:
          - wg-client
    ```

2.  **Конфигурация клиента `config/wireguard/wg0.conf` с Killswitch:**
    *Внимание: `<wg_server_ip>` **должен быть IP-адресом**, а не DNS-именем.*
    ```ini
    [Interface]
    PrivateKey = <client_private_key>
    Address = 10.0.0.2/24, fd30:0:0::2/64
    MTU = 1420
    DNS = 1.1.1.1, 2606:4700:4700::1111
    PostUp = iptables -A OUTPUT ! -o wg0 -p udp -d <wg_server_ip> --dport 51820 -j ACCEPT; iptables -A OUTPUT ! -o wg0 -j DROP; ip6tables -A OUTPUT ! -o wg0 -p udp -d <wg_server_ipv6> --dport 51820 -j ACCEPT; ip6tables -A OUTPUT ! -o wg0 -j DROP
    PostDown = iptables -D OUTPUT ! -o wg0 -p udp -d <wg_server_ip> --dport 51820 -j ACCEPT; iptables -D OUTPUT ! -o wg0 -j DROP; ip6tables -D OUTPUT ! -o wg0 -p udp -d <wg_server_ipv6> --dport 51820 -j ACCEPT; ip6tables -D OUTPUT ! -o wg0 -j DROP

    [Peer]
    PublicKey = <server_public_key>
    AllowedIPs = 0.0.0.0/0, ::/0
    Endpoint = <wg_server_ip>:51820
    PersistentKeepalive = 25
    ```

## 7. Маршрутизация, исключения и killswitch
- Если нужно оставить часть исходящих подключений в обход VPN (например, локальный Prometheus/БД), используйте policy‑based routing внутри контейнера: маркируйте трафик через `iptables -t mangle -j MARK` и добавьте правила `ip rule`/`ip route` для отдельной таблицы.
- Не используйте отрицания в `AllowedIPs` (например, `!192.168.88.0/24`) — в стандартном WireGuard это не поддерживается. Исключения реализуются policy‑routing’ом.
- Killswitch в `wg-client`: запретить любой исходящий трафик мимо `wg0`, разрешив только соединение к `Endpoint` и loopback. Пример (IPv4):
  ```bash
  iptables -A OUTPUT -p udp -d <wg_server_ip> --dport 51820 -j ACCEPT
  iptables -A OUTPUT -o wg0 -j ACCEPT
  iptables -A OUTPUT -o lo -j ACCEPT
  iptables -A OUTPUT -j DROP
  ```
  Для IPv6 — аналоги через `ip6tables`.

## 8. CI/CD и управление ключами
1. Хранить приватные ключи только в секрет‑хранилище (Vault, GitHub Secrets, GitLab CI variables). Не хранить в git.
2. Генерация и деплой ключей Ansible’ом с использованием `wg` (X25519), а не `openssh_keypair`:
   ```yaml
   - name: Ensure WireGuard installed
     package:
       name: wireguard
       state: present

   - name: Generate WireGuard private key if absent
     command: wg genkey
     register: wg_priv
     args:
       creates: /etc/wireguard/server_private.key

   - name: Save private key
     copy:
       dest: /etc/wireguard/server_private.key
       content: "{{ wg_priv.stdout }}\n"
       mode: '0600'

   - name: Generate public key
     command: bash -lc "cat /etc/wireguard/server_private.key | wg pubkey"
     register: wg_pub

   - name: Deploy wg0.conf
     template:
       src: wg0.conf.j2
       dest: /etc/wireguard/wg0.conf

   - name: Enable service
     systemd:
       name: wg-quick@wg0
       state: started
       enabled: yes
   ```
3. При ротации ключей — rolling‑deploy контейнера и обновление peer‑секций.

## 9. Мониторинг и алёртинг
| Метрика | Где снимать | Как алертить |
|---------|-------------|--------------|
| Последнее рукопожатие peer (сек.) | wireguard_exporter / `wg` exporter | >300 сек без рукопожатия |
| `wg_rx_bytes` / `wg_tx_bytes` | node_exporter / wireguard_exporter | 0 байт >5 мин или подозрительные всплески |
| Перезапуски контейнера `wg-client` | cadvisor | >3 за час |
| Состояние killswitch | кастомный probe | Любая утечка трафика вне `wg0` |

## 10. Безопасность
- Ограничить доступ по SSH к серверам WireGuard только с доверенных IP.
- Использовать `iptables -m conntrack --ctstate NEW` для фильтрации исходящих подключений внутри туннеля.
- Включить `fs.ipv4.ip_forward = 1` только на сервере, остальным запрещён форвардинг (и `net.ipv6.conf.all.forwarding=1` при использовании IPv6).
- Обновлять пакеты WireGuard (`apt upgrade`) минимум раз в месяц.

## 11. План пилотного внедрения
| Шаг | Ответственный | Длительность | Критерий готовности |
|-----|---------------|--------------|---------------------|
| Поднять wg-server #1 | DevOps | 0.5d | Пинг с локала, входящее подключение |
| Подготовить Compose с wg-client (stage) | DevOps | 0.5d | Бот работает через VPN, метрики доступны |
| Нагрузочное тестирование | QA | 1d | Нет деградации >5% latency |
| Включить killswitch + тест на утечки | Sec/QA | 0.5d | Нет трафика вне `wg0` |
| Обновить production | DevOps | 0.5d | Метрики в Grafana, Telegram-бот online |
| Анализ, оптимизация | DevOps+Sec | 1d | Отчёт, список улучшений |

## 12. Риски и пути их минимизации
1. Падение `wg-server` → несколько серверов + DNS‑фейловер (короткий TTL) или внешний механизм переключения `Endpoint` по результатам health‑probe. WireGuard не поддерживает список `Endpoint` в конфиге.
2. Утечка ключей → использовать короткий TTL, rotation, 2FA к секрет‑хранилищу.
3. Перегрузка CPU на VPS → enable multiqueue, подобрать MTU, использовать ядра с `wg offload`.
4. Блокировка UDP 51820 провайдером → настроить TCP‑fallback (обёртка `wg-inside-tcp`/UDPTunnel) или использовать порт 443/53.

## 13. Здоровье канала и fallback стратегии
- Добавить probe в `wg-client`: проверять «последнее рукопожатие» и доступность Telegram API. При провале:
  - перезапуск `wg0` (`wg-quick down wg0 && wg-quick up wg0`);
  - переключение endpoint через DNS‑фейловер;
  - при длительной недоступности — временный fallback на прямой egress/прокси (см. план устойчивости сети), чтобы не останавливать обработку контента.
- Экспортировать статус в метрики и троттлить алерты.

## 14. Таймлайн и ресурсы
- Всего ~3 человеко-дня:
  1. Подготовка серверов – 1д
  2. Обновление Compose / тест – 1д
  3. Мониторинг, документация – 1д
- Потребуются 1–2 t3.micro (~5 $/мес) VPS для серверов.

## 15. Изменения в репозитории
- Обновлён файл `doc/WIREGUARD_INTEGRATION_PLAN_RU.md` (настоящий документ).
- Обновить `docker-compose.yml`.
- Добавить `config/wireguard/` и скрипты `healthcheck.sh`, `notify.sh` в `.gitignore`.

---
Документ подготовлен для проекта «War & Peace».