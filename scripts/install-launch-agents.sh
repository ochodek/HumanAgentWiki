#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/HumanAgentWiki"
DOMAIN="gui/$(id -u)"
ATTEMPTS=5
LABELS=(mcp web runtime)

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'HumanAgentWiki LaunchAgents require macOS.\n' >&2
  exit 1
fi

mkdir -p "$AGENT_DIR" "$LOG_DIR"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

escaped_project_dir="${PROJECT_DIR//&/\\&}"
escaped_project_dir="${escaped_project_dir//|/\\|}"
escaped_home="${HOME//&/\\&}"
escaped_home="${escaped_home//|/\\|}"

for service in "${LABELS[@]}"; do
  label="com.jarvis.humanagentwiki.$service"
  source_plist="$PROJECT_DIR/ops/$label.plist"
  rendered_plist="$tmp_dir/$label.plist"
  sed \
    -e "s|__HAW_PROJECT_DIR__|$escaped_project_dir|g" \
    -e "s|__HAW_HOME__|$escaped_home|g" \
    "$source_plist" > "$rendered_plist"
  plutil -lint "$rendered_plist" >/dev/null
done

for service in "${LABELS[@]}"; do
  label="com.jarvis.humanagentwiki.$service"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
done

sleep 1

for service in "${LABELS[@]}"; do
  label="com.jarvis.humanagentwiki.$service"
  install -m 0644 "$tmp_dir/$label.plist" "$AGENT_DIR/$label.plist"
done

for service in "${LABELS[@]}"; do
  label="com.jarvis.humanagentwiki.$service"
  attempt=1
  until launchctl bootstrap "$DOMAIN" "$AGENT_DIR/$label.plist"; do
    if (( attempt >= ATTEMPTS )); then
      printf 'Could not load %s after %d attempts.\n' "$label" "$ATTEMPTS" >&2
      exit 1
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
done

launchctl kickstart -k "$DOMAIN/com.jarvis.humanagentwiki.mcp"
launchctl kickstart -k "$DOMAIN/com.jarvis.humanagentwiki.web"
"$PROJECT_DIR/scripts/ensure-runtime.sh"

printf 'HumanAgentWiki LaunchAgents installed and started.\n'
