#!/usr/bin/env python3
"""
Demo: AI controlling visible browser window
Shows step-by-step what AI is doing in the browser
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_servers.antigravity_browser import cdp
from mcp_servers.antigravity_browser.config import BrowserConfig
from mcp_servers.antigravity_browser.launcher import BrowserLauncher


def demo(interactive=True, delay=2.0):
    """Run demo with visible browser.

    Args:
        interactive: If True, waits for Enter key between steps. If False, runs automatically.
        delay: Seconds to wait between steps in auto mode.
    """
    def wait_step(message):
        """Wait for user input or auto-delay."""
        if interactive:
            input(message)
        else:
            print(message.replace("Press Enter to ", ""))
            time.sleep(delay)

    print("=" * 60)
    print("AI Browser Automation Demo")
    print("=" * 60)
    if interactive:
        print("\nYou will see the browser window and AI actions in real-time")
        print("Press Enter to continue through each step...")
    else:
        print("\nRunning in automatic mode (no manual input required)")
        print(f"Delay between steps: {delay}s")
    print()

    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)

    # Step 1: Launch browser
    wait_step("Press Enter to launch browser...")
    result = launcher.ensure_running()
    print(f"✓ {result.message}")
    time.sleep(1)

    # Step 2: Navigate to test page
    wait_step("\nPress Enter to open test page...")
    test_page = f"file://{Path(__file__).parent.absolute()}/test_page.html"
    cdp.navigate_to(test_page, config)
    print(f"✓ Navigated to: {test_page}")
    time.sleep(1)

    # Step 3: Get page info
    wait_step("\nPress Enter to inspect page info...")
    info = cdp.get_page_info(config)
    print(f"✓ Page title: {info['pageInfo']['title']}")
    print(f"  Viewport: {info['pageInfo']['innerWidth']}x{info['pageInfo']['innerHeight']}")
    time.sleep(1)

    # Step 4: Type in input
    wait_step("\nPress Enter to type text in input field...")
    cdp.focus_element("#text-input", config)
    time.sleep(0.5)
    cdp.dom_action_fallback(config, {
        "command": "type",
        "selector": "#text-input",
        "text": "Hello from AI! 🤖",
        "clear": True
    })
    print("✓ Typed text: 'Hello from AI! 🤖'")
    time.sleep(1)

    # Step 5: Click button
    wait_step("\nPress Enter to click button...")
    result = cdp.dom_action_fallback(config, {
        "command": "click",
        "selector": "#click-button"
    })
    print("✓ Clicked button")
    time.sleep(1)

    # Step 6: Scroll down
    wait_step("\nPress Enter to scroll down...")
    cdp.scroll_page(0, 500, config)
    print("✓ Scrolled down 500px")
    time.sleep(1)

    # Step 7: Hover over element
    wait_step("\nPress Enter to hover over element...")
    cdp.hover_element("#hover-target", config)
    print("✓ Hovering over hover target (watch the color change!)")
    time.sleep(2)

    # Step 8: Select option
    wait_step("\nPress Enter to select dropdown option...")
    cdp.scroll_page(0, -500, config)  # Scroll back up
    time.sleep(0.5)
    cdp.select_option("#dropdown", "option3", config, by="value")
    print("✓ Selected 'Option 3' in dropdown")
    time.sleep(1)

    # Step 9: Take screenshot
    wait_step("\nPress Enter to take screenshot...")
    target = cdp._first_page_target(config)
    session = cdp.CdpSession(target["webSocketDebuggerUrl"])
    try:
        session.enable_page()
        data_b64 = session.capture_screenshot()
        import base64
        binary = base64.b64decode(data_b64, validate=False)
        screenshot_path = Path(__file__).parent / "demo_screenshot.png"
        screenshot_path.write_bytes(binary)
        print(f"✓ Screenshot saved: {screenshot_path}")
        print(f"  Size: {len(binary)} bytes")
    finally:
        session.close()
    time.sleep(1)

    print("\n" + "=" * 60)
    print("Demo complete! Browser window remains open.")
    print("You can:")
    print("  - Interact with the page manually")
    print("  - Close the browser when done")
    print("  - Re-run this demo: python3 tests/demo_visible.py")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Browser automation demo")
    parser.add_argument("--auto", action="store_true", help="Run automatically without user input")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between steps in auto mode (default: 2.0s)")
    args = parser.parse_args()

    try:
        demo(interactive=not args.auto, delay=args.delay)
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Demo error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
