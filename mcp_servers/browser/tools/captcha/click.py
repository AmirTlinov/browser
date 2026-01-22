"""
CAPTCHA click operations.

Click blocks in CAPTCHA grid or interactive areas.
"""

from __future__ import annotations

import time
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session
from .analyze import _analyze_captcha_in_session
from .screenshot import _build_grid_map


def click_captcha_blocks(
    config: BrowserConfig, blocks: list[int], delay: float = 0.3, grid_size: int = 0
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
    try:
        with get_session(config) as (session, target):
            used_cache = False

            # Prefer using the recent screenshot-derived grid mapping when available.
            # This makes the CAPTCHA "workbench" stable within a multi-step run:
            # - no drift from re-analysis heuristics
            # - same numbering as the overlay screenshot
            grid_map: dict[int, dict] | None = None
            rows: int | None = None
            cols: int | None = None

            cached: dict[str, Any] | None = None
            try:
                tab_id = session.tab_id
                if isinstance(tab_id, str) and tab_id:
                    cached = session_manager.get_captcha_state(tab_id, max_age_ms=120_000)
            except Exception:
                cached = None

            if isinstance(cached, dict):
                cached_map = cached.get("gridMap")
                try:
                    cached_rows = int(cached.get("rows") or 0)
                    cached_cols = int(cached.get("cols") or 0)
                except Exception:
                    cached_rows = 0
                    cached_cols = 0

                # Enforce caller-specified grid size (if any).
                if grid_size in {3, 4} and (cached_rows != int(grid_size) or cached_cols != int(grid_size)):
                    cached_map = None

                # If scroll changed since the screenshot, cached viewport coords may be wrong.
                if cached_map is not None and isinstance(cached.get("scroll"), dict):
                    try:
                        cur_scroll = session.eval_js("({x: window.scrollX, y: window.scrollY})")
                    except Exception:
                        cur_scroll = None
                    if isinstance(cur_scroll, dict):
                        try:
                            if int(cur_scroll.get("x") or 0) != int(cached["scroll"].get("x") or 0):
                                cached_map = None
                            if int(cur_scroll.get("y") or 0) != int(cached["scroll"].get("y") or 0):
                                cached_map = None
                        except Exception:
                            cached_map = None

                if isinstance(cached_map, dict) and cached_rows > 0 and cached_cols > 0:
                    # keys are ints by construction (_build_grid_map)
                    grid_map = cached_map  # type: ignore[assignment]
                    rows = cached_rows
                    cols = cached_cols
                    used_cache = True

            if grid_map is None or rows is None or cols is None:
                captcha = _analyze_captcha_in_session(session, force_grid_size=int(grid_size or 0))
                if not captcha.get("detected"):
                    raise SmartToolError(
                        tool="click_captcha_blocks",
                        action="find_captcha",
                        reason="No CAPTCHA detected",
                        suggestion="Use captcha(action='screenshot') to confirm the challenge is visible",
                    )

                bounds = captcha.get("gridBounds") or captcha.get("bounds")
                if not isinstance(bounds, dict):
                    raise SmartToolError(
                        tool="click_captcha_blocks",
                        action="get_grid",
                        reason="CAPTCHA bounds are missing",
                        suggestion="Use captcha(action='screenshot') first to capture grid bounds",
                    )

                grid_info = captcha.get("grid") if isinstance(captcha.get("grid"), dict) else None
                if grid_size in {3, 4}:
                    rows = cols = int(grid_size)
                elif grid_info:
                    rows = int(grid_info.get("rows") or 3)
                    cols = int(grid_info.get("cols") or 3)
                else:
                    rows = cols = 3

                grid_map = _build_grid_map(bounds, rows, cols)
            clicked: list[dict[str, Any]] = []
            errors: list[str] = []

            for block_num in blocks:
                block_info = grid_map.get(int(block_num))
                if not block_info:
                    errors.append(f"Block {block_num} not found (valid: 1-{len(grid_map)})")
                    continue

                x = int(block_info["x"])
                y = int(block_info["y"])

                session.click(x, y, button="left", click_count=1)

                clicked.append({"block": int(block_num), "x": x, "y": y})

                if delay > 0 and block_num != blocks[-1]:
                    time.sleep(delay)

            return {
                "result": {
                    "success": len(errors) == 0,
                    "clicked": clicked,
                    "errors": errors if errors else None,
                    "total_clicked": len(clicked),
                    "source": "cache" if used_cache else "analyze",
                },
                "target": target.get("id", ""),
            }

    except SmartToolError:
        raise
    except (OSError, ValueError, KeyError) as e:
        raise SmartToolError(
            tool="click_captcha_blocks",
            action="click",
            reason=str(e),
            suggestion="Ensure CAPTCHA is visible and grid is correct",
        ) from e


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
    try:
        with get_session(config) as (session, target):
            captcha = _analyze_captcha_in_session(session)

            if not captcha.get("detected"):
                raise SmartToolError(
                    tool="click_captcha_area",
                    action="find_captcha",
                    reason="No CAPTCHA detected",
                    suggestion="Navigate to a page with CAPTCHA",
                )

            clickable = captcha.get("clickableAreas", [])

            # If no specific clickable areas, click center of CAPTCHA
            if not clickable:
                bounds = captcha.get("bounds")
                if bounds:
                    clickable = [{"id": 1, "name": "captcha_center", "bounds": bounds}]

            area = next((a for a in clickable if a.get("id") == area_id), None)
            if not area:
                raise SmartToolError(
                    tool="click_captcha_area",
                    action="find_area",
                    reason=f"Area {area_id} not found",
                    suggestion=f"Available areas: {[a.get('id') for a in clickable]}",
                )

            bounds = area.get("bounds", {})
            x = bounds.get("centerX") or (bounds.get("x", 0) + bounds.get("width", 0) / 2)
            y = bounds.get("centerY") or (bounds.get("y", 0) + bounds.get("height", 0) / 2)

            session.send(
                "Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": int(x), "y": int(y), "button": "left", "clickCount": 1},
            )
            session.send(
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": int(x), "y": int(y), "button": "left"},
            )

            return {
                "result": {
                    "success": True,
                    "area": area.get("name", f"area_{area_id}"),
                    "clicked": {"x": int(x), "y": int(y)},
                },
                "target": target.get("id", ""),
            }

    except SmartToolError:
        raise
    except (OSError, ValueError, KeyError) as e:
        raise SmartToolError(
            tool="click_captcha_area",
            action="click",
            reason=str(e),
            suggestion="Try using click coordinates directly with click(x=..., y=...)",
        ) from e
