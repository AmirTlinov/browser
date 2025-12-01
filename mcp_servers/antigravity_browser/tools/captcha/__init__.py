"""
CAPTCHA detection, analysis and interaction tools.

Provides:
- analyze_captcha: Detect and analyze CAPTCHA type
- get_captcha_screenshot: Capture CAPTCHA with numbered grid overlay
- click_captcha_blocks: Click specific blocks in CAPTCHA grid
- click_captcha_area: Click interactive areas (checkbox, buttons)
- submit_captcha: Find and click verify/submit button
"""
from .analyze import analyze_captcha
from .click import click_captcha_area, click_captcha_blocks
from .screenshot import get_captcha_screenshot
from .submit import submit_captcha

__all__ = [
    "analyze_captcha",
    "get_captcha_screenshot",
    "click_captcha_blocks",
    "click_captcha_area",
    "submit_captcha",
]
