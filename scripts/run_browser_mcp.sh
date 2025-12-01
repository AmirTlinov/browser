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

EXT_DIR="${MCP_EXTENSION_PATH:-$ROOT/vendor/antigravity_extension}"
PROFILE="${MCP_BROWSER_PROFILE:-$HOME/.gemini/antigravity-browser-profile}"
PORT="${MCP_BROWSER_PORT:-9333}"
BINARY="${MCP_BROWSER_BINARY:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || command -v google-chrome-stable || true)}"

# Fresh profile for deterministic extension state. By default мы НЕ сносим профиль,
# чтобы расширение оставалось установленным и extension_* работали и в Chrome, и в Chromium.
if [ "${MCP_BROWSER_PROFILE_RESET:-0}" = "1" ]; then
  rm -rf "$PROFILE"
fi
mkdir -p "$PROFILE"

export MCP_BROWSER_PROFILE="$PROFILE"
export MCP_BROWSER_PORT="$PORT"
export MCP_BROWSER_BINARY="$BINARY"
export MCP_EXTENSION_PATH="$EXT_DIR"
export MCP_EXTENSION_ID="${MCP_EXTENSION_ID:-nfpbnbofdhimjnheaejflfaodcnlbngp}"
export MCP_HEADLESS="${MCP_HEADLESS:-1}"
export MCP_ALLOW_HOSTS="${MCP_ALLOW_HOSTS:-*}"

# Force Chrome to run only with our extension
BASE_FLAGS=("--disable-extensions-except=$EXT_DIR" "--load-extension=$EXT_DIR")
BASE_FLAGS_CSV=$(IFS=,; echo "${BASE_FLAGS[*]}")
if [ -n "${MCP_BROWSER_FLAGS:-}" ]; then
  export MCP_BROWSER_FLAGS="${BASE_FLAGS_CSV},${MCP_BROWSER_FLAGS}"
else
  export MCP_BROWSER_FLAGS="$BASE_FLAGS_CSV"
fi

if [ "${MCP_QUIET:-0}" != "1" ]; then
  echo "[mcp] binary=${MCP_BROWSER_BINARY:-unset}" >&2
  echo "[mcp] profile=${MCP_BROWSER_PROFILE}" >&2
  echo "[mcp] port=${MCP_BROWSER_PORT}" >&2
  echo "[mcp] ext_path=${MCP_EXTENSION_PATH}" >&2
  echo "[mcp] ext_id=${MCP_EXTENSION_ID}" >&2
  echo "[mcp] allowlist=${MCP_ALLOW_HOSTS}" >&2
  echo "[mcp] flags=${MCP_BROWSER_FLAGS}" >&2
  echo "[mcp] starting server..." >&2
fi

python3 -m mcp_servers.antigravity_browser.server
