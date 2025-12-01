"""
Smart form filling by field names/labels.

Matches fields by name, id, label text, placeholder, or aria-label.
"""
from __future__ import annotations

import json
from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session, with_retry


@with_retry(max_attempts=2, delay=0.2)
def fill_form(
    config: BrowserConfig,
    data: dict[str, Any],
    form_index: int = 0,
    submit: bool = False
) -> dict[str, Any]:
    """
    Fill a form with provided data in one operation.

    PREFERRED over multiple browser_type calls. Intelligently matches fields by:
    1. Exact name/id match
    2. Label text match
    3. Placeholder match
    4. Aria-label match

    Args:
        data: Dict mapping field identifiers to values. Keys can be:
              - Field name/id: {"email": "user@example.com"}
              - Label text: {"Email Address": "user@example.com"}
              For checkboxes/radios: use true/false
        form_index: Which form on the page (0 = first)
        submit: Whether to submit after filling

    Returns dict with filled fields, errors, and submit status.
    """
    if not data:
        raise SmartToolError(
            tool="fill_form",
            action="validate",
            reason="No data provided",
            suggestion="Provide a dict with field names/values"
        )

    with get_session(config) as (session, target):
        js = _build_fill_form_js(data, form_index, submit)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="fill_form",
                action="evaluate",
                reason="Form fill returned null",
                suggestion="Page may have navigated or form structure changed"
            )

        if result.get("notFound") and len(result["notFound"]) > 0:
            result["suggestion"] = f"Fields not found: {result['notFound']}. Use analyze_page to see available fields."

        return {
            "result": result,
            "target": target["id"]
        }


def _build_fill_form_js(data: dict[str, Any], form_index: int, submit: bool) -> str:
    """Build JavaScript for form filling operation."""
    return f'''
    (() => {{
        const data = {json.dumps(data)};
        const formIndex = {form_index};
        const shouldSubmit = {json.dumps(submit)};

        const forms = document.querySelectorAll('form');
        const form = forms[formIndex] || null;
        const searchScope = form || document;

        // Helper: Check visibility
        const isVisible = (el) => {{
            if (!el) return false;
            const style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden';
        }};

        // Helper: Find field by various strategies
        const findField = (key) => {{
            const keyLower = key.toLowerCase().trim();

            // Strategy 1: Exact name/id match
            let el = searchScope.querySelector(`[name="${{key}}"], #${{CSS.escape(key)}}`);
            if (el && isVisible(el)) return el;

            // Strategy 2: Case-insensitive name/id
            el = searchScope.querySelector(`[name="${{keyLower}}" i], [id="${{keyLower}}" i]`);
            if (el && isVisible(el)) return el;

            // Strategy 3: Partial name/id match
            const allInputs = searchScope.querySelectorAll('input, select, textarea');
            for (const input of allInputs) {{
                if (!isVisible(input)) continue;
                const name = (input.name || '').toLowerCase();
                const id = (input.id || '').toLowerCase();
                if (name.includes(keyLower) || id.includes(keyLower)) return input;
            }}

            // Strategy 4: Label text match
            const labels = searchScope.querySelectorAll('label');
            for (const label of labels) {{
                const labelText = (label.textContent || '').toLowerCase().trim();
                if (labelText.includes(keyLower)) {{
                    if (label.htmlFor) {{
                        el = document.getElementById(label.htmlFor);
                        if (el && isVisible(el)) return el;
                    }}
                    el = label.querySelector('input, select, textarea');
                    if (el && isVisible(el)) return el;
                }}
            }}

            // Strategy 5: Placeholder match
            for (const input of allInputs) {{
                if (!isVisible(input)) continue;
                const placeholder = (input.placeholder || '').toLowerCase();
                if (placeholder.includes(keyLower)) return input;
            }}

            // Strategy 6: Aria-label match
            for (const input of allInputs) {{
                if (!isVisible(input)) continue;
                const ariaLabel = (input.getAttribute('aria-label') || '').toLowerCase();
                if (ariaLabel.includes(keyLower)) return input;
            }}

            return null;
        }};

        const results = {{
            success: true,
            filled: [],
            notFound: [],
            errors: [],
            submitted: false
        }};

        // Fill each field
        for (const [key, value] of Object.entries(data)) {{
            const field = findField(key);

            if (!field) {{
                results.notFound.push(key);
                results.success = false;
                continue;
            }}

            try {{
                const tagName = field.tagName.toLowerCase();
                const type = (field.type || '').toLowerCase();

                if (type === 'checkbox') {{
                    const shouldCheck = Boolean(value);
                    if (field.checked !== shouldCheck) {{
                        field.click();
                    }}
                    results.filled.push({{ key, type: 'checkbox', checked: field.checked }});
                }} else if (type === 'radio') {{
                    field.checked = true;
                    field.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    results.filled.push({{ key, type: 'radio', value: field.value }});
                }} else if (tagName === 'select') {{
                    // Try value first, then text
                    let found = false;
                    for (const opt of field.options) {{
                        if (opt.value === value || opt.textContent.trim() === value) {{
                            field.value = opt.value;
                            found = true;
                            break;
                        }}
                    }}
                    if (!found) field.value = value;
                    field.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    results.filled.push({{ key, type: 'select', value: field.value }});
                }} else {{
                    // Text input, textarea, etc.
                    field.focus();
                    field.value = String(value);
                    field.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    field.dispatchEvent(new Event('change', {{ bubbles: true }}));

                    // Verify
                    if (field.value !== String(value)) {{
                        results.errors.push({{
                            key, error: 'Value not set correctly', expected: value, actual: field.value
                        }});
                    }} else {{
                        results.filled.push({{ key, type: type || 'text', valueLength: field.value.length }});
                    }}
                }}
            }} catch (e) {{
                results.errors.push({{ key, error: e.message }});
                results.success = false;
            }}
        }}

        // Submit if requested
        if (shouldSubmit && results.filled.length > 0) {{
            const submitBtn = searchScope.querySelector(
                'button[type="submit"], input[type="submit"], button:not([type="button"]):not([type="reset"])'
            );
            if (submitBtn && isVisible(submitBtn)) {{
                submitBtn.click();
                results.submitted = true;
            }} else if (form) {{
                form.submit();
                results.submitted = true;
            }} else {{
                results.errors.push({{ error: 'No submit button found and no form to submit' }});
            }}
        }}

        return results;
    }})()
    '''
