#!/usr/bin/env python3
"""
Integration test script for browser automation tools.
Tests all MCP tools against a local test page.

Usage:
    python3 tests/integration_test.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_servers.antigravity_browser import smart_tools as cdp
from mcp_servers.antigravity_browser.config import BrowserConfig
from mcp_servers.antigravity_browser.launcher import BrowserLauncher


def test_navigation():
    """Test navigation tools."""
    print("\n=== Testing Navigation ===")
    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)

    # Launch browser
    result = launcher.ensure_running()
    print(f"✓ Browser launch: {result.message}")

    # Test navigation to test page
    test_page = f"file://{Path(__file__).parent.absolute()}/test_page.html"
    result = cdp.navigate_to(config, test_page, wait_load=True)
    print(f"✓ Navigate to test page: {result['url']}")

    # Test about:blank
    result = cdp.navigate_to(config, "about:blank")
    print(f"✓ Navigate to about:blank: {result['url']}")

    # Back to test page
    result = cdp.navigate_to(config, test_page)
    print("✓ Back to test page")

    # Test history navigation
    result = cdp.navigate_to(config, "about:blank")
    result = cdp.go_back(config)
    print(f"✓ Go back: navigated={result.get('navigated', True)}")

    result = cdp.go_forward(config)
    print(f"✓ Go forward: navigated={result.get('navigated', True)}")

    # Test reload
    result = cdp.reload_page(config, ignore_cache=False)
    print(f"✓ Reload page: {result['url']}")


def test_dom_reading():
    """Test DOM reading tools."""
    print("\n=== Testing DOM Reading ===")
    config = BrowserConfig.from_env()

    # Navigate to test page first
    test_page = f"file://{Path(__file__).parent.absolute()}/test_page.html"
    cdp.navigate_to(config, test_page)

    # Get page info
    result = cdp.get_page_info(config)
    print(f"✓ Page info: {result['pageInfo']['url']}")
    print(f"  Viewport: {result['pageInfo']['innerWidth']}x{result['pageInfo']['innerHeight']}")

    # Get DOM
    result = cdp.get_dom_tree(config)
    html_length = len(result['html'])
    print(f"✓ Get DOM: {html_length} bytes")

    # Get element info
    result = cdp.get_element_info("#text-input", config)
    elem = result['element']
    print(f"✓ Get element: {elem['tagName']} at ({elem['bounds']['x']}, {elem['bounds']['y']})")


def test_mouse_interaction():
    """Test mouse interaction tools."""
    print("\n=== Testing Mouse Interaction ===")
    config = BrowserConfig.from_env()

    # Get element position first
    result = cdp.get_element_info("#click-button", config)
    bounds = result['element']['bounds']
    x = bounds['x'] + bounds['width'] / 2
    y = bounds['y'] + bounds['height'] / 2

    # Move mouse
    result = cdp.move_mouse_to(x, y, config)
    print(f"✓ Move mouse to ({x}, {y})")

    # Click at pixel
    result = cdp.click_at_pixel(x, y, config)
    print(f"✓ Click at pixel ({x}, {y})")

    # Hover over element
    result = cdp.hover_element("#hover-target", config)
    print("✓ Hover over #hover-target")

    # Double click
    result = cdp.double_click_at_pixel(x, y, config)
    print(f"✓ Double-click at ({x}, {y})")


def test_keyboard_interaction():
    """Test keyboard interaction tools."""
    print("\n=== Testing Keyboard Interaction ===")
    config = BrowserConfig.from_env()

    # Focus input
    result = cdp.focus_element("#text-input", config)
    print(f"✓ Focus #text-input: {result['focused']}")

    # Type text via JS (browser_type)
    test_text = "Hello World"
    result = cdp.dom_action_fallback(config, {
        "command": "type",
        "selector": "#text-input",
        "text": test_text,
        "clear": True
    })
    print(f"✓ Type text via JS: '{test_text}'")

    # Press keys
    result = cdp.press_key("Tab", config)
    print("✓ Press Tab key")

    result = cdp.press_key("Enter", config)
    print("✓ Press Enter key")

    # Type using keyboard events
    result = cdp.type_text("Test123", config)
    print("✓ Type via keyboard events: 'Test123'")


def test_form_interaction():
    """Test form interaction tools."""
    print("\n=== Testing Form Interaction ===")
    config = BrowserConfig.from_env()

    # Select option by value
    result = cdp.select_option("#dropdown", "option2", config, by="value")
    print(f"✓ Select by value: {result['value']}")

    # Select option by text
    result = cdp.select_option("#dropdown", "Option 3", config, by="text")
    print(f"✓ Select by text: {result['value']}")

    # Clear input
    result = cdp.clear_input("#text-input", config)
    print(f"✓ Clear input: {result['cleared']}")


def test_scroll():
    """Test scroll tools."""
    print("\n=== Testing Scroll ===")
    config = BrowserConfig.from_env()

    # Scroll down
    result = cdp.scroll_page(0, 300, config)
    print("✓ Scroll down 300px")

    # Scroll up
    result = cdp.scroll_page(0, -200, config)
    print("✓ Scroll up 200px")

    # Scroll to element
    result = cdp.scroll_to_element("#scroll-target", config)
    print(f"✓ Scroll to #scroll-target: {result['rect']}")


def test_viewport():
    """Test viewport tools."""
    print("\n=== Testing Viewport ===")
    config = BrowserConfig.from_env()

    # Resize viewport
    result = cdp.resize_viewport(1024, 768, config)
    print(f"✓ Resize viewport: {result['width']}x{result['height']}")

    # Restore
    result = cdp.resize_viewport(1280, 720, config)
    print(f"✓ Restore viewport: {result['width']}x{result['height']}")


def test_wait():
    """Test wait tools."""
    print("\n=== Testing Wait ===")
    config = BrowserConfig.from_env()

    # Wait for element that exists
    result = cdp.wait_for_element("#click-button", config, timeout=5.0)
    print(f"✓ Wait for element: found={result['found']}")

    # Wait for element that doesn't exist (should timeout)
    result = cdp.wait_for_element("#nonexistent", config, timeout=1.0)
    print(f"✓ Wait for nonexistent: found={result['found']}")


def test_screenshot():
    """Test screenshot tool."""
    print("\n=== Testing Screenshot ===")
    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)
    launcher.ensure_running()

    # Take screenshot
    target = cdp._first_page_target(config)
    session = cdp.CdpSession(target["webSocketDebuggerUrl"])
    try:
        session.enable_page()
        data_b64 = session.capture_screenshot()
        import base64
        binary = base64.b64decode(data_b64, validate=False)
        print(f"✓ Screenshot: {len(binary)} bytes")
    finally:
        session.close()


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("Browser Automation Integration Tests")
    print("=" * 60)

    try:
        test_navigation()
        test_dom_reading()
        test_mouse_interaction()
        test_keyboard_interaction()
        test_form_interaction()
        test_scroll()
        test_viewport()
        test_wait()
        test_screenshot()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
