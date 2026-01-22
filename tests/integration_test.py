#!/usr/bin/env python3
"""
Integration test script for browser automation tools.

This is intentionally a *manual* integration script (not collected by pytest),
useful when validating against a real Chrome/Chromium instance.

Usage:
    python3 tests/integration_test.py
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

# Add repo root to path for local runs without install.
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_servers.browser import tools as cdp  # noqa: E402
from mcp_servers.browser.config import BrowserConfig  # noqa: E402
from mcp_servers.browser.launcher import BrowserLauncher  # noqa: E402


def _test_page_url() -> str:
    return f"file://{(Path(__file__).parent / 'test_page.html').absolute()}"


def main() -> int:
    print("=" * 60)
    print("Browser Automation Integration Test")
    print("=" * 60)

    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)

    result = launcher.ensure_running()
    print(f"✓ Browser: {result.message}")

    url = _test_page_url()
    nav = cdp.navigate_to(config, url)
    print(f"✓ Navigate: {nav.get('url')}")

    info = cdp.get_page_info(config)
    print(f"✓ Title: {info.get('pageInfo', {}).get('title')}")

    dom = cdp.get_dom(config, max_chars=2000)
    print(f"✓ DOM bytes: {len(dom.get('html', ''))} (truncated={dom.get('truncated')})")

    elem = cdp.get_element_info(config, "#text-input")
    print(f"✓ Element: {elem.get('element', {}).get('tagName')} selector=#text-input")

    cdp.focus_element(config, "#text-input")
    cdp.dom_action_type(config, selector="#text-input", text="Hello", clear=True)
    print("✓ Type: #text-input")

    cdp.dom_action_click(config, "#click-button")
    print("✓ Click: #click-button")

    cdp.scroll_page(config, 0, 300)
    print("✓ Scroll: +300px")

    cdp.hover_element(config, "#hover-target")
    print("✓ Hover: #hover-target")

    cdp.select_option(config, "#dropdown", "option2", by="value")
    print("✓ Select: #dropdown -> option2")

    cdp.wait_for_element(config, "#click-button", timeout=2.0)
    print("✓ Wait: #click-button")

    shot = cdp.screenshot(config)
    png = base64.b64decode(shot["content_b64"], validate=False)
    out = Path(__file__).parent / "integration_screenshot.png"
    out.write_bytes(png)
    print(f"✓ Screenshot: {out} ({len(png)} bytes)")

    print("\n✅ Integration test completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
