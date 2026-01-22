[LEGEND]

[CONTENT]
# Troubleshooting Guide

## Snap Chromium Issues

**Snap Chromium** has fundamental issues:
1. **Ignores `--user-data-dir`** - forces ~/snap/chromium/ profile
2. **SingletonLock** - blocks parallel instances

### Solution 1: Use Local Chromium (Recommended - No System Installation)

```bash
# Download portable Chromium to project directory
./scripts/install_local_chromium.sh

# It's automatically detected - no configuration needed!
```

**Advantages:**
- ✅ No system-wide installation required
- ✅ No snap issues
- ✅ Portable across machines
- ✅ Self-contained in project (542MB)
- ✅ Works out of the box

### Solution 2: Install System Chromium

#### Quick Fix (Ubuntu/Debian)

```bash
# Remove snap version
sudo snap remove chromium

# Install proper version
sudo apt install chromium-browser

# Set environment variable
export MCP_BROWSER_BINARY=/usr/bin/chromium-browser
```

#### Or Use Install Script

```bash
./scripts/install_chromium.sh
```

### Verification

```bash
# Check which binary will be used
python3 -c "from mcp_servers.browser.config import BrowserConfig; print(BrowserConfig.detect_binary())"

# Should NOT be /snap/bin/chromium
```

---

## Port Already in Use

```
Error: Port 9222 already in use
```

### Solution

```bash
# Find process using port
lsof -i :9222

# Kill it
kill <PID>

# Or use different port
export MCP_BROWSER_PORT=9333
```

---

## Profile Lock Issues

```
Error: Unable to lock profile
```

### Solution

```bash
# Use unique profile
export MCP_BROWSER_PROFILE=~/.mcp/browser-$(date +%s)

# Or clean existing
rm -rf ~/.gemini/browser-profile/SingletonLock
```

---

## Browser Not Opening (Visible Mode)

### Check

```bash
# 1. Browser binary exists
ls -la $(python3 -c "from mcp_servers.browser.config import BrowserConfig; print(BrowserConfig.detect_binary())")

# 2. Display available
echo $DISPLAY

# 3. No X11 forwarding issues
xdpyinfo | grep "name of display"
```

### Solution

```bash
# For headless servers, use headless mode
export MCP_HEADLESS=1

# For desktop, ensure X11
export DISPLAY=:0
```

---

## Performance Issues

### Symptoms
- Slow page loads
- Timeouts
- High CPU usage

### Solutions

```bash
# 1. Use headless mode (faster)
export MCP_HEADLESS=1

# 2. Reduce window size
export MCP_WINDOW_SIZE=800,600

# 3. Increase timeouts
export MCP_HTTP_TIMEOUT=30

# 4. Disable GPU (if needed)
export MCP_BROWSER_FLAGS="--disable-gpu,--disable-software-rasterizer"
```

---

## Screenshots Empty/Black

### Solution

```bash
# Don't use headless for screenshots
export MCP_HEADLESS=0

# Or use proper headless mode
export MCP_HEADLESS=1
# Note: --headless=new (not --headless=old)
```

---

## CDP Connection Lost

```
Error: Inspected target navigated or closed
```

### This is Normal

Can happen during navigation changes (e.g. `navigate(action="back")` / `navigate(action="forward")`). Navigation can invalidate the inspected target.

No action needed - handled automatically.

---

## fetch CORS Errors

```
Error: CORS policy blocked the request
```

### Explanation

`fetch` executes `fetch()` in the page context, so it's subject to CORS policy. This is intentional - it simulates what a user script on the page could do.

### Solutions

1. **Navigate to the same origin first:**
   ```
   navigate(url="https://api.example.com/")
   fetch(url="https://api.example.com/data")
   ```

2. **Use http for simple requests:**
   `http` makes server-side requests without CORS restrictions.

3. **Use cookies tool for authentication:**
   Set cookies via CDP, then navigate to the page.

---

## Quick Diagnostic

```bash
# Check configuration
python3 -c "
from mcp_servers.browser.config import BrowserConfig
c = BrowserConfig.from_env()
print(f'Binary: {c.binary_path}')
print(f'Profile: {c.profile_path}')
print(f'Port: {c.cdp_port}')
"

# Test CDP connection
python3 -c "
from mcp_servers.browser.config import BrowserConfig
from mcp_servers.browser.launcher import BrowserLauncher
config = BrowserConfig.from_env()
launcher = BrowserLauncher(config)
result = launcher.ensure_running()
print(f'Browser: {result.message}')
version = launcher.cdp_version()
print(f'CDP Version: {version}')
"
```

---

## Getting Help

1. Check this guide first
2. Run diagnostics above
3. Check logs in stderr
4. Open issue with:
   - OS and version
   - Browser binary path
   - Full error message
   - Output of diagnostic commands
