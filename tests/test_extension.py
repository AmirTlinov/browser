#!/usr/bin/env python3
"""Test CDP cookie and fetch functionality (replaces old extension tests)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_servers.antigravity_browser import smart_tools as cdp
from mcp_servers.antigravity_browser.config import BrowserConfig
from mcp_servers.antigravity_browser.launcher import BrowserLauncher


def test_cdp_cookies():
    """Test CDP cookie operations."""
    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)

    print(f"Browser binary: {config.binary_path}")

    # Launch browser
    result = launcher.ensure_running()
    print(f"Launch result: {result.message}")

    # Navigate to a test page first
    test_url = "https://httpbin.org/get"
    print(f"\nNavigating to {test_url}")
    cdp.navigate_to(config, test_url)

    # Test set_cookie
    print("\n--- Testing set_cookie ---")
    result = cdp.set_cookie(
        name="test_cookie",
        value="test_value_123",
        domain="httpbin.org",
        config=config,
        path="/",
        secure=False,
        http_only=False,
        same_site="Lax",
    )
    print(f"set_cookie result: {result}")

    # Test get_all_cookies
    print("\n--- Testing get_all_cookies ---")
    result = cdp.get_all_cookies(config, urls=["https://httpbin.org/"])
    print(f"get_all_cookies result: {len(result.get('cookies', []))} cookies")
    for cookie in result.get("cookies", []):
        print(f"  - {cookie['name']}={cookie['value'][:20]}...")

    # Test set_cookies_batch
    print("\n--- Testing set_cookies_batch ---")
    batch_cookies = [
        {"name": "batch_cookie_1", "value": "batch_value_1", "domain": "httpbin.org"},
        {"name": "batch_cookie_2", "value": "batch_value_2", "domain": "httpbin.org"},
    ]
    result = cdp.set_cookies_batch(batch_cookies, config)
    print(f"set_cookies_batch result: {result}")

    # Verify batch cookies
    result = cdp.get_all_cookies(config, urls=["https://httpbin.org/"])
    print(f"After batch: {len(result.get('cookies', []))} cookies")

    # Test delete_cookie
    print("\n--- Testing delete_cookie ---")
    result = cdp.delete_cookie(name="test_cookie", config=config, domain="httpbin.org")
    print(f"delete_cookie result: {result}")

    # Verify deletion
    result = cdp.get_all_cookies(config, urls=["https://httpbin.org/"])
    cookie_names = [c["name"] for c in result.get("cookies", [])]
    if "test_cookie" not in cookie_names:
        print("Cookie deleted successfully")
    else:
        print("Warning: cookie still exists")

    print("\nCookie tests completed.")
    return True


def test_browser_fetch():
    """Test browser_fetch functionality."""
    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)

    # Ensure browser is running
    launcher.ensure_running()

    # Navigate to httpbin for testing
    print("\n--- Testing browser_fetch ---")
    cdp.navigate_to(config, "https://httpbin.org/")

    # Test GET request
    print("\nTesting GET request...")
    result = cdp.browser_fetch("https://httpbin.org/get", config)
    print(f"GET result: ok={result.get('ok')}, status={result.get('status')}")
    if result.get("ok"):
        print("GET request successful")
    else:
        print(f"GET request failed: {result.get('error', 'unknown error')}")

    # Test POST request
    print("\nTesting POST request...")
    result = cdp.browser_fetch(
        "https://httpbin.org/post",
        config,
        method="POST",
        headers={"Content-Type": "application/json"},
        body='{"test": "data"}',
    )
    print(f"POST result: ok={result.get('ok')}, status={result.get('status')}")

    # Test with custom headers
    print("\nTesting custom headers...")
    result = cdp.browser_fetch(
        "https://httpbin.org/headers",
        config,
        headers={"X-Custom-Header": "test-value"},
    )
    print(f"Headers result: ok={result.get('ok')}")

    print("\nbrowser_fetch tests completed.")
    return True


if __name__ == "__main__":
    try:
        test_cdp_cookies()
        test_browser_fetch()
        print("\n All tests passed!")
        sys.exit(0)
    except Exception as e:
        print(f"\n Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
