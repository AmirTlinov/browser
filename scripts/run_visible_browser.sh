#!/bin/bash
# Run MCP server with visible browser window for debugging/monitoring

# Set visible mode (default is already 0, but explicit for clarity)
export MCP_HEADLESS=0

# Optional: Set custom window size (default is 1280,900)
# export MCP_WINDOW_SIZE=1920,1080

# Optional: Use specific browser
# export MCP_BROWSER_BINARY=/usr/bin/chromium

# Optional: Custom profile to isolate from main browser
# export MCP_BROWSER_PROFILE=~/.mcp/browser-profile

# Optional: Allow all hosts (for testing)
export MCP_ALLOW_HOSTS="*"

echo "============================================"
echo "Starting MCP Browser Server (Visible Mode)"
echo "============================================"
echo "Browser will open in a visible window"
echo "Press Ctrl+C to stop"
echo ""

cd "$(dirname "$0")/.." || exit 1
python3 -m mcp_servers.antigravity_browser.server
