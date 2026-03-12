#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# monitor.sh  —  Finance Observer liveness monitor
#
# Checks /health and /ping every run.  Designed to be called by cron.
#
# Usage:
#   chmod +x monitor.sh
#   ./monitor.sh                     # one-off check, prints to stdout
#   ./monitor.sh --notify-email      # also sends email on failure
#
# Cron every 5 minutes (pipe stderr too so you see curl errors):
#   */5 * * * * /home/here/Desktop/fx\ alert/currencies/curencies/monitor.sh >> /var/log/fx_monitor.log 2>&1
#
# Cron with email notification:
#   */5 * * * * /home/here/Desktop/fx\ alert/currencies/curencies/monitor.sh --notify-email >> /var/log/fx_monitor.log 2>&1
# ---------------------------------------------------------------------------

APP_HOST="${APP_HOST:-http://localhost:8000}"
NOTIFY_EMAIL="${NOTIFY_EMAIL:-}"          # set via env or edit below
ALERT_TO="${ALERT_TO:-}"                  # recipient email, e.g. you@example.com
LOG_FILE="${LOG_FILE:-}"                  # optional dedicated log file path
TIMEOUT=10                                # curl timeout in seconds

NOTIFY=false
[[ "$1" == "--notify-email" ]] && NOTIFY=true

# --------------------------------------------------------------------------
timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo "[$(timestamp)] $*"; }

send_alert_email() {
    local subject="$1" body="$2"
    if [[ -n "$ALERT_TO" ]]; then
        echo "$body" | mail -s "$subject" "$ALERT_TO" 2>/dev/null \
            && log "Alert email sent to $ALERT_TO"
    fi
}

# --------------------------------------------------------------------------
# 1. Minimal TCP liveness check  (/ping always returns 200 if process alive)
# --------------------------------------------------------------------------
PING_HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time "$TIMEOUT" "${APP_HOST}/ping" 2>/dev/null)

if [[ "$PING_HTTP" != "200" ]]; then
    MSG="CRITICAL: Finance Observer process is DOWN (HTTP ${PING_HTTP:-no-response})"
    log "$MSG"
    if $NOTIFY; then
        send_alert_email "[FX Alert] App DOWN" \
            "$MSG
Host: $APP_HOST
Time: $(timestamp)
Next step: ssh in and check 'systemctl status financeobserver' or 'python run_uvicorn.py'"
    fi
    exit 2
fi

# --------------------------------------------------------------------------
# 2. Full component health check  (/health)
# --------------------------------------------------------------------------
HEALTH_BODY=$(curl -s --max-time "$TIMEOUT" "${APP_HOST}/health" 2>/dev/null)
HEALTH_HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time "$TIMEOUT" "${APP_HOST}/health" 2>/dev/null)

STATUS=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)

OBSERVER=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('observer','?'))" 2>/dev/null)

REDIS=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('redis','?'))" 2>/dev/null)

POSTGRES=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('postgres','?'))" 2>/dev/null)

STREAM_TASK=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('stream_task','?'))" 2>/dev/null)

FAILURES=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('stream_failures','?'))" 2>/dev/null)

UPTIME=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('uptime_seconds','?'))" 2>/dev/null)

LAST_TS=$(echo "$HEALTH_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('checks',{}).get('last_snapshot_ts','none'))" 2>/dev/null)

# --------------------------------------------------------------------------
# 3. Report
# --------------------------------------------------------------------------
log "STATUS=$STATUS | observer=$OBSERVER | redis=$REDIS | postgres=$POSTGRES | stream=$STREAM_TASK | failures=$FAILURES | uptime=${UPTIME}s | last_ts=$LAST_TS"

if [[ "$HEALTH_HTTP" != "200" ]]; then
    MSG="WARNING: Finance Observer is DEGRADED or DOWN (HTTP ${HEALTH_HTTP}, status=${STATUS})"
    log "$MSG"
    log "Full response: $HEALTH_BODY"
    if $NOTIFY; then
        send_alert_email "[FX Alert] App ${STATUS^^}" \
            "$MSG

Component details:
  observer   : $OBSERVER
  redis      : $REDIS
  postgres   : $POSTGRES
  stream task: $STREAM_TASK
  failures   : $FAILURES
  last ts    : $LAST_TS
  uptime     : ${UPTIME}s

Host: $APP_HOST
Time: $(timestamp)"
    fi
    exit 1
fi

log "OK"
exit 0
