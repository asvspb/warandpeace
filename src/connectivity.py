# -*- coding: utf-8 -*-
"""
Модуль для управления состоянием соединения с Telegram.

Реализует механизм "предохранителя" (Circuit Breaker) для предотвращения
лавинообразных ошибок при длительной недоступности API Telegram.
"""
import logging
import os
import socket
import time
from typing import Optional, Dict, Any
try:
    # When running as package
    from .metrics import VPN_ACTIVE, DNS_RESOLVE_OK, NETWORK_INFO  # type: ignore
except Exception:
    try:
        # When running as module from /app
        from metrics import VPN_ACTIVE, DNS_RESOLVE_OK, NETWORK_INFO  # type: ignore
    except Exception:
        VPN_ACTIVE = None  # type: ignore
        DNS_RESOLVE_OK = None  # type: ignore
        NETWORK_INFO = None  # type: ignore
from threading import RLock

# --- Состояния предохранителя ---
STATE_CLOSED = "CLOSED"  # Соединение считается стабильным, запросы разрешены.
STATE_OPEN = "OPEN"      # Соединение разорвано, запросы блокируются.
STATE_HALF_OPEN = "HALF_OPEN" # Пробный период, разрешен один запрос для проверки.

logger = logging.getLogger()
_net_state_lock = RLock()
_vpn_last_state: Optional[bool] = None
_vpn_last_ctx: Optional[Dict[str, Optional[str]]] = None

class TelegramCircuitBreaker:
    """
    Отслеживает состояние доступности Telegram API.
    """
    def __init__(self):
        # Загрузка настроек из переменных окружения с разумными дефолтами
        self.failure_threshold = int(os.getenv("TG_CB_FAILURE_THRESHOLD", 5))
        self.failure_window_sec = int(os.getenv("TG_CB_FAILURE_WINDOW_SEC", 60))
        self.open_state_cooldown_sec = int(os.getenv("TG_CB_OPEN_COOLDOWN_SEC", 30))

        self._lock = RLock()
        self.reset()

    def reset(self):
        """Сбрасывает предохранитель в исходное состояние."""
        with self._lock:
            self._state = STATE_CLOSED
            self._failures = []
            self._opened_at = 0
            logger.info("Соединение стабильно, запросы к Telegram разрешены.")

    @property
    def state(self):
        """Возвращает текущее состояние."""
        with self._lock:
            return self._state

    def note_failure(self):
        """
        Регистрирует сбой при вызове API. Если количество сбоев превышает
        порог, предохранитель переходит в состояние OPEN.
        """
        with self._lock:
            if self._state == STATE_OPEN:
                return  # Уже в открытом состоянии, ничего не делаем

            current_time = time.time()
            self._failures.append(current_time)

            # Удаляем старые сбои, которые вышли за пределы временного окна
            window_start_time = current_time - self.failure_window_sec
            self._failures = [t for t in self._failures if t >= window_start_time]

            # Если в окне набралось достаточно сбоев, размыкаем цепь
            if len(self._failures) >= self.failure_threshold:
                self._state = STATE_OPEN
                self._opened_at = current_time
                logger.critical(
                    f"Circuit Breaker перешел в состояние OPEN. "
                    f"Обнаружено {len(self._failures)} сбоев за последние {self.failure_window_sec} сек."
                )

    def note_success(self):
        """
        Регистрирует успешный вызов. Если предохранитель был в состоянии
        OPEN или HALF_OPEN, он сбрасывается в CLOSED.
        """
        with self._lock:
            if self._state != STATE_CLOSED:
                logger.info("Соединение с Telegram восстановлено. Запросы к Telegram снова разрешены.")
                self.reset()

    def is_open(self) -> bool:
        """
        Проверяет, разрешены ли в данный момент вызовы к API.

        Returns:
            True, если вызовы заблокированы (состояние OPEN).
            False, если вызовы разрешены (состояние CLOSED или HALF_OPEN).
        """
        with self._lock:
            if self._state == STATE_CLOSED:
                return False

            if self._state == STATE_OPEN:
                # Проверяем, прошел ли период "остывания"
                if time.time() - self._opened_at >= self.open_state_cooldown_sec:
                    self._state = STATE_HALF_OPEN
                    logger.warning("Circuit Breaker перешел в состояние HALF_OPEN. Будет предпринята пробная попытка.")
                    return False  # Разрешаем один пробный вызов
                else:
                    return True # Все еще "остываем", вызовы блокированы

            # В состоянии HALF_OPEN мы уже разрешили один вызов,
            # поэтому для всех последующих считаем цепь разомкнутой,
            # пока не будет вызван note_success() или note_failure().
            return False


# Глобальный экземпляр предохранителя для всего приложения
circuit_breaker = TelegramCircuitBreaker()


# --- VPN/Network diagnostics ---

def _get_default_route_interface() -> Optional[str]:
    """Parse /proc/net/route to determine default route interface.

    Returns interface name like 'wg0', 'eth0', or None if undetermined.
    """
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as f:
            # Skip header
            _ = next(f, None)
            best_metric = None
            best_iface = None
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 11:
                    # Fallback to whitespace split
                    parts = line.strip().split()
                if len(parts) < 11:
                    continue
                iface, destination_hex, flags_hex, _, _, _, metric_str, *_rest = parts[:11]
                # Default route has destination 00000000
                if destination_hex != "00000000":
                    continue
                try:
                    metric = int(metric_str)
                except Exception:
                    metric = 0
                # Pick lowest metric
                if best_metric is None or metric < best_metric:
                    best_metric = metric
                    best_iface = iface
            return best_iface
    except Exception:
        return None


