#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$ROOT/data/outbox"
LOGFILE="$LOGDIR/mcp_startup.log"
mkdir -p "$LOGDIR"

echo "Starting at $(date)" >> "$LOGFILE"
exec 2>>"$LOGFILE"
set -x

# Build PYTHONPATH with vendor + user-site + repo
PY_PATHS=(
  "$ROOT/vendor/python"
  "$HOME/.local/lib/python3.12/site-packages"
  "$ROOT"
)
export PYTHONPATH="$(IFS=:; echo "${PY_PATHS[*]}")"

MODE="${MCP_BROWSER_MODE:-extension}"
PORT="${MCP_BROWSER_PORT:-9222}"

export MCP_BROWSER_MODE="$MODE"
export MCP_BROWSER_PORT="$PORT"
export MCP_ALLOW_HOSTS="${MCP_ALLOW_HOSTS:-*}"
export MCP_AUTO_PORT_FALLBACK="${MCP_AUTO_PORT_FALLBACK:-0}"

if [ "$MODE" = "launch" ]; then
  PROFILE="${MCP_BROWSER_PROFILE:-$HOME/.gemini/browser-profile}"
  BINARY="${MCP_BROWSER_BINARY:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || command -v google-chrome-stable || true)}"

  # Fresh profile for deterministic browser state. By default we do NOT delete it.
  if [ "${MCP_BROWSER_PROFILE_RESET:-0}" = "1" ]; then
    rm -rf "$PROFILE"
  fi
  mkdir -p "$PROFILE"

  export MCP_BROWSER_PROFILE="$PROFILE"
  export MCP_BROWSER_BINARY="$BINARY"
  export MCP_HEADLESS="${MCP_HEADLESS:-1}"
fi

if [ "${MCP_QUIET:-0}" != "1" ]; then
  echo "[mcp] mode=${MCP_BROWSER_MODE}" >&2
  echo "[mcp] port=${MCP_BROWSER_PORT}" >&2
  echo "[mcp] allowlist=${MCP_ALLOW_HOSTS}" >&2
  if [ "${MCP_BROWSER_MODE}" = "launch" ]; then
    echo "[mcp] binary=${MCP_BROWSER_BINARY:-unset}" >&2
    echo "[mcp] profile=${MCP_BROWSER_PROFILE:-unset}" >&2
    echo "[mcp] flags=${MCP_BROWSER_FLAGS}" >&2
    echo "[mcp] headless=${MCP_HEADLESS}" >&2
  fi
  echo "[mcp] starting server..." >&2
fi

python3 -m mcp_servers.browser.server
