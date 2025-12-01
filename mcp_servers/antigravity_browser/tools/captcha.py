"""
CAPTCHA Detection and Interaction Tools.

Provides comprehensive CAPTCHA handling capabilities:
- analyze_captcha: Detect CAPTCHA type and structure
- get_captcha_screenshot: Visual grid with numbered blocks
- click_captcha_blocks: Click specific blocks by number
- click_captcha_area: Click checkbox/button areas
- submit_captcha: Auto-find and click verify button
"""

from __future__ import annotations

import base64
import time
from io import BytesIO
from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError
from .base import get_session as _get_session


def analyze_captcha(config: BrowserConfig, force_grid_size: int = 0) -> dict[str, Any]:
    """
    Detect and analyze CAPTCHA on the current page.

    Args:
        config: Browser configuration
        force_grid_size: Force grid size (3 for 3x3, 4 for 4x4). 0 = auto-detect.
                        Use this when auto-detection fails for mosaic-style 4x4 CAPTCHAs.

    Returns:
        Dictionary containing:
        - captcha: Analysis results with type, bounds, grid info, clickable areas
        - target: Target ID
        - suggestion: AI-friendly usage suggestion

    Automatically identifies CAPTCHA type and returns:
    - type: recaptcha_v2_checkbox, recaptcha_v2_image, hcaptcha, turnstile,
            geetest, image_text, image_grid, unknown
    - bounds: position and size of CAPTCHA element
    - challenge: description of what to do
    - grid: if image grid, returns grid dimensions and cell info
    - iframe: if in iframe, returns iframe selector
    - clickableAreas: list of interactive areas with IDs and bounds

    Use get_captcha_screenshot() to get visual with numbered blocks.
    """
    session, target = _get_session(config)
    try:
        js = f'''
        (() => {{
            const forceGridSize = {force_grid_size};
            const result = {{
                detected: false,
                type: 'unknown',
                bounds: null,
                challenge: null,
                grid: null,
                iframe: null,
                elements: [],
                clickableAreas: []
            }};

            // Helper to get element bounds
            const getBounds = (el) => {{
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    centerX: Math.round(rect.x + rect.width / 2),
                    centerY: Math.round(rect.y + rect.height / 2)
                }};
            }};

            // Check for reCAPTCHA v2 image challenge FIRST (takes priority over checkbox)
            // But only if the bframe is visible (y > -9000, since hidden bframe has y=-9999)
            let recaptchaChallengeFrame = document.querySelector('iframe[src*="recaptcha"][src*="bframe"]');
            const bframeBounds = recaptchaChallengeFrame ? getBounds(recaptchaChallengeFrame) : null;
            const bframeVisible = bframeBounds && bframeBounds.y > -9000;

            if (recaptchaChallengeFrame && bframeVisible) {{
                result.detected = true;
                result.type = 'recaptcha_v2_image';
                const frameBounds = bframeBounds;
                result.iframe = 'iframe[src*="recaptcha"][src*="bframe"]';
                result.challenge = 'Select all images matching the description. Use get_captcha_screenshot() to see numbered grid.';

                // reCAPTCHA bframe structure analysis:
                // The iframe contains a header (~100-130px) with the challenge text,
                // then the image grid, then buttons at the bottom (~50-75px).
                //
                // Two main types of challenges:
                // 1. 3x3 grid with 9 separate images: ~400x580, aspect ratio ~1.45
                // 2. 4x4 mosaic (one image split into 16): ~400x670+, aspect ratio ~1.67+
                // 3. 4x4 grid (wider frame): ~456x600+
                //
                // Grid dimensions:
                // - 3x3: grid ~372x372 (cells ~124x124)
                // - 4x4: grid ~372x372 (cells ~93x93) - same grid size, smaller cells!

                // Detect grid type from iframe dimensions
                let rows = 3, cols = 3;
                const aspectRatio = frameBounds.height / frameBounds.width;

                // Manual override via force_grid_size parameter
                if (forceGridSize === 3) {{
                    rows = 3;
                    cols = 3;
                }} else if (forceGridSize === 4) {{
                    rows = 4;
                    cols = 4;
                }}
                // Auto-detection methods (only if not forced)
                // Method 1: Wide iframe (>= 450px) indicates 4x4
                else if (frameBounds.width >= 450) {{
                    rows = 4;
                    cols = 4;
                }}
                // Method 2: High aspect ratio (>= 1.6) indicates 4x4 mosaic
                // 4x4 mosaic has same width but taller frame due to more rows
                else if (aspectRatio >= 1.6) {{
                    rows = 4;
                    cols = 4;
                }}
                // Method 3: Check if height suggests 4x4
                // 3x3: ~580px height, 4x4 mosaic: ~670px+ height
                else if (frameBounds.height >= 650) {{
                    rows = 4;
                    cols = 4;
                }}

                // Calculate image grid area within bframe
                // These values are calibrated from actual reCAPTCHA measurements
                // Header with challenge text: ~130px
                // Bottom with verify button: ~72px
                // Side padding: ~14px each side
                const headerHeight = 130;
                const bottomHeight = 72;
                const sidePadding = 14;

                // Grid is square, calculate based on available width
                const availableWidth = frameBounds.width - (sidePadding * 2);
                const gridWidth = availableWidth;
                const gridHeight = availableWidth;  // Grid is square

                // Grid bounds (position of actual image area)
                result.gridBounds = {{
                    x: Math.round(frameBounds.x + sidePadding),
                    y: Math.round(frameBounds.y + headerHeight),
                    width: Math.round(gridWidth),
                    height: Math.round(gridHeight)
                }};

                result.bounds = frameBounds;
                result.grid = {{
                    rows: rows,
                    cols: cols,
                    total: rows * cols,
                    cellWidth: Math.round(gridWidth / cols),
                    cellHeight: Math.round(gridHeight / rows),
                    aspectRatio: Math.round(aspectRatio * 100) / 100
                }};

                return result;
            }}

            // Check for reCAPTCHA v2 checkbox (only if no image challenge)
            let recaptchaFrame = document.querySelector('iframe[src*="recaptcha"][src*="anchor"]');
            if (recaptchaFrame) {{
                result.detected = true;
                result.type = 'recaptcha_v2_checkbox';
                result.bounds = getBounds(recaptchaFrame);
                result.challenge = 'Click the checkbox "I am not a robot"';
                result.iframe = 'iframe[src*="recaptcha"][src*="anchor"]';
                result.clickableAreas = [{{
                    id: 1,
                    name: 'checkbox',
                    bounds: result.bounds,
                    action: 'click'
                }}];
                return result;
            }}

            // Check for hCaptcha
            let hcaptchaFrame = document.querySelector('iframe[src*="hcaptcha"]');
            if (hcaptchaFrame) {{
                result.detected = true;
                result.type = 'hcaptcha';
                result.bounds = getBounds(hcaptchaFrame);
                result.iframe = 'iframe[src*="hcaptcha"]';
                result.challenge = 'hCaptcha challenge. May require image selection.';
                result.grid = {{ rows: 3, cols: 3, total: 9, note: 'Typical hCaptcha grid' }};
                return result;
            }}

            // Check for Cloudflare Turnstile
            let turnstileFrame = document.querySelector('iframe[src*="challenges.cloudflare"]');
            if (turnstileFrame) {{
                result.detected = true;
                result.type = 'turnstile';
                result.bounds = getBounds(turnstileFrame);
                result.iframe = 'iframe[src*="challenges.cloudflare"]';
                result.challenge = 'Cloudflare Turnstile - usually auto-solves, may need checkbox click';
                result.clickableAreas = [{{
                    id: 1,
                    name: 'turnstile_checkbox',
                    bounds: result.bounds,
                    action: 'click'
                }}];
                return result;
            }}

            // Check for GeeTest
            let geetest = document.querySelector('.geetest_holder, .geetest_panel, [class*="geetest"]');
            if (geetest) {{
                result.detected = true;
                result.type = 'geetest';
                result.bounds = getBounds(geetest);
                result.challenge = 'GeeTest slider or puzzle captcha';
                return result;
            }}

            // Check for generic image CAPTCHA
            let captchaImg = document.querySelector('img[src*="captcha" i], img[alt*="captcha" i], img[id*="captcha" i], img[class*="captcha" i]');
            if (captchaImg) {{
                result.detected = true;
                result.type = 'image_text';
                result.bounds = getBounds(captchaImg);
                result.challenge = 'Enter the text shown in the image';
                // Find associated input
                const form = captchaImg.closest('form');
                if (form) {{
                    const input = form.querySelector('input[type="text"]:not([type="hidden"])');
                    if (input) {{
                        result.elements.push({{
                            type: 'input',
                            name: input.name || input.id,
                            bounds: getBounds(input)
                        }});
                    }}
                }}
                return result;
            }}

            // Check for custom image grid (common pattern)
            let imageGrid = document.querySelector('[class*="captcha"] table, [id*="captcha"] table, .image-grid, [class*="grid"][class*="captcha"]');
            if (imageGrid) {{
                result.detected = true;
                result.type = 'image_grid';
                result.bounds = getBounds(imageGrid);
                const cells = imageGrid.querySelectorAll('td, [class*="cell"], [class*="tile"]');
                result.grid = {{
                    total: cells.length,
                    rows: Math.ceil(Math.sqrt(cells.length)),
                    cols: Math.ceil(Math.sqrt(cells.length))
                }};
                result.challenge = `Select matching images from ${{result.grid.total}}-cell grid`;

                // Map clickable areas
                cells.forEach((cell, idx) => {{
                    result.clickableAreas.push({{
                        id: idx + 1,
                        bounds: getBounds(cell),
                        action: 'click'
                    }});
                }});
                return result;
            }}

            // Check for any visible CAPTCHA-related element
            const captchaKeywords = ['captcha', 'recaptcha', 'hcaptcha', 'challenge', 'verify', 'robot'];
            for (const kw of captchaKeywords) {{
                const el = document.querySelector(`[class*="${{kw}}" i], [id*="${{kw}}" i]`);
                if (el && el.offsetWidth > 50 && el.offsetHeight > 50) {{
                    result.detected = true;
                    result.type = 'unknown';
                    result.bounds = getBounds(el);
                    result.challenge = 'Unknown CAPTCHA type detected. Use screenshot to analyze.';
                    return result;
                }}
            }}

            return result;
        }})()
        '''

        analysis = session.eval_js(js)

        return {
            "captcha": analysis,
            "target": target.get("id", ""),
            "suggestion": _get_captcha_suggestion(analysis) if analysis.get("detected") else "No CAPTCHA detected"
        }

    finally:
        session.close()


