"""
CAPTCHA detection and analysis.

Detects CAPTCHA type, bounds, grid info and clickable areas.
"""

from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ..base import get_session as _get_session


def analyze_captcha(config: BrowserConfig, force_grid_size: int = 0) -> dict[str, Any]:
    """
    Detect and analyze CAPTCHA on the current page.

    Args:
        config: Browser configuration
        force_grid_size: Force grid size (3 for 3x3, 4 for 4x4). 0 = auto-detect.

    Returns:
        Dictionary with captcha analysis, target ID, and suggestion.
    """
    session, target = _get_session(config)
    try:
        js = _build_analyze_js(force_grid_size)
        analysis = session.eval_js(js)

        return {
            "captcha": analysis,
            "target": target.get("id", ""),
            "suggestion": _get_captcha_suggestion(analysis) if analysis.get("detected") else "No CAPTCHA detected",
        }
    finally:
        session.close()


def _get_captcha_suggestion(analysis: dict[str, Any]) -> str:
    """Generate AI-friendly suggestion based on CAPTCHA type."""
    ctype = analysis.get("type", "unknown")

    suggestions = {
        "recaptcha_v2_checkbox": "Use click_captcha_area(1) to click the checkbox",
        "recaptcha_v2_image": "Use get_captcha_screenshot() to see grid, then click_captcha_blocks([1,4,7])",
        "hcaptcha": "Use get_captcha_screenshot() to see challenge, then click_captcha_blocks()",
        "turnstile": "Usually auto-solves. If stuck, use click_captcha_area(1)",
        "geetest": "Use get_captcha_screenshot() to see puzzle, may need drag operation",
        "image_text": "Use get_captcha_screenshot() to read text, then fill input field",
        "image_grid": "Use get_captcha_screenshot() to see numbered grid, then click_captcha_blocks()",
    }
    return suggestions.get(ctype, "Use get_captcha_screenshot() to analyze visually")


def _build_analyze_js(force_grid_size: int) -> str:
    """Build JavaScript for CAPTCHA analysis."""
    return f"""
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

        // Check for reCAPTCHA v2 image challenge FIRST
        let recaptchaChallengeFrame = document.querySelector('iframe[src*="recaptcha"][src*="bframe"]');
        const bframeBounds = recaptchaChallengeFrame ? getBounds(recaptchaChallengeFrame) : null;
        const bframeVisible = bframeBounds && bframeBounds.y > -9000;

        if (recaptchaChallengeFrame && bframeVisible) {{
            result.detected = true;
            result.type = 'recaptcha_v2_image';
            const frameBounds = bframeBounds;
            result.iframe = 'iframe[src*="recaptcha"][src*="bframe"]';
            result.challenge = 'Select all images matching the description.';

            let rows = 3, cols = 3;
            const aspectRatio = frameBounds.height / frameBounds.width;

            if (forceGridSize === 3) {{
                rows = cols = 3;
            }} else if (forceGridSize === 4) {{
                rows = cols = 4;
            }} else if (frameBounds.width >= 450) {{
                rows = cols = 4;
            }} else if (aspectRatio >= 1.6) {{
                rows = cols = 4;
            }} else if (frameBounds.height >= 650) {{
                rows = cols = 4;
            }}

            const headerHeight = 130;
            const sidePadding = 14;
            const availableWidth = frameBounds.width - (sidePadding * 2);

            result.gridBounds = {{
                x: Math.round(frameBounds.x + sidePadding),
                y: Math.round(frameBounds.y + headerHeight),
                width: Math.round(availableWidth),
                height: Math.round(availableWidth)
            }};

            result.bounds = frameBounds;
            result.grid = {{
                rows: rows,
                cols: cols,
                total: rows * cols,
                cellWidth: Math.round(availableWidth / cols),
                cellHeight: Math.round(availableWidth / rows),
                aspectRatio: Math.round(aspectRatio * 100) / 100
            }};

            return result;
        }}

        // Check for reCAPTCHA v2 checkbox
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
            result.challenge = 'Cloudflare Turnstile - usually auto-solves';
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
        let captchaImg = document.querySelector(
            'img[src*="captcha" i], img[alt*="captcha" i], img[id*="captcha" i], img[class*="captcha" i]'
        );
        if (captchaImg) {{
            result.detected = true;
            result.type = 'image_text';
            result.bounds = getBounds(captchaImg);
            result.challenge = 'Enter the text shown in the image';
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

        // Check for custom image grid
        let imageGrid = document.querySelector(
            '[class*="captcha"] table, [id*="captcha"] table, .image-grid'
        );
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
    """
