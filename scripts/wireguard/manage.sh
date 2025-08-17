#!/usr/bin/env bash
#
# manage.sh — управляющий скрипт интеграции WireGuard в проект
#
# Возможности:
# - init        — создать шаблон env для WG и подсказать следующий шаг
# - render      — срендерить client wg0.conf из ENV и системных данных
# - render-client — то же, что render
# - render-server — срендерить server wg0.conf из ENV и системных данных
# - configure   — интерактивная настройка клиента (вставьте конфиг; автодетект значений)
# - up          — запустить контейнер wg-client (docker compose up -d wg-client)
# - stop        — остановить контейнер wg-client
# - restart     — перезапустить контейнер wg-client
# - status      — показать статус/health, давность рукопожатия, ip/route
# - logs        — показать логи wg-client (follow)
# - validate    — проверить docker-compose.yml (docker compose config -q)
# - rotate-key  — сгенерировать новый клиентский приватный ключ и обновить wg.env (бэкапит файл)
# - reinstall   — полная переустановка: (опц. rotate-key) -> render -> restart
#
# Где хранить настройки:
# - config/wireguard/wg.env — переменные окружения для генерации конфига клиента
#   (см. config/wireguard/wg.env.example)
#
set -Eeuo pipefail
trap 'echo "[wg-manage] error at line $LINENO" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_DIR="$REPO_ROOT/config/wireguard"
ENV_FILE="$CONFIG_DIR/wg.env"
CLIENT_CONF="$CONFIG_DIR/wg0.conf"
LOG_DIR="$REPO_ROOT/logs"
VPN_LOG="$LOG_DIR/vpn.log"

log_event() {
  mkdir -p "$LOG_DIR"
  local ts msg
  # Desired format example: 17-08.25 - [14:39] -
  # This is local time: DD-MM.YY - [HH:MM] -
  ts="$(date +'%d-%m.%y - [%H:%M] -')"
  msg="$*"
  echo "$ts $msg" | tee -a "$VPN_LOG"
}

usage() {
  cat <<'USAGE'
Usage: scripts/wireguard/manage.sh <command> [options]

Commands:
  init                    Create config/wireguard/wg.env from example (no overwrite)
  render                  Render client wg0.conf from env
  render-client           Render client wg0.conf from env
  render-server           Render server wg0.conf from env
  configure               Interactive setup: paste client config, auto-fill env, render and (re)start
  up                      docker compose up -d wg-client
  stop                    docker compose stop wg-client
  restart                 docker compose restart wg-client
  status                  Show wg-client ps/health and last handshake age
  logs                    docker compose logs -f wg-client
  validate                docker compose config -q
  rotate-key              Generate new WG_CLIENT_PRIVATE_KEY and update wg.env (backup kept)
  reinstall [--rotate]    Stop -> (rotate-key) -> render -> up

Environment file:
  config/wireguard/wg.env — copy from config/wireguard/wg.env.example and fill values (client).
  config/wireguard/wg.server.env — optional server env for render-server.
USAGE
}

ensure_tools() {
  command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
  command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null || {
    echo "docker compose not found" >&2; exit 1;
  }
}

cmd_init() {
  mkdir -p "$CONFIG_DIR"
  mkdir -p "$LOG_DIR"
  local example="$CONFIG_DIR/wg.env.example"
  if [[ ! -f "$example" ]]; then
    cat > "$example" <<'ENV'
# WireGuard client env for rendering config/wireguard/wg0.conf
# Mandatory
WG_CLIENT_PRIVATE_KEY=
WG_SERVER_PUBLIC_KEY=

# One of the following must be set:
# WG_SERVER_ENDPOINT=wg.example.com:51820
# OR explicit IP/port:
# WG_SERVER_IP=1.2.3.4
# WG_SERVER_IPV6=2001:db8::1
# WG_SERVER_PORT=51820

# Optional client params
WG_CLIENT_ADDR_IPV4=10.0.0.2/24
WG_CLIENT_ADDR_IPV6=fd30:0:0::2/64
WG_CLIENT_DNS=1.1.1.1,2606:4700:4700::1111
WG_CLIENT_MTU=1420
ENV
  fi
  if [[ -f "$ENV_FILE" ]]; then
    echo "Already exists: $ENV_FILE"; return 0
  fi
  cp "$example" "$ENV_FILE"
  log_event "vpn:init created $ENV_FILE"
  echo "Edit it and run: scripts/wireguard/manage.sh render && scripts/wireguard/manage.sh up"
}