def _get_public_ip(timeout_sec: float = 3.0) -> Optional[str]:
    """Resolve public IP via external service. Returns None on failure."""
    try:
        # Lazy import to avoid mandatory dependency at import-time
        import requests  # type: ignore
        for url in (
            "https://api.ipify.org",
            "https://ifconfig.me/ip",
            "https://ipv4.icanhazip.com",
        ):
            try:
                resp = requests.get(url, timeout=timeout_sec)
                if resp.ok:
                    ip = resp.text.strip()
                    # Basic validation
                    try:
                        socket.inet_aton(ip)
                        return ip
                    except OSError:
                        continue
            except Exception:
                continue
        return None
    except Exception:
        return None


def _get_egress_local_ip(target_host: str = "1.1.1.1", target_port: int = 80) -> Optional[str]:
    """Determine the local IPv4 address used to reach target.

    Uses a UDP socket trick without sending packets.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            try:
                s.connect((target_host, target_port))
                local_ip = s.getsockname()[0]
                return local_ip
            except Exception:
                return None
    except Exception:
        return None


def detect_network_context() -> Dict[str, Any]:
    """Gather lightweight network/VPN context for logging/metrics."""
    wg0_present = os.path.exists("/sys/class/net/wg0")
    default_iface = _get_default_route_interface()
    public_ip = _get_public_ip()
    egress_local_ip = _get_egress_local_ip()
    # Heuristic: if wg0 exists and either default route is wg0 or
    # the chosen local IP for Internet egress is a typical WG client subnet (10.x/100.64-127.x)
    vpn_active_guess = bool(
        wg0_present
        and (
            default_iface == "wg0"
            or (egress_local_ip and (egress_local_ip.startswith("10.") or egress_local_ip.startswith("100.")))
        )
    )
    return {
        "wg0_present": wg0_present,
        "default_iface": default_iface,
        "public_ip": public_ip,
        "egress_local_ip": egress_local_ip,
        "vpn_active_guess": vpn_active_guess,
    }


def log_network_context(prefix: str = "NET") -> None:
    """Log a concise VPN/network status.

    - Detailed one-line context is logged at DEBUG to avoid INFO noise.
    - INFO is emitted only on VPN state transitions (connect/disconnect).
    """
    ctx = detect_network_context()
    # Export metrics if available
    try:
        if VPN_ACTIVE is not None:
            VPN_ACTIVE.set(1.0 if ctx.get("vpn_active_guess") else 0.0)
        if NETWORK_INFO is not None:
            NETWORK_INFO.labels(
                default_iface=str(ctx.get("default_iface") or "n/a"),
                egress_ip=str(ctx.get("egress_local_ip") or "n/a"),
                public_ip=str(ctx.get("public_ip") or "n/a"),
            ).set(1)
        if DNS_RESOLVE_OK is not None:
            import socket as _s
            for host in ("api.ipify.org", "www.warandpeace.ru", "api.telegram.org"):
                ok = 0.0
                try:
                    _ = _s.getaddrinfo(host, 443, proto=_s.IPPROTO_TCP)
                    ok = 1.0
                except Exception:
                    ok = 0.0
                DNS_RESOLVE_OK.labels(hostname=host).set(ok)
    except Exception:
        pass
    # Emit INFO only on VPN state transitions
    try:
        vpn_active_now = bool(ctx.get("vpn_active_guess"))
        current_ctx = {
            "default_iface": ctx.get("default_iface"),
            "egress_local_ip": ctx.get("egress_local_ip"),
            "public_ip": ctx.get("public_ip"),
        }
        with _net_state_lock:
            global _vpn_last_state, _vpn_last_ctx
            previous = _vpn_last_state
            # Connect/Disconnect events
            if previous is not None and vpn_active_now != previous:
                if vpn_active_now:
                    logger.info(
                        "VPN подключен (iface=%s, egress=%s, public=%s)",
                        current_ctx.get("default_iface"),
                        current_ctx.get("egress_local_ip") or "n/a",
                        current_ctx.get("public_ip") or "n/a",
                    )
                else:
                    logger.info(
                        "VPN отключен (default_iface=%s, egress=%s, public=%s)",
                        current_ctx.get("default_iface"),
                        current_ctx.get("egress_local_ip") or "n/a",
                        current_ctx.get("public_ip") or "n/a",
                    )
            # Restart/route-change event while remaining connected
            elif previous is True and vpn_active_now is True and _vpn_last_ctx is not None:
                if (
                    _vpn_last_ctx.get("default_iface") != current_ctx.get("default_iface")
                    or _vpn_last_ctx.get("egress_local_ip") != current_ctx.get("egress_local_ip")
                    or _vpn_last_ctx.get("public_ip") != current_ctx.get("public_ip")
                ):
                    logger.info(
                        "VPN перезапущен/изменена маршрутизация (iface: %s→%s, egress: %s→%s, public: %s→%s)",
                        _vpn_last_ctx.get("default_iface"),
                        current_ctx.get("default_iface"),
                        _vpn_last_ctx.get("egress_local_ip") or "n/a",
                        current_ctx.get("egress_local_ip") or "n/a",
                        _vpn_last_ctx.get("public_ip") or "n/a",
                        current_ctx.get("public_ip") or "n/a",
                    )
            _vpn_last_state = vpn_active_now
            _vpn_last_ctx = current_ctx
    except Exception:
        # Do not fail the caller because of logging
        pass

    # Always keep a detailed line at DEBUG for diagnostics
    logger.debug(
        "%s: wg0_present=%s; default_iface=%s; egress_ip_local=%s; public_ip=%s; vpn_active=%s",
        prefix,
        ctx.get("wg0_present"),
        ctx.get("default_iface"),
        ctx.get("egress_local_ip") or "n/a",
        ctx.get("public_ip") or "n/a",
        ctx.get("vpn_active_guess"),
    )