def _get_captcha_suggestion(analysis: dict[str, Any]) -> str:
    """
    Generate AI-friendly suggestion based on CAPTCHA type.

    Args:
        analysis: CAPTCHA analysis result

    Returns:
        Human-readable suggestion for next steps
    """
    ctype = analysis.get("type", "unknown")

    suggestions = {
        "recaptcha_v2_checkbox": "Use click_captcha_area(1) to click the checkbox",
        "recaptcha_v2_image": "Use get_captcha_screenshot() to see grid, then click_captcha_blocks([1,4,7]) for selected cells",
        "hcaptcha": "Use get_captcha_screenshot() to see challenge, then click_captcha_blocks() for matching images",
        "turnstile": "Usually auto-solves. If stuck, use click_captcha_area(1)",
        "geetest": "Use get_captcha_screenshot() to see puzzle, may need drag operation",
        "image_text": "Use get_captcha_screenshot() to read text, then fill input field",
        "image_grid": "Use get_captcha_screenshot() to see numbered grid, then click_captcha_blocks()",
    }
    return suggestions.get(ctype, "Use get_captcha_screenshot() to analyze visually")


def get_captcha_screenshot(
    config: BrowserConfig,
    draw_grid: bool = True,
    grid_size: int | None = None
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
    session, target = _get_session(config)
    try:
        # First analyze to find CAPTCHA
        analysis_result = analyze_captcha(config)
        captcha = analysis_result.get("captcha", {})

        if not captcha.get("detected"):
            return {
                "error": "No CAPTCHA detected",
                "suggestion": "Navigate to a page with CAPTCHA first",
                "target": target.get("id", "")
            }

        bounds = captcha.get("bounds")
        if not bounds:
            # Full page screenshot
            screenshot_data = session.send("Page.captureScreenshot", {"format": "png"})
            return {
                "screenshot_b64": screenshot_data.get("data"),
                "captcha": captcha,
                "grid": None,
                "target": target.get("id", "")
            }

        # Capture specific area with padding
        # For reCAPTCHA image challenges, capture the full iframe (bounds) for context
        padding = 10
        clip = {
            "x": max(0, bounds["x"] - padding),
            "y": max(0, bounds["y"] - padding),
            "width": bounds["width"] + padding * 2,
            "height": bounds["height"] + padding * 2,
            "scale": 1
        }

        screenshot_data = session.send("Page.captureScreenshot", {
            "format": "png",
            "clip": clip
        })

        # Determine grid dimensions
        grid_info = captcha.get("grid")
        if grid_size and grid_size in [3, 4]:
            # grid_size is the number of rows/cols (3 for 3x3, 4 for 4x4)
            rows = cols = grid_size
        elif grid_info:
            rows = grid_info.get("rows", 3)
            cols = grid_info.get("cols", 3)
        else:
            rows = cols = 3  # Default 3x3

        # Use gridBounds for reCAPTCHA image challenges (more accurate)
        # Otherwise fall back to bounds
        grid_bounds = captcha.get("gridBounds") or bounds

        # Create grid mapping for click coordinates
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
                        "height": int(cell_height)
                    }
                }
                block_num += 1

        # Draw grid overlay on image if requested
        if draw_grid and captcha.get("type") in ["recaptcha_v2_image", "hcaptcha", "image_grid"]:
            try:
                from PIL import Image, ImageDraw, ImageFont

                # Decode screenshot
                img_data = base64.b64decode(screenshot_data["data"])
                img = Image.open(BytesIO(img_data))
                draw = ImageDraw.Draw(img)

                # Calculate grid on screenshot coordinates (with padding offset)
                for block_id, block_info in grid_map.items():
                    # Transform from page coordinates to screenshot coordinates
                    # clip["x"] already includes padding subtracted, so we just subtract clip coords
                    x = block_info["bounds"]["x"] - clip["x"]
                    y = block_info["bounds"]["y"] - clip["y"]
                    w = block_info["bounds"]["width"]
                    h = block_info["bounds"]["height"]

                    # Draw cell border
                    draw.rectangle([x, y, x + w, y + h], outline="red", width=2)

                    # Draw block number
                    text = str(block_id)
                    # Try to use a larger font
                    try:
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
                    except (OSError, IOError):
                        font = ImageFont.load_default()

                    # Get text size for centering
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]

                    # Draw number with background
                    text_x = x + 5
                    text_y = y + 5
                    draw.rectangle([text_x - 2, text_y - 2, text_x + text_w + 4, text_y + text_h + 4], fill="red")
                    draw.text((text_x, text_y), text, fill="white", font=font)

                # Encode back to base64
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                screenshot_data["data"] = base64.b64encode(buffer.getvalue()).decode()

            except ImportError:
                # PIL not available - return original screenshot with grid info
                pass

        return {
            "screenshot_b64": screenshot_data.get("data"),
            "captcha": captcha,
            "grid": {
                "rows": rows,
                "cols": cols,
                "total": rows * cols,
                "blocks": grid_map
            },
            "usage": "To click blocks 1, 4, 7: click_captcha_blocks([1, 4, 7])",
            "target": target.get("id", "")
        }

    finally:
        session.close()


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
    except Exception as e:
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
    except Exception as e:
        raise SmartToolError(
            tool="click_captcha_area",
            action="click",
            reason=str(e),
            suggestion="Try using click coordinates directly with browser_click_pixel"
        ) from e
    finally:
        session.close()


