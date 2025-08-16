Последнее обновление: 2025-08-16
Статус: ready

# План внедрения WireGuard VPN в проект «War & Peace» (оптимизированная версия)

## 1. Цели внедрения
1. Сокрытие реального публичного IP-адреса бота Telegram и связанных микросервисов.
2. Шифрование трафика между контейнерами/сервером и внешними API (Telegram, внешние БД, сторонние HTTP-ресурсы). Исключение утечек DNS/трафика в обход туннеля (killswitch).
3. Повышение отказоустойчивости за счёт возможности быстрой смены выходного узла (multi-endpoint через DNS/failover).
4. Централизованное управление сетевыми ACL и логирование сетевой активности.
5. Подготовка инфраструктуры к горизонтальному масштабированию (несколько точек выхода, балансировка).

## 2. Текущее состояние инфраструктуры
- Приложение развёрнуто в контейнере `telegram-bot` (Docker Compose) на VPS.
- Открыт только порт 8000 (Prometheus metrics).
- Другие сервисы отсутствуют или работают в той же Compose-сети.

## 3. Целевая архитектура сети с WireGuard
```
┌───────────────────────────────── VPS ─────────────────────────────────┐
│                                                                       │
│  [docker0]               [wg0] (172.30.0.1/24, fd30:0:0::1/64)        │
│    │                              │                                    │
│    │ docker-compose              ┌┴─────────┐                          │
│    ├──────── telegram-bot -------► wg-client│                          │
│    │                              └─────────┘                          │
│    │                                                             TLS   │
│    └──────── other services …                                         ▲│
│                                                                       ││ WireGuard tunnel (UDP/51820)
└────────────────────────────────────────────────────────────────────────┘│
                                                                          │
                                   ┌────────────── Cloud WG server ───────┘
                                   │  wg-server (public IP, IPv4/IPv6)    │
                                   └───────────────────────────────────────┘
```
- `wg-server` — один или несколько облачных/VPS-узлов, принимающих туннель (желательно IPv4+IPv6).
- `wg-client` — sidecar-контейнер в Compose (linuxserver/wireguard) с включённым NAT и правилами killswitch.
- `telegram-bot` и сервисы направляют исходящий трафик через `wg-client` при помощи `network_mode: "service:wg-client"` (общий netns) либо policy-based routing.
- Метрики на порт 8000 можно оставить доступными с хоста, пробрасывая порт у `wg-client`.

## 4. Подготовительные работы
1. Анализ трафика — определить домены/IP, куда обращается бот (Telegram API, базы, сторонние HTTP). Убедиться, что критичный трафик может проходить через VPN.
2. Выбор хостинга для `wg-server` — минимум два географически распределённых VPS для отказоустойчивости.
3. Оценка MTU/пропускной способности — подобрать оптимальный MTU (обычно 1420) и протестировать.

## 5. Развёртывание WireGuard-сервера
1. Установить WireGuard (`apt install wireguard`) на каждом сервере.
2. Сгенерировать ключи:
   ```bash
   umask 077
   wg genkey | tee server_private.key | wg pubkey > server_public.key
   ```
3. Создать конфиг `/etc/wireguard/wg0.conf`:
   ```ini
   [Interface]
   Address = 172.30.0.1/24, fd30:0:0::1/64
   ListenPort = 51820
   PrivateKey = <server_private_key>
   # Разрешаем форвардинг и NAT (IPv4+IPv6)
   PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE; ip6tables -A FORWARD -i wg0 -j ACCEPT; ip6tables -A FORWARD -o wg0 -j ACCEPT; ip6tables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
   PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE; ip6tables -D FORWARD -i wg0 -j ACCEPT; ip6tables -D FORWARD -o wg0 -j ACCEPT; ip6tables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
   SaveConfig = true
   ```
4. Открыть UDP 51820 в файрволе. Включить IP‑форвардинг:
   ```bash
   sysctl -w net.ipv4.ip_forward=1
   sysctl -w net.ipv6.conf.all.forwarding=1
   ```
5. Запустить сервис `systemctl enable --now wg-quick@wg0`.
6. Повторить для дополнительных серверов (изменив подсеть, например `172.30.1.1/24`, или использовать одну общую подсеть со скриптом динамического назначения IP).

## 6. Настройка WireGuard-клиента в Docker Compose
1. Добавить сервис `wg-client` в `docker-compose.yml`:
   ```yaml
   services:
     wg-client:
       image: linuxserver/wireguard:latest
       container_name: wg-client
       cap_add:
         - NET_ADMIN
         # - SYS_MODULE # только если модуль WireGuard не загружен на хосте
       environment:
         - PUID=1000
         - PGID=1000
         - TZ=Europe/Moscow
       volumes:
         - ./config/wireguard:/config
         - /lib/modules:/lib/modules:ro
       sysctls:
         - net.ipv4.conf.all.src_valid_mark=1
       restart: unless-stopped
       # Пробрасываем порт метрик здесь, если бот разделяет netns wg-client
       ports:
         - "8000:8000"
   ```
2. Создать каталог `config/wireguard/` и положить туда `wg0.conf` клиента (с поддержкой IPv6 и корректным DNS во избежание DNS‑утечек):
   ```ini
   [Interface]
   PrivateKey = <client_private_key>
   Address = 172.30.0.2/24, fd30:0:0::2/64
   DNS = 1.1.1.1, 2606:4700:4700::1111

   [Peer]
   PublicKey = <server_public_key>
   AllowedIPs = 0.0.0.0/0, ::/0
   Endpoint = <wg_server_ip>:51820
   PersistentKeepalive = 25
   ```
3. На сервере добавить пира в `wg0.conf`:
   ```ini
   [Peer]
   PublicKey = <client_public_key>
   AllowedIPs = 172.30.0.2/32, fd30:0:0::2/128
   ```
4. Подключение бота к сети WireGuard — вариант `network_mode: container`:
   ```yaml
   telegram-bot:
     network_mode: "service:wg-client"
     depends_on:
       - wg-client
   ```
   Плюс убрать порт 8000 из `telegram-bot` и пробросить его из `wg-client`.
   Либо создать отдельную пользовательскую сеть и настроить policy‑based routing внутри контейнера (маркировка пакетов и отдельная таблица маршрутов).
5. Перезапуск Compose: `docker compose up -d --build`.

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
- Обновить `docker-compose.yml` (пример в разделе 6).
- Добавить `config/wireguard/` в `.gitignore`.

---
Документ подготовлен для проекта «War & Peace». При необходимости расширяйте план разделами High Availability и автоматическим failover между несколькими выходными узлами (DNS‑фейловер/оператор поверх WireGuard, резервные прокси).