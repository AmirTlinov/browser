"""
CAPTCHA screenshot with numbered grid overlay.

Captures CAPTCHA area and draws numbered grid for block selection.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import get_session
from .analyze import _analyze_captcha_in_session


def get_captcha_screenshot(
    config: BrowserConfig, draw_grid: bool = True, grid_size: int | None = None
) -> dict[str, Any]:
    """
    Get a screenshot of the CAPTCHA area with numbered grid overlay.

    Args:
        config: Browser configuration
        draw_grid: Draw numbered grid over image CAPTCHAs (default: True)
        grid_size: Force specific grid size (3 for 3x3, 4 for 4x4). Auto-detected if None.

    Returns:
        Dictionary containing:
        - screenshot_b64: Base64 PNG image with numbered blocks
        - captcha: CAPTCHA analysis info
        - grid: Grid mapping (block number -> coordinates and bounds)
        - usage: Usage example
        - target: Target ID

    The grid overlay makes it easy to specify which blocks to click.
    Block numbers start from 1 (top-left) and go left-to-right, top-to-bottom.
    """
    toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
    is_v2 = toolset in {"v2", "northstar", "north-star"}
    with get_session(config) as (session, target):
        captcha = _analyze_captcha_in_session(session, force_grid_size=int(grid_size or 0))

        if not captcha.get("detected"):
            return {
                "error": "No CAPTCHA detected",
                "suggestion": ('run(actions=[{captcha:{action:"analyze"}}])' if is_v2 else 'captcha(action="analyze")'),
                "target": target.get("id", ""),
            }

        bounds = captcha.get("bounds")
        if not bounds:
            screenshot_data = session.send("Page.captureScreenshot", {"format": "png"})
            return {
                "screenshot_b64": screenshot_data.get("data"),
                "captcha": captcha,
                "grid": None,
                "target": target.get("id", ""),
            }

        # Capture specific area with padding
        padding = 10
        clip = {
            "x": max(0, bounds["x"] - padding),
            "y": max(0, bounds["y"] - padding),
            "width": bounds["width"] + padding * 2,
            "height": bounds["height"] + padding * 2,
            "scale": 1,
        }

        screenshot_data = session.send("Page.captureScreenshot", {"format": "png", "clip": clip})

        # Determine grid dimensions
        grid_info = captcha.get("grid")
        if grid_size and grid_size in [3, 4]:
            rows = cols = grid_size
        elif grid_info:
            rows = grid_info.get("rows", 3)
            cols = grid_info.get("cols", 3)
        else:
            rows = cols = 3  # Default 3x3

        # Use gridBounds for reCAPTCHA image challenges (more accurate)
        grid_bounds = captcha.get("gridBounds") or bounds

        # Create grid mapping for click coordinates
        grid_map = _build_grid_map(grid_bounds, rows, cols)

        # Draw grid overlay on image if requested
        if draw_grid and captcha.get("type") in ["recaptcha_v2_image", "hcaptcha", "image_grid"]:
            screenshot_data = _draw_grid_overlay(screenshot_data, grid_map, clip)

        # Persist a short-lived "captcha workbench" state for stable multi-step flows:
        # screenshot → click_blocks should not drift due to re-analysis heuristics.
        try:
            tab_id = session.tab_id
            if isinstance(tab_id, str) and tab_id:
                scroll = None
                try:
                    scroll = session.eval_js("({x: window.scrollX, y: window.scrollY})")
                except Exception:
                    scroll = None
                session_manager.set_captcha_state(
                    tab_id,
                    state={
                        "type": captcha.get("type"),
                        "bounds": captcha.get("bounds"),
                        "gridBounds": captcha.get("gridBounds") or grid_bounds,
                        "rows": int(rows),
                        "cols": int(cols),
                        "gridMap": grid_map,
                        "clip": clip,
                        **({"scroll": scroll} if isinstance(scroll, dict) else {}),
                    },
                )
        except Exception:
            pass

        return {
            "screenshot_b64": screenshot_data.get("data"),
            "captcha": captcha,
            "grid": {"rows": rows, "cols": cols, "total": rows * cols, "blocks": grid_map},
            "usage": (
                'run(actions=[{captcha:{action:"click_blocks", blocks:[1,4,7]}}])'
                if is_v2
                else 'captcha(action="click_blocks", blocks=[1,4,7])'
            ),
            "target": target.get("id", ""),
        }


def _build_grid_map(grid_bounds: dict, rows: int, cols: int) -> dict[int, dict]:
    """Build grid mapping with click coordinates for each block."""
    grid_map = {}
    cell_width = grid_bounds["width"] / cols
    cell_height = grid_bounds["height"] / rows

    block_num = 1
    for row in range(rows):
        for col in range(cols):
            center_x = grid_bounds["x"] + (col + 0.5) * cell_width
            center_y = grid_bounds["y"] + (row + 0.5) * cell_height
            grid_map[block_num] = {
                "row": row + 1,
                "col": col + 1,
                "x": int(center_x),
                "y": int(center_y),
                "bounds": {
                    "x": int(grid_bounds["x"] + col * cell_width),
                    "y": int(grid_bounds["y"] + row * cell_height),
                    "width": int(cell_width),
                    "height": int(cell_height),
                },
            }
            block_num += 1

    return grid_map


def _draw_grid_overlay(screenshot_data: dict, grid_map: dict, clip: dict) -> dict:
    """Draw numbered grid overlay on screenshot using PIL."""
    try:
        data_b64 = screenshot_data.get("data")
        if not isinstance(data_b64, str) or not data_b64:
            return screenshot_data

        from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

        try:
            img_data = base64.b64decode(data_b64)
        except Exception:
            return screenshot_data

        try:
            img = Image.open(BytesIO(img_data))
        except Exception:
            return screenshot_data

        draw = ImageDraw.Draw(img)

        for block_id, block_info in grid_map.items():
            # Transform from page coordinates to screenshot coordinates
            x = block_info["bounds"]["x"] - clip["x"]
            y = block_info["bounds"]["y"] - clip["y"]
            w = block_info["bounds"]["width"]
            h = block_info["bounds"]["height"]

            # Draw cell border
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)

            # Draw block number
            text = str(block_id)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            except OSError:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            text_x = x + 5
            text_y = y + 5
            draw.rectangle([text_x - 2, text_y - 2, text_x + text_w + 4, text_y + text_h + 4], fill="red")
            draw.text((text_x, text_y), text, fill="white", font=font)

        # Encode back to base64
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        screenshot_data["data"] = base64.b64encode(buffer.getvalue()).decode()

    except Exception:
        # Best-effort only: return original screenshot if overlay fails for any reason.
        return screenshot_data

    return screenshot_data
