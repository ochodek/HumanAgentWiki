#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HAW_PROJECT_DIR:-/Users/jarvis/humanagentwiki}"
COLIMA_BIN="${COLIMA_BIN:-/opt/homebrew/bin/colima}"
DOCKER_BIN="${DOCKER_BIN:-/opt/homebrew/bin/docker}"
LAUNCHCTL_BIN="${LAUNCHCTL_BIN:-/bin/launchctl}"
NC_BIN="${NC_BIN:-/usr/bin/nc}"
SLEEP_BIN="${SLEEP_BIN:-/bin/sleep}"
COLIMA_LABEL="${COLIMA_LABEL:-homebrew.mxcl.colima}"
MCP_LABEL="${MCP_LABEL:-com.jarvis.humanagentwiki.mcp}"
COLIMA_PLIST="${COLIMA_PLIST:-/Users/jarvis/Library/LaunchAgents/homebrew.mxcl.colima.plist}"
ATTEMPTS="${HAW_RUNTIME_ATTEMPTS:-30}"
INTERVAL="${HAW_RUNTIME_INTERVAL_SECONDS:-2}"
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

if ! wait_for_colima; then
  log "Colima is unavailable; clearing stale runtime state."
  "$LAUNCHCTL_BIN" bootout "$DOMAIN/$COLIMA_LABEL" >/dev/null 2>&1 || true
  "$COLIMA_BIN" stop --force >/dev/null 2>&1 || true
  "$LAUNCHCTL_BIN" bootstrap "$DOMAIN" "$COLIMA_PLIST"
  "$LAUNCHCTL_BIN" kickstart "$DOMAIN/$COLIMA_LABEL"
  wait_for_colima || {
    log "Colima did not become ready within the configured timeout."
    exit 1
  }
fi

"$DOCKER_BIN" info >/dev/null
cd "$PROJECT_DIR"
"$DOCKER_BIN" compose up -d db >/dev/null
wait_for_database || {
  log "HumanAgentWiki PostgreSQL did not become ready within the configured timeout."
  exit 1
}

if ! "$NC_BIN" -z 127.0.0.1 8802 >/dev/null 2>&1; then
  log "HumanAgentWiki MCP is unavailable; restarting its LaunchAgent."
  "$LAUNCHCTL_BIN" kickstart -k "$DOMAIN/$MCP_LABEL"
fi

log "HumanAgentWiki runtime is healthy."
