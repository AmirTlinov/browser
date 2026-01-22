#!/usr/bin/env bash
set -euo pipefail

# Start the user's browser with a local-only CDP debugging port.
#
# Why this exists:
# - In `attach` mode the MCP server will not spawn a browser.
# - You usually want the agent to drive your real profile (tabs/cookies/extensions).
# - CDP must be enabled at browser start via flags; you can't reliably add it to an already running instance.

PORT="${MCP_BROWSER_PORT:-9222}"

BIN="${MCP_BROWSER_BINARY:-}"
if [ -z "${BIN}" ]; then
  BIN="$(
    command -v google-chrome-stable \
      || command -v google-chrome \
      || command -v chromium \
      || command -v chromium-browser \
      || true
  )"
fi

if [ -z "${BIN}" ]; then
  echo "[cdp] No Chrome/Chromium binary found (set MCP_BROWSER_BINARY)." >&2
  exit 2
fi

python3 - <<'PY' "${PORT}" && exit 0
import sys
import json
from urllib.request import urlopen

port = sys.argv[1]
try:
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.3) as resp:
        payload = json.loads(resp.read().decode())
    ua = payload.get("User-Agent", "unknown")
    print(f"[cdp] CDP is already available on 127.0.0.1:{port}")
    print(f"[cdp] User-Agent: {ua}")
except Exception:
    raise SystemExit(1)
PY

echo "[cdp] Launching: ${BIN}" >&2
echo "[cdp] Port: 127.0.0.1:${PORT}" >&2
echo "[cdp] If CDP does not come up, fully close the browser and rerun." >&2

"${BIN}" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="${PORT}" \
  >/dev/null 2>&1 &

sleep 0.25

python3 - <<'PY' "${PORT}"
import sys
import json
from urllib.request import urlopen

port = sys.argv[1]
with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2.0) as resp:
    payload = json.loads(resp.read().decode())
print(f"[cdp] Ready: 127.0.0.1:{port}")
print(f"[cdp] Browser: {payload.get('Browser', 'unknown')}")
PY