def submit_captcha(config: BrowserConfig) -> dict[str, Any]:
    """
    Submit/verify the CAPTCHA after selecting images or completing challenge.

    Args:
        config: Browser configuration

    Returns:
        Dictionary containing:
        - result: Submit result with success status, button text, clicked coordinates
        - target: Target ID

    Automatically finds and clicks the verify/submit button.
    Common button selectors:
    - reCAPTCHA: #recaptcha-verify-button, .rc-button-default
    - hCaptcha: .button-submit, [data-action="submit"]
    - Generic: button[type="submit"], input[type="submit"]
    """
    session, target = _get_session(config)
    try:
        js = '''
        (() => {
            // Common verify/submit button selectors
            const selectors = [
                // reCAPTCHA
                '#recaptcha-verify-button',
                '.rc-button-default',
                '[id*="verify"]',
                // hCaptcha
                '.button-submit',
                '[data-action="submit"]',
                // Generic
                'button[type="submit"]',
                'input[type="submit"]',
                '[class*="verify" i]',
                '[class*="submit" i]',
                'button:contains("Verify")',
                'button:contains("Submit")'
            ];

            for (const sel of selectors) {
                try {
                    const btn = document.querySelector(sel);
                    if (btn && btn.offsetWidth > 0) {
                        const rect = btn.getBoundingClientRect();
                        return {
                            found: true,
                            selector: sel,
                            x: Math.round(rect.x + rect.width / 2),
                            y: Math.round(rect.y + rect.height / 2),
                            text: btn.textContent?.trim().substring(0, 30)
                        };
                    }
                } catch(e) {}
            }

            // Try iframes
            const iframes = document.querySelectorAll('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]');
            for (const iframe of iframes) {
                try {
                    const doc = iframe.contentDocument;
                    if (doc) {
                        const btn = doc.querySelector('#recaptcha-verify-button, .verify-button, button');
                        if (btn) {
                            const iframeRect = iframe.getBoundingClientRect();
                            const btnRect = btn.getBoundingClientRect();
                            return {
                                found: true,
                                inIframe: true,
                                x: Math.round(iframeRect.x + btnRect.x + btnRect.width / 2),
                                y: Math.round(iframeRect.y + btnRect.y + btnRect.height / 2),
                                text: btn.textContent?.trim().substring(0, 30)
                            };
                        }
                    }
                } catch(e) {}
            }

            return { found: false };
        })()
        '''

        result = session.eval_js(js)

        if not result.get("found"):
            raise SmartToolError(
                tool="submit_captcha",
                action="find_button",
                reason="No verify/submit button found",
                suggestion="CAPTCHA may auto-submit, or use click_element to find button manually"
            )

        x = result["x"]
        y = result["y"]

        # Click the button
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

        return {
            "result": {
                "success": True,
                "button": result.get("text", "verify"),
                "clicked": {"x": x, "y": y}
            },
            "target": target.get("id", "")
        }

    except SmartToolError:
        raise
    except Exception as e:
        raise SmartToolError(
            tool="submit_captcha",
            action="submit",
            reason=str(e),
            suggestion="Try clicking verify button manually"
        ) from e
    finally:
        session.close()
