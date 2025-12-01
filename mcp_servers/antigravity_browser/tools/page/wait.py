"""
Smart waiting for browser conditions.

Provides wait_for function for navigation, load, text, element presence.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session


def wait_for(
    config: BrowserConfig, condition: str, timeout: float = 10.0, text: str | None = None, selector: str | None = None
) -> dict[str, Any]:
    """
    Wait for a condition before proceeding.

    Args:
        config: Browser configuration
        condition: What to wait for:
            - "navigation": Page URL change
            - "load": Page fully loaded
            - "text": Specific text appears on page
            - "element": Element matching selector appears
            - "network_idle": No network activity for 500ms
        timeout: Maximum wait time in seconds
        text: Text to wait for (when condition="text")
        selector: CSS selector (when condition="element")

    Returns:
        Dictionary with success status, elapsed time, and condition details
    """
    valid_conditions = ["navigation", "load", "text", "element", "network_idle"]
    if condition not in valid_conditions:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason=f"Invalid condition: {condition}",
            suggestion=f"Use one of: {', '.join(valid_conditions)}",
        )

    if condition == "text" and not text:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason="text parameter required for condition='text'",
            suggestion="Provide text='expected text'",
        )

    if condition == "element" and not selector:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason="selector parameter required for condition='element'",
            suggestion="Provide selector='css selector'",
        )

    with get_session(config) as (session, target):
        start_time = time.time()
        start_url = session.eval_js("window.location.href")

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time

            result = _check_condition(session, target, condition, elapsed, start_url, text, selector)
            if result:
                return result

            time.sleep(0.15)

        return {
            "success": False,
            "condition": condition,
            "timeout": timeout,
            "elapsed": round(time.time() - start_time, 2),
            "suggestion": f"Condition '{condition}' not met within {timeout}s",
            "target": target["id"],
        }


def _check_condition(
    session: Any,
    target: dict[str, Any],
    condition: str,
    elapsed: float,
    start_url: str | None,
    text: str | None,
    selector: str | None,
) -> dict[str, Any] | None:
    """Check a single wait condition. Returns result dict if met, None otherwise."""
    if condition == "navigation":
        current_url = session.eval_js("window.location.href")
        if current_url != start_url:
            return {
                "success": True,
                "condition": condition,
                "elapsed": round(elapsed, 2),
                "old_url": start_url,
                "new_url": current_url,
                "target": target["id"],
            }

    elif condition == "load":
        ready_state = session.eval_js("document.readyState")
        if ready_state == "complete":
            return {"success": True, "condition": condition, "elapsed": round(elapsed, 2), "target": target["id"]}

    elif condition == "text" and text:
        found = session.eval_js(f"document.body.innerText.includes({json.dumps(text)})")
        if found:
            return {
                "success": True,
                "condition": condition,
                "text": text,
                "elapsed": round(elapsed, 2),
                "target": target["id"],
            }

    elif condition == "element" and selector:
        js = f"document.querySelector({json.dumps(selector)}) !== null"
        found = session.eval_js(js)
        if found:
            return {
                "success": True,
                "condition": condition,
                "selector": selector,
                "elapsed": round(elapsed, 2),
                "target": target["id"],
            }

    elif condition == "network_idle":
        js = """
        (() => {
            if (!window._networkIdleTracker) {
                window._networkIdleTracker = { count: 0, lastActivity: Date.now() };
                const observer = new PerformanceObserver((list) => {
                    window._networkIdleTracker.count++;
                    window._networkIdleTracker.lastActivity = Date.now();
                });
                observer.observe({ entryTypes: ['resource'] });
            }
            return Date.now() - window._networkIdleTracker.lastActivity > 500;
        })()
        """
        is_idle = session.eval_js(js)
        if is_idle:
            return {"success": True, "condition": condition, "elapsed": round(elapsed, 2), "target": target["id"]}

    return None