cmd_render() {
  [[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE. Run 'manage.sh init' first." >&2; exit 2; }
  set -a; source "$ENV_FILE"; set +a
  log_event "vpn:render-client starting"
  # Inline client renderer (was scripts/wireguard/render_client_wg0.sh)
  resolve_endpoint() {
    local endpoint host port v4 v6
    endpoint="$1"
    # normalize scheme and spaces
    endpoint="${endpoint#udp://}"
    endpoint="${endpoint#wireguard://}"
    endpoint="$(echo "$endpoint" | xargs)"
    if [[ "$endpoint" =~ ^\[(.+)\]:(\d+)$ ]]; then
      host="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[2]}"
    elif [[ "$endpoint" =~ ^([^:]+):(\d+)$ ]]; then
      host="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[2]}"
    else
      # Not a host:port — return empties, caller will decide
      echo "" "" ""; return 0
    fi
    v4="$(getent ahostsv4 "$host" 2>/dev/null | awk '{print $1; exit}' || true)"
    v6="$(getent ahostsv6 "$host" 2>/dev/null | awk '{print $1; exit}' || true)"
    echo "$v4" "$v6" "$port"
  }

  : "${WG_CLIENT_PRIVATE_KEY:?WG_CLIENT_PRIVATE_KEY is required}"
  : "${WG_SERVER_PUBLIC_KEY:?WG_SERVER_PUBLIC_KEY is required}"
  WG_CLIENT_ADDR_IPV4="${WG_CLIENT_ADDR_IPV4:-10.0.0.2/24}"
  WG_CLIENT_ADDR_IPV6="${WG_CLIENT_ADDR_IPV6:-}"
  WG_CLIENT_DNS="${WG_CLIENT_DNS:-1.1.1.1,2606:4700:4700::1111}"
  WG_CLIENT_MTU="${WG_CLIENT_MTU:-1420}"

  WG_SERVER_IP="${WG_SERVER_IP:-}"
  WG_SERVER_IPV6="${WG_SERVER_IPV6:-}"
  WG_SERVER_PORT="${WG_SERVER_PORT:-}"
  WG_SERVER_ENDPOINT="${WG_SERVER_ENDPOINT:-}"

  if [[ -n "$WG_SERVER_ENDPOINT" ]]; then
    # Try resolve host:port; if no port given, try to resolve host only
    read -r ep_v4 ep_v6 ep_port < <(resolve_endpoint "$WG_SERVER_ENDPOINT") || true
    if [[ -z "$ep_port" ]]; then
      # Assume endpoint without port; take port from env or default 51820
      ep_port="${WG_SERVER_PORT:-51820}"
      # Extract host part (strip optional brackets)
      host_only="$WG_SERVER_ENDPOINT"
      host_only="${host_only#[}"; host_only="${host_only%]}"
      ep_v4="$(getent ahostsv4 "$host_only" 2>/dev/null | awk '{print $1; exit}' || true)"
      ep_v6="$(getent ahostsv6 "$host_only" 2>/dev/null | awk '{print $1; exit}' || true)"
    fi
    WG_SERVER_PORT="${WG_SERVER_PORT:-$ep_port}"
    if [[ -z "$WG_SERVER_IP" && -n "$ep_v4" ]]; then WG_SERVER_IP="$ep_v4"; fi
    if [[ -z "$WG_SERVER_IPV6" && -n "$ep_v6" ]]; then WG_SERVER_IPV6="$ep_v6"; fi
  fi

  # Default port if still empty
  WG_SERVER_PORT="${WG_SERVER_PORT:-51820}"

  mkdir -p "$CONFIG_DIR"
  local tmp="$CLIENT_CONF.tmp"
  {
    echo "[Interface]"
    if [[ -n "$WG_CLIENT_ADDR_IPV6" ]]; then
      echo "Address = $WG_CLIENT_ADDR_IPV4, $WG_CLIENT_ADDR_IPV6"
    else
      echo "Address = $WG_CLIENT_ADDR_IPV4"
    fi
    echo "PrivateKey = $WG_CLIENT_PRIVATE_KEY"
    echo "MTU = $WG_CLIENT_MTU"
    echo "DNS = ${WG_CLIENT_DNS//,/ , }" | sed 's/ , /, /g'
    if [[ -n "$WG_SERVER_IP" ]]; then
      echo "PostUp = iptables -A OUTPUT -o lo -j ACCEPT; iptables -A OUTPUT -o wg0 -j ACCEPT; iptables -A OUTPUT -p udp -d $WG_SERVER_IP --dport $WG_SERVER_PORT -j ACCEPT; iptables -A OUTPUT -j DROP"
      echo "PostDown = iptables -D OUTPUT -o lo -j ACCEPT; iptables -D OUTPUT -o wg0 -j ACCEPT; iptables -D OUTPUT -p udp -d $WG_SERVER_IP --dport $WG_SERVER_PORT -j ACCEPT; iptables -D OUTPUT -j DROP"
    fi
    if [[ -n "$WG_SERVER_IPV6" ]]; then
      echo "PostUp = ip6tables -A OUTPUT -o lo -j ACCEPT; ip6tables -A OUTPUT -o wg0 -j ACCEPT; ip6tables -A OUTPUT -p udp -d $WG_SERVER_IPV6 --dport $WG_SERVER_PORT -j ACCEPT; ip6tables -A OUTPUT -j DROP"
      echo "PostDown = ip6tables -D OUTPUT -o lo -j ACCEPT; ip6tables -D OUTPUT -o wg0 -j ACCEPT; ip6tables -D OUTPUT -p udp -d $WG_SERVER_IPV6 --dport $WG_SERVER_PORT -j ACCEPT; ip6tables -D OUTPUT -j DROP"
    fi
    echo
    echo "[Peer]"
    echo "PublicKey = $WG_SERVER_PUBLIC_KEY"
    echo "AllowedIPs = 0.0.0.0/0, ::/0"
    if [[ -n "$WG_SERVER_IP" ]]; then
      echo "Endpoint = $WG_SERVER_IP:$WG_SERVER_PORT"
    elif [[ -n "$WG_SERVER_ENDPOINT" ]]; then
      echo "Endpoint = $WG_SERVER_ENDPOINT"
    else
      echo "# Endpoint must be provided via WG_SERVER_IP:WG_SERVER_PORT or WG_SERVER_ENDPOINT" >&2
      exit 1
    fi
    echo "PersistentKeepalive = 25"
  } > "$tmp"
  mv "$tmp" "$CLIENT_CONF"
  log_event "vpn:render-client rendered $CLIENT_CONF (endpoint=${WG_SERVER_IP:-$WG_SERVER_ENDPOINT})"
}

compose() {
  # Prefer docker compose v2
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

cmd_up() { log_event "vpn:up docker compose up -d wg-client"; compose up -d wg-client; }
cmd_stop() { log_event "vpn:stop docker compose stop wg-client"; compose stop wg-client; }
cmd_restart() { log_event "vpn:restart docker compose restart wg-client"; compose restart wg-client; }
cmd_logs() { compose logs -f wg-client; }
cmd_validate() { compose config -q; }

cmd_status() {
  compose ps wg-client || true
  # Health
  local health
  health="$(docker inspect --format '{{.State.Health.Status}}' wg-client 2>/dev/null || true)"
  [[ -n "$health" ]] && echo "Health: $health"
  # Handshake age
  local hs
  hs="$(compose exec wg-client sh -lc 'v=$(wg show wg0 latest-handshakes | awk "{print $2}"); if [ -n "$v" ]; then echo $(( $(date +%s) - v )); fi' 2>/dev/null || true)"
  if [[ -n "$hs" ]]; then
    echo "seconds_since_handshake: $hs"
    log_event "vpn:status health=${health:-n/a} handshake_s=$hs"
  else
    echo "no-handshake"
    log_event "vpn:status health=${health:-n/a} no-handshake"
  fi
}

cmd_rotate_key() {
  [[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE. Run 'manage.sh init' first." >&2; exit 2; }
  command -v wg >/dev/null || { echo "wg not found. Install wireguard-tools." >&2; exit 1; }
  mkdir -p "$CONFIG_DIR/.backup"
  cp "$ENV_FILE" "$CONFIG_DIR/.backup/wg.env.$(date -u +%Y%m%dT%H%M%SZ)"
  local new_priv new_pub
  new_priv="$(wg genkey)"
  new_pub="$(printf "%s" "$new_priv" | wg pubkey)"
  # In-place update WG_CLIENT_PRIVATE_KEY=...
  if grep -q '^WG_CLIENT_PRIVATE_KEY=' "$ENV_FILE"; then
    sed -i "s#^WG_CLIENT_PRIVATE_KEY=.*#WG_CLIENT_PRIVATE_KEY=${new_priv//#/\#}#" "$ENV_FILE"
  else
    echo "WG_CLIENT_PRIVATE_KEY=$new_priv" >> "$ENV_FILE"
  fi
  echo "New client key generated. Public key: $new_pub"
  log_event "vpn:rotate-key new_pub=$new_pub"
  echo "IMPORTANT: Update this public key on the server peer config."
}

cmd_reinstall() {
  local rotate=false
  if [[ "${1:-}" == "--rotate" ]]; then rotate=true; shift; fi
  if $rotate; then cmd_rotate_key; fi
  cmd_stop || true
  cmd_render
  cmd_up
}

cmd_configure() {
  mkdir -p "$CONFIG_DIR" "$LOG_DIR"
  local tmp_conf
  tmp_conf="$(mktemp)"
  echo "Вставьте клиентский конфиг WireGuard (.conf) и завершите Ctrl-D:" >&2
  if ! cat > "$tmp_conf"; then
    echo "Ввод прерван" >&2; rm -f "$tmp_conf"; exit 1
  fi
  # Парсинг значений
  local client_priv addr dns mtu server_pub endpoint psk
  client_priv="$(grep -E '^\s*PrivateKey\s*=\s*' "$tmp_conf" 2>/dev/null | sed -E 's/^\s*PrivateKey\s*=\s*//; s/\s+$//; q' || true)"
  addr="$(grep -E '^\s*Address\s*=\s*' "$tmp_conf" 2>/dev/null | sed -E 's/^\s*Address\s*=\s*//; s/\s+$//; q' || true)"
  dns="$(grep -E '^\s*DNS\s*=\s*' "$tmp_conf" 2>/dev/null | sed -E 's/^\s*DNS\s*=\s*//; s/\s+$//; q' | tr -d ' ' || true)"
  mtu="$(grep -E '^\s*MTU\s*=\s*' "$tmp_conf" 2>/dev/null | sed -E 's/^\s*MTU\s*=\s*//; s/\s+$//; q' || true)"
  server_pub="$(grep -E '^\s*PublicKey\s*=\s*' "$tmp_conf" 2>/dev/null | tail -n1 | sed -E 's/^\s*PublicKey\s*=\s*//; s/\s+$//' || true)"
  endpoint="$(grep -E '^\s*Endpoint\s*=\s*' "$tmp_conf" 2>/dev/null | sed -E 's/^\s*Endpoint\s*=\s*//; s/\s+$//; q' || true)"
  psk="$(grep -E '^\s*PresharedKey\s*=\s*' "$tmp_conf" | sed -E 's/^\s*PresharedKey\s*=\s*//; s/\s+$//; q' || true)"
  rm -f "$tmp_conf"

  # Адреса клиента IPv4/IPv6
  local addr_v4 addr_v6
  IFS=',' read -r addr_v4 addr_v6 <<< "${addr// /}"

  # При отсутствии приватного ключа — сгенерируем
  if [[ -z "$client_priv" ]]; then
    if command -v wg >/dev/null; then
      client_priv="$(wg genkey)"
      echo "Сгенерирован новый приватный ключ клиента." >&2
    else
      echo "Внимание: не найден wg для генерации ключа. Установите wireguard-tools или укажите PrivateKey в конфиге." >&2
    fi
  fi

  # Сохранение wg.env (с бэкапом)
  mkdir -p "$CONFIG_DIR/.backup"
  [[ -f "$ENV_FILE" ]] && cp "$ENV_FILE" "$CONFIG_DIR/.backup/wg.env.$(date -u +%Y%m%dT%H%M%SZ)"
  {
    echo "WG_CLIENT_PRIVATE_KEY=${client_priv}"
    [[ -n "$server_pub" ]] && echo "WG_SERVER_PUBLIC_KEY=${server_pub}"
    if [[ "$endpoint" =~ :[0-9]+$ ]]; then
      echo "WG_SERVER_ENDPOINT=${endpoint}"
    else
      # Разделить host:port, если порт не определён — спросить
      echo "# Укажите порт сервера вручную, пример: WG_SERVER_ENDPOINT=host:51820"
      echo "WG_SERVER_ENDPOINT=${endpoint}"
    fi
    [[ -n "$addr_v4" ]] && echo "WG_CLIENT_ADDR_IPV4=${addr_v4}"
    [[ -n "$addr_v6" ]] && echo "WG_CLIENT_ADDR_IPV6=${addr_v6}"
    [[ -n "$dns" ]] && echo "WG_CLIENT_DNS=${dns}"
    [[ -n "$mtu" ]] && echo "WG_CLIENT_MTU=${mtu}"
    [[ -n "$psk" ]] && echo "# PresharedKey (не используется в рендере по умолчанию): ${psk}"
  } > "$ENV_FILE"

  log_event "vpn:configure updated $ENV_FILE"
  # Рендер и предложение запустить/перезапустить
  cmd_render
  local ans action
  if compose ps -q wg-client >/dev/null 2>&1 && [[ -n "$(compose ps -q wg-client)" ]]; then
    read -r -p "Перезапустить wg-client сейчас? [Y/n] " ans || true
    action="restart"
  else
    read -r -p "Запустить wg-client сейчас? [Y/n] " ans || true
    action="up"
  fi
  if [[ -z "$ans" || "$ans" =~ ^[Yy]$ ]]; then
    if [[ "$action" == "restart" ]]; then cmd_restart; else cmd_up; fi
  else
    echo "Пропуск запуска/перезапуска. Используйте: ./scripts/wireguard/manage.sh $action"
  fi
}

main() {
  ensure_tools
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    init) cmd_init "$@" ;;
    render) cmd_render "$@" ;;
    render-client) cmd_render "$@" ;;
    configure) cmd_configure "$@" ;;
    render-server)
      # Inline server renderer (was scripts/wireguard/render_server_wg0.sh)
      local SERVER_ENV="$CONFIG_DIR/wg.server.env"
      [[ -f "$SERVER_ENV" ]] && { set -a; source "$SERVER_ENV"; set +a; }
      : "${WG_SERVER_PRIVATE_KEY:?WG_SERVER_PRIVATE_KEY is required}"
      : "${WG_CLIENT_PUBLIC_KEY:?WG_CLIENT_PUBLIC_KEY is required}"
      local WG_LISTEN_PORT="${WG_LISTEN_PORT:-51820}"
      local WG_SERVER_ADDR_IPV4="${WG_SERVER_ADDR_IPV4:-10.0.0.1/24}"
      local WG_SERVER_ADDR_IPV6="${WG_SERVER_ADDR_IPV6:-}"
      local WG_CLIENT_ADDR_IPV4="${WG_CLIENT_ADDR_IPV4:-10.0.0.2/32}"
      local WG_CLIENT_ADDR_IPV6="${WG_CLIENT_ADDR_IPV6:-}"
      local WG_EGRESS_INTERFACE="${WG_EGRESS_INTERFACE:-}"
      detect_egress_iface() {
        local iface
        iface="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')"
        if [[ -z "$iface" ]]; then
          iface="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
        fi
        [[ -n "$iface" ]] || { echo "Cannot detect egress interface automatically. Set WG_EGRESS_INTERFACE" >&2; exit 1; }
        echo "$iface"
      }
      if [[ -z "$WG_EGRESS_INTERFACE" ]]; then WG_EGRESS_INTERFACE="$(detect_egress_iface)"; fi
      local OUT_FILE="$CONFIG_DIR/wg0.server.conf" tmp="$CONFIG_DIR/wg0.server.conf.tmp"
      {
        echo "[Interface]"
        if [[ -n "$WG_SERVER_ADDR_IPV6" ]]; then
          echo "Address = $WG_SERVER_ADDR_IPV4, $WG_SERVER_ADDR_IPV6"
        else
          echo "Address = $WG_SERVER_ADDR_IPV4"
        fi
        echo "ListenPort = $WG_LISTEN_PORT"
        echo "PrivateKey = $WG_SERVER_PRIVATE_KEY"
        echo "PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o $WG_EGRESS_INTERFACE -j MASQUERADE; ip6tables -A FORWARD -i wg0 -j ACCEPT; ip6tables -t nat -A POSTROUTING -o $WG_EGRESS_INTERFACE -j MASQUERADE"
        echo "PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o $WG_EGRESS_INTERFACE -j MASQUERADE; ip6tables -D FORWARD -i wg0 -j ACCEPT; ip6tables -t nat -D POSTROUTING -o $WG_EGRESS_INTERFACE -j MASQUERADE"
        echo "SaveConfig = true"
        echo
        echo "[Peer]"
        if [[ -n "$WG_CLIENT_ADDR_IPV6" ]]; then
          echo "PublicKey = $WG_CLIENT_PUBLIC_KEY"
          echo "AllowedIPs = $WG_CLIENT_ADDR_IPV4, $WG_CLIENT_ADDR_IPV6"
        else
          echo "PublicKey = $WG_CLIENT_PUBLIC_KEY"
          echo "AllowedIPs = $WG_CLIENT_ADDR_IPV4"
        fi
      } > "$tmp"
      mv "$tmp" "$OUT_FILE"
      echo "Rendered $OUT_FILE"
    ;;
    up) cmd_up "$@" ;;
    stop) cmd_stop "$@" ;;
    restart) cmd_restart "$@" ;;
    status) cmd_status "$@" ;;
    logs) cmd_logs "$@" ;;
    validate) cmd_validate "$@" ;;
    rotate-key) cmd_rotate_key "$@" ;;
    reinstall) cmd_reinstall "$@" ;;
    -h|--help|help|"") usage ;;
    *) echo "Unknown command: $cmd" >&2; usage; exit 2 ;;
  esac
}

main "$@"
