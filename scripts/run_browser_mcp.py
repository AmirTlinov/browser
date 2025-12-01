#!/usr/bin/env python3
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

print(
    f"[mcp] binary={os.environ.get('MCP_BROWSER_BINARY', 'auto')} | "
    f"profile={os.environ.get('MCP_BROWSER_PROFILE', '~/.gemini/antigravity-browser-profile')} | "
    f"port={os.environ.get('MCP_BROWSER_PORT', '9222')} | "
    f"allowlist={os.environ.get('MCP_ALLOW_HOSTS', '*')}",
    file=sys.stderr,
)

from mcp_servers.antigravity_browser.server import main  # noqa: E402

if __name__ == "__main__":
    main()
