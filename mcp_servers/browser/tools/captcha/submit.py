"""
CAPTCHA submission.

Find and click verify/submit buttons.
"""

from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session


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
    try:
        with get_session(config) as (session, target):
            js = _build_submit_js()
            result = session.eval_js(js)
            if not isinstance(result, dict):
                result = {"found": False}

            if not result.get("found"):
                raise SmartToolError(
                    tool="submit_captcha",
                    action="find_button",
                    reason="No verify/submit button found",
                    suggestion="CAPTCHA may auto-submit, or use page(detail='locators') to find the verify button",
                )

            x = int(result["x"])
            y = int(result["y"])

            session.click(x, y, button="left", click_count=1)

            return {
                "result": {"success": True, "button": result.get("text", "verify"), "clicked": {"x": x, "y": y}},
                "target": target.get("id", ""),
            }

    except SmartToolError:
        raise
    except (OSError, ValueError, KeyError) as e:
        raise SmartToolError(
            tool="submit_captcha",
            action="submit",
            reason=str(e),
            suggestion="Try using page(detail='locators') and click(...) manually",
        ) from e


def _build_submit_js() -> str:
    """Build JavaScript to find verify/submit button."""
    return """
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
    """
