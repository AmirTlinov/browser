"""
Batch workflow execution for browser automation.

Execute sequences of browser actions efficiently.
"""
from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session


# ═══════════════════════════════════════════════════════════════════════════════
# Step execution handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _execute_navigate_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute navigation step."""
    from ..navigation import navigate_to

    url = step.get("url")
    if not url:
        raise SmartToolError("workflow", "navigate", "Missing url", "Provide url parameter")
    navigate_to(config, url, wait_load=step.get("wait_load", True))
    return {"success": True, "url": url}


def _execute_click_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute click step."""
    from .click import click_element
    from ..input import dom_action_click

    if step.get("text") or step.get("role") or step.get("near_text"):
        click_result = click_element(
            config,
            text=step.get("text"),
            role=step.get("role"),
            near_text=step.get("near_text"),
            index=step.get("index", 0)
        )
        result = click_result.get("result", {})
        result["success"] = True
        return result
    elif step.get("selector"):
        dom_action_click(config, step["selector"])
        return {"success": True, "selector": step["selector"]}
    else:
        raise SmartToolError("workflow", "click", "No click target", "Provide text, role, or selector")


def _execute_type_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute type step."""
    from ..input import dom_action_type

    selector = step.get("selector")
    text = step.get("text", "")
    if not selector:
        raise SmartToolError("workflow", "type", "Missing selector", "Provide selector parameter")
    dom_action_type(config, selector, text, step.get("clear", True))
    return {"success": True}


def _execute_fill_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute fill form step."""
    from .form import fill_form

    data = step.get("data", {})
    fill_result = fill_form(
        config,
        data=data,
        form_index=step.get("form_index", 0),
        submit=step.get("submit", False)
    )
    result = fill_result.get("result", {})
    result["success"] = result.get("success", True)
    return result


def _execute_search_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute search step."""
    from .search import search_page

    query = step.get("query", "")
    search_result = search_page(config, query, submit=step.get("submit", True))
    result = search_result.get("result", {})
    result["success"] = result.get("success", True)
    return result


def _execute_wait_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute wait step."""
    try:
        from ..page import wait_for
        wait_result = wait_for(
            config,
            condition=step.get("condition", "load"),
            timeout=step.get("timeout", 10),
            text=step.get("text"),
            selector=step.get("selector")
        )
        wait_result["success"] = True
        return wait_result
    except ImportError:
        return {"error": "wait_for not available"}


def _execute_screenshot_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute screenshot step."""
    with get_session(config) as (session, target):
        data_b64 = session.capture_screenshot()
        return {
            "success": True,
            "bytes": len(data_b64) * 3 // 4,
            "screenshot_b64": data_b64
        }


def _execute_extract_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute extract content step."""
    try:
        from ..page import extract_content
        extract_result = extract_content(
            config,
            content_type=step.get("content_type", "main"),
            selector=step.get("selector")
        )
        return {"success": True, "content": extract_result.get("content")}
    except ImportError:
        return {"error": "extract_content not available"}


# Step handler registry
_STEP_HANDLERS: dict[str, Any] = {
    "navigate": _execute_navigate_step,
    "click": _execute_click_step,
    "type": _execute_type_step,
    "fill": _execute_fill_step,
    "search": _execute_search_step,
    "wait": _execute_wait_step,
    "screenshot": _execute_screenshot_step,
    "extract": _execute_extract_step,
}


def _execute_workflow_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute a single workflow step based on action type."""
    action = step.get("action")
    handler = _STEP_HANDLERS.get(action)

    if handler:
        return handler(config, step)
    else:
        return {
            "error": f"Unknown action: {action}",
            "suggestion": f"Supported actions: {', '.join(_STEP_HANDLERS.keys())}"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Main workflow executor
# ═══════════════════════════════════════════════════════════════════════════════


def execute_workflow(
    config: BrowserConfig,
    steps: list[dict[str, Any]],
    include_screenshots: bool = False,
    compact_results: bool = True,
) -> dict[str, Any]:
    """
    Execute a sequence of browser actions as a workflow.

    Allows batching multiple operations for efficiency.
    Each step is a dict with "action" and action-specific params.

    Supported actions:
    - navigate: {"action": "navigate", "url": "https://..."}
    - click: {"action": "click", "text": "Button Text"} or {"action": "click", "selector": "..."}
    - type: {"action": "type", "selector": "...", "text": "..."}
    - fill: {"action": "fill", "data": {...}, "submit": bool}
    - search: {"action": "search", "query": "..."}
    - wait: {"action": "wait", "condition": "...", "timeout": 5}
    - screenshot: {"action": "screenshot"}
    - extract: {"action": "extract", "content_type": "..."}

    Each step can have "continue_on_error": true to continue despite errors.

    Args:
        config: Browser configuration
        steps: List of action steps to execute
        include_screenshots: Include screenshot data in results (default: False)
        compact_results: Return compact results without redundant fields (default: True)

    Returns:
        Summary with workflow status and step results.
    """
    if not steps:
        raise SmartToolError(
            tool="execute_workflow",
            action="validate",
            reason="No steps provided",
            suggestion="Provide a list of action steps"
        )

    results = []

    for i, step in enumerate(steps):
        action = step.get("action")
        step_result: dict[str, Any] = {
            "step": i,
            "action": action,
            "success": False
        }

        try:
            result = _execute_workflow_step(config, step)

            # Remove screenshot data if not requested
            if not include_screenshots and "screenshot_b64" in result:
                del result["screenshot_b64"]

            step_result.update(result)
        except SmartToolError as e:
            step_result["error"] = str(e)
            step_result["suggestion"] = e.suggestion
        except (OSError, ValueError, KeyError, TypeError) as e:
            step_result["error"] = str(e)

        # Compact results - remove success=True (implied by lack of error)
        if compact_results and step_result.get("success") is True:
            step_result.pop("success", None)

        results.append(step_result)

        # Stop on error unless continue_on_error specified
        if step_result.get("error") and not step.get("continue_on_error"):
            break

    succeeded = sum(1 for r in results if not r.get("error"))
    completed = len(results) == len(steps) and succeeded == len(steps)

    return {
        "completed": completed,
        "total": len(steps),
        "executed": len(results),
        "succeeded": succeeded,
        "results": results
    }
