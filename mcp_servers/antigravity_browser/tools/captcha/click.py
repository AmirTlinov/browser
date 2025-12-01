"""
CAPTCHA click operations.

Click blocks in CAPTCHA grid or interactive areas.
"""
from __future__ import annotations

import time
from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError
from ..base import get_session as _get_session
from .analyze import analyze_captcha
from .screenshot import get_captcha_screenshot


def click_captcha_blocks(
    config: BrowserConfig,
    blocks: list[int],
    delay: float = 0.3,
    grid_size: int = 0
) -> dict[str, Any]:
    """
    Click specific blocks in a CAPTCHA grid by their numbers.

    Args:
        config: Browser configuration
        blocks: List of block numbers to click (1-indexed, left-to-right, top-to-bottom)
        delay: Delay between clicks in seconds (default: 0.3)
        grid_size: Force grid size (3 for 3x3, 4 for 4x4). Default: 0 = auto-detect.

    Returns:
        Dictionary containing:
        - result: Click results with success status, clicked blocks, errors
        - target: Target ID

    Example: click_captcha_blocks([1, 4, 7, 9]) clicks blocks 1, 4, 7, 9

    Block numbering for 3x3 grid:
    [1] [2] [3]
    [4] [5] [6]
    [7] [8] [9]

    Block numbering for 4x4 grid:
    [1]  [2]  [3]  [4]
    [5]  [6]  [7]  [8]
    [9]  [10] [11] [12]
    [13] [14] [15] [16]
    """
    session, target = _get_session(config)
    try:
        # Get CAPTCHA info and grid, passing grid_size for forced override
        screenshot_result = get_captcha_screenshot(config, draw_grid=False, grid_size=grid_size)

        if "error" in screenshot_result:
            raise SmartToolError(
                tool="click_captcha_blocks",
                action="find_captcha",
                reason=screenshot_result["error"],
                suggestion=screenshot_result.get("suggestion", "")
            )

        grid = screenshot_result.get("grid")
        if not grid or not grid.get("blocks"):
            raise SmartToolError(
                tool="click_captcha_blocks",
                action="get_grid",
                reason="Could not determine CAPTCHA grid",
                suggestion="Use get_captcha_screenshot() first to see the grid"
            )

        grid_blocks = grid["blocks"]
        clicked = []
        errors = []

        for block_num in blocks:
            block_info = grid_blocks.get(block_num)
            if not block_info:
                errors.append(f"Block {block_num} not found (valid: 1-{len(grid_blocks)})")
                continue

            x = block_info["x"]
            y = block_info["y"]

            # Click the block
            session.send("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1
            })
            session.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left"
            })

            clicked.append({
                "block": block_num,
                "x": x,
                "y": y
            })

            if delay > 0 and block_num != blocks[-1]:
                time.sleep(delay)

        return {
            "result": {
                "success": len(errors) == 0,
                "clicked": clicked,
                "errors": errors if errors else None,
                "total_clicked": len(clicked)
            },
            "target": target.get("id", "")
        }

    except SmartToolError:
        raise
    except (OSError, ValueError, KeyError) as e:
        raise SmartToolError(
            tool="click_captcha_blocks",
            action="click",
            reason=str(e),
            suggestion="Ensure CAPTCHA is visible and grid is correct"
        ) from e
    finally:
        session.close()


def click_captcha_area(config: BrowserConfig, area_id: int = 1) -> dict[str, Any]:
    """
    Click a specific CAPTCHA interactive area (checkbox, button, etc.).

    Args:
        config: Browser configuration
        area_id: Area ID from analyze_captcha() clickableAreas (default: 1)

    Returns:
        Dictionary containing:
        - result: Click result with success status, area name, clicked coordinates
        - target: Target ID

    Use for:
    - reCAPTCHA checkbox
    - Turnstile checkbox
    - Submit/Verify buttons
    """
    session, target = _get_session(config)
    try:
        analysis_result = analyze_captcha(config)
        captcha = analysis_result.get("captcha", {})

        if not captcha.get("detected"):
            raise SmartToolError(
                tool="click_captcha_area",
                action="find_captcha",
                reason="No CAPTCHA detected",
                suggestion="Navigate to a page with CAPTCHA"
            )

        clickable = captcha.get("clickableAreas", [])

        # If no specific clickable areas, click center of CAPTCHA
        if not clickable:
            bounds = captcha.get("bounds")
            if bounds:
                clickable = [{
                    "id": 1,
                    "name": "captcha_center",
                    "bounds": bounds
                }]

        area = next((a for a in clickable if a.get("id") == area_id), None)
        if not area:
            raise SmartToolError(
                tool="click_captcha_area",
                action="find_area",
                reason=f"Area {area_id} not found",
                suggestion=f"Available areas: {[a.get('id') for a in clickable]}"
            )

        bounds = area.get("bounds", {})
        x = bounds.get("centerX") or (bounds.get("x", 0) + bounds.get("width", 0) / 2)
        y = bounds.get("centerY") or (bounds.get("y", 0) + bounds.get("height", 0) / 2)

        # Click
        session.send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": int(x),
            "y": int(y),
            "button": "left",
            "clickCount": 1
        })
        session.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": int(x),
            "y": int(y),
            "button": "left"
        })

        return {
            "result": {
                "success": True,
                "area": area.get("name", f"area_{area_id}"),
                "clicked": {"x": int(x), "y": int(y)}
            },
            "target": target.get("id", "")
        }

    except SmartToolError:
        raise
    except (OSError, ValueError, KeyError) as e:
        raise SmartToolError(
            tool="click_captcha_area",
            action="click",
            reason=str(e),
            suggestion="Try using click coordinates directly with browser_click_pixel"
        ) from e
    finally:
        session.close()
