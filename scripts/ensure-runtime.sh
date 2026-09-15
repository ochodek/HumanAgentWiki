#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HAW_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COLIMA_BIN="${COLIMA_BIN:-/opt/homebrew/bin/colima}"
DOCKER_BIN="${DOCKER_BIN:-/opt/homebrew/bin/docker}"
LAUNCHCTL_BIN="${LAUNCHCTL_BIN:-/bin/launchctl}"
NC_BIN="${NC_BIN:-/usr/bin/nc}"
CURL_BIN="${CURL_BIN:-/usr/bin/curl}"
SLEEP_BIN="${SLEEP_BIN:-/bin/sleep}"
COLIMA_LABEL="${COLIMA_LABEL:-homebrew.mxcl.colima}"
MCP_LABEL="${MCP_LABEL:-com.jarvis.humanagentwiki.mcp}"
WEB_LABEL="${WEB_LABEL:-com.jarvis.humanagentwiki.web}"
COLIMA_PLIST="${COLIMA_PLIST:-$HOME/Library/LaunchAgents/homebrew.mxcl.colima.plist}"
ATTEMPTS="${HAW_RUNTIME_ATTEMPTS:-30}"
INTERVAL="${HAW_RUNTIME_INTERVAL_SECONDS:-2}"
RUNTIME_SERVICE_MODE="${HAW_RUNTIME_SERVICE_MODE:-gui}"
DOMAIN="gui/$(/usr/bin/id -u)"

log() {
  printf '%s %s\n' "$(/bin/date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

wait_for_colima() {
  local attempt=1
  while (( attempt <= ATTEMPTS )); do
    if "$COLIMA_BIN" status >/dev/null 2>&1; then
      return 0
    fi
    "$SLEEP_BIN" "$INTERVAL"
    attempt=$((attempt + 1))
  done
  return 1
}

wait_for_docker() {
  local attempt=1
  while (( attempt <= ATTEMPTS )); do
    if "$DOCKER_BIN" info >/dev/null 2>&1; then
      return 0
    fi
    "$SLEEP_BIN" "$INTERVAL"
    attempt=$((attempt + 1))
  done
  return 1
}

wait_for_database() {
  local attempt=1
  while (( attempt <= ATTEMPTS )); do
    if "$DOCKER_BIN" compose exec -T db pg_isready -U humanagentwiki -d humanagentwiki >/dev/null 2>&1; then
      return 0
    fi
    "$SLEEP_BIN" "$INTERVAL"
    attempt=$((attempt + 1))
  done
  return 1
}

wait_for_port() {
  local port="$1"
  local attempt=1
  while (( attempt <= ATTEMPTS )); do
    if "$NC_BIN" -z 127.0.0.1 "$port" >/dev/null 2>&1; then
      return 0
    fi
    "$SLEEP_BIN" "$INTERVAL"
    attempt=$((attempt + 1))
  done
  return 1
}

wait_for_web() {
  local attempt=1
  while (( attempt <= ATTEMPTS )); do
    if "$CURL_BIN" --fail --silent --show-error --max-time 2 \
      http://127.0.0.1:8808/healthz 2>/dev/null | /usr/bin/grep -q '"status":"ok"'; then
      return 0
    fi
    "$SLEEP_BIN" "$INTERVAL"
    attempt=$((attempt + 1))
  done
  return 1
}

ensure_interface() {
  local label="$1"
  local port="$2"
  local name="$3"

  if wait_for_port "$port"; then
    return 0
  fi

  if [[ "$RUNTIME_SERVICE_MODE" == "system" ]]; then
    log "HumanAgentWiki $name is unavailable; system launchd must restore it."
    return 1
  fi

  log "HumanAgentWiki $name is unavailable; restarting its LaunchAgent."
  "$LAUNCHCTL_BIN" kickstart -k "$DOMAIN/$label"
  wait_for_port "$port" || {
    log "HumanAgentWiki $name did not become ready within the configured timeout."
    exit 1
  }
}

ensure_web() {
  if wait_for_web; then
    return 0
  fi

  if [[ "$RUNTIME_SERVICE_MODE" == "system" ]]; then
    log "HumanAgentWiki web UI is unavailable; system launchd must restore it."
    return 1
  fi

  log "HumanAgentWiki web UI is unavailable; restarting its LaunchAgent."
  "$LAUNCHCTL_BIN" kickstart -k "$DOMAIN/$WEB_LABEL"
  wait_for_web || {
    log "HumanAgentWiki web UI did not become ready within the configured timeout."
    exit 1
  }
}

case "$RUNTIME_SERVICE_MODE" in
  gui|system) ;;
  *)
    log "HAW_RUNTIME_SERVICE_MODE must be either gui or system."
    exit 2
    ;;
esac

if ! wait_for_colima; then
  if [[ "$RUNTIME_SERVICE_MODE" == "system" ]]; then
    log "Colima did not become ready within the configured timeout; system launchd owns recovery."
    exit 1
  fi

  log "Colima is unavailable; requesting a normal LaunchAgent start."
  if ! "$LAUNCHCTL_BIN" kickstart "$DOMAIN/$COLIMA_LABEL"; then
    "$LAUNCHCTL_BIN" bootstrap "$DOMAIN" "$COLIMA_PLIST"
    "$LAUNCHCTL_BIN" kickstart "$DOMAIN/$COLIMA_LABEL"
  fi
  wait_for_colima || {
    log "Colima did not become ready within the configured timeout."
    exit 1
  }
fi

if [[ "$RUNTIME_SERVICE_MODE" == "system" ]]; then
  wait_for_docker || {
    log "Docker did not become ready within the configured timeout; system launchd owns recovery."
    exit 1
  }
elif ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  log "Docker is unavailable while Colima is running; requesting a graceful Colima restart."
  "$COLIMA_BIN" restart >/dev/null 2>&1 || {
    log "Colima rejected the graceful restart request."
    exit 1
  }
  wait_for_colima || {
    log "Colima did not become ready after the graceful restart."
    exit 1
  }
  wait_for_docker || {
    log "Docker did not become ready after the graceful Colima restart."
    exit 1
  }
fi
cd "$PROJECT_DIR"
"$DOCKER_BIN" compose up -d db >/dev/null
wait_for_database || {
  log "HumanAgentWiki PostgreSQL is unhealthy; requesting a volume-preserving container restart."
  "$DOCKER_BIN" compose restart db >/dev/null
  wait_for_database || {
    log "HumanAgentWiki PostgreSQL did not become ready within the configured timeout."
    exit 1
  }
}

ensure_interface "$MCP_LABEL" 8802 "MCP"
ensure_web

log "HumanAgentWiki runtime is healthy."
