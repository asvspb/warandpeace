#!/bin/sh
set -eu

# Configuration via env or defaults
WG_CONTAINER="${WG_CONTAINER:-wg-client}"
POLL_SECONDS="${WG_WATCHDOG_POLL:-30}"
UNHEALTHY_THRESHOLD="${WG_UNHEALTHY_THRESHOLD:-7}"
DISABLE_MINUTES="${WG_DISABLE_MINUTES:-15}"
LOG_FILE="${WG_WATCHDOG_LOG:-/logs/vpn.log}"

log() {
  ts="$(date +'%d-%m.%y - [%H:%M] -')"
  printf '%s %s\n' "$ts" "$*" | tee -a "$LOG_FILE" >/dev/null
}

consec=0
cycle=0
log "wg-watchdog: start (container=$WG_CONTAINER poll=${POLL_SECONDS}s thr=${UNHEALTHY_THRESHOLD} disable=${DISABLE_MINUTES}m)"

while :; do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$WG_CONTAINER" 2>/dev/null || echo n/a)"
  if [ "$status" = "unhealthy" ]; then
    consec=$((consec+1))
  else
    consec=0
  fi

  if [ "$consec" -ge "$UNHEALTHY_THRESHOLD" ]; then
    cycle=$((cycle+1))
    log "wg-watchdog: threshold reached (consec=$consec). Disabling VPN for ${DISABLE_MINUTES}m (cycle #$cycle)"
    # Try to bring wg down (killswitch off) to allow direct egress
    if docker exec "$WG_CONTAINER" sh -lc 'wg-quick down wg0' >/dev/null 2>&1; then
      log "wg-watchdog: wg-quick down wg0 succeeded"
    else
      log "wg-watchdog: wg-quick down failed, trying container restart"
      docker restart "$WG_CONTAINER" >/dev/null 2>&1 || true
    fi
    # Sleep disable period
    sleep "$((DISABLE_MINUTES*60))"
    # Try to bring wg back up
    if docker exec "$WG_CONTAINER" sh -lc 'wg-quick up wg0' >/dev/null 2>&1; then
      log "wg-watchdog: wg-quick up wg0 succeeded"
    else
      log "wg-watchdog: wg-quick up failed, trying container restart"
      docker restart "$WG_CONTAINER" >/dev/null 2>&1 || true
    fi
    consec=0
  fi

  sleep "$POLL_SECONDS"
done
