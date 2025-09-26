#!/bin/sh
set -eu

BOT_CONTAINER="${BOT_CONTAINER:-warandpeace-bot}"
POLL_SECONDS="${BOT_WATCHDOG_POLL:-30}"
UNHEALTHY_THRESHOLD="${BOT_UNHEALTHY_THRESHOLD:-4}"
LOG_FILE="${BOT_WATCHDOG_LOG:-/logs/bot.log}"

log() {
  ts="$(date +'%d-%m.%y - [%H:%M] -')"
  printf '%s %s\n' "$ts" "$*" | tee -a "$LOG_FILE" >/dev/null
}

consec=0
log "bot-watchdog: start (container=$BOT_CONTAINER poll=${POLL_SECONDS}s thr=${UNHEALTHY_THRESHOLD})"

while :; do
  # Get docker state and health (may be empty if no healthcheck configured)
  info="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$BOT_CONTAINER" 2>/dev/null || echo 'n/a n/a')"
  state="$(printf '%s' "$info" | awk '{print $1}')"
  health="$(printf '%s' "$info" | awk '{print $2}')"

  if [ "$state" != "running" ]; then
    log "bot-watchdog: state=$state -> restarting $BOT_CONTAINER"
    docker restart "$BOT_CONTAINER" >/dev/null 2>&1 || true
    consec=0
    sleep "$POLL_SECONDS"
    continue
  fi

  case "$health" in
    healthy) consec=0 ;;
    *) consec=$((consec+1)) ;;
  esac

  if [ "$consec" -ge "$UNHEALTHY_THRESHOLD" ]; then
    log "bot-watchdog: health=$health (consec=$consec) -> docker restart $BOT_CONTAINER"
    docker restart "$BOT_CONTAINER" >/dev/null 2>&1 || true
    consec=0
  fi

  sleep "$POLL_SECONDS"
done
