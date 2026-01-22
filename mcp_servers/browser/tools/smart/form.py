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
def fill_form(config: BrowserConfig, data: dict[str, Any], form_index: int = 0, submit: bool = False) -> dict[str, Any]:
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
            suggestion="Provide a dict with field names/values",
        )

    with get_session(config) as (session, target):
        js = _build_fill_form_js(data, form_index, submit)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="fill_form",
                action="evaluate",
                reason="Form fill returned null",
                suggestion="Page may have navigated or form structure changed",
            )

        if result.get("notFound") and len(result["notFound"]) > 0:
            result["suggestion"] = f"Fields not found: {result['notFound']}. Use analyze_page to see available fields."

        return {"result": result, "target": target["id"]}


@with_retry(max_attempts=2, delay=0.2)
def focus_field(config: BrowserConfig, key: str, form_index: int = 0) -> dict[str, Any]:
    """Focus a form field by semantic key (label/name/id/placeholder/aria-label).

    Why this exists:
    - CSS selectors are brittle and do not work across iframes.
    - This enables stable `act(ref=...)` for inputs, including same-origin iframes + open shadow DOM.
    """
    if not isinstance(key, str) or not key.strip():
        raise SmartToolError(
            tool="focus_field",
            action="validate",
            reason="Missing key",
            suggestion="Provide focus_key like 'Email' or 'Password'",
        )

    with get_session(config) as (session, target):
        js = _build_focus_field_js(key, form_index)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="focus_field",
                action="evaluate",
                reason="Focus returned null",
                suggestion="Page may have navigated or the field is not accessible",
            )

        if isinstance(result, dict) and result.get("error"):
            raise SmartToolError(
                tool="focus_field",
                action="focus",
                reason=result.get("reason", "Field not found"),
                suggestion=result.get("suggestion", "Try a different key or use page(detail='locators')"),
                details={"key": key, "form_index": form_index},
            )

        return {"result": result, "target": target["id"]}


def _build_fill_form_js(data: dict[str, Any], form_index: int, submit: bool) -> str:
    """Build JavaScript for form filling operation."""
    return f"""
    (() => {{
        const data = {json.dumps(data)};
        const formIndex = {form_index};
        const shouldSubmit = {json.dumps(submit)};

        // Helper: Traverse open shadow roots (best-effort)
        const cssEscape = (value) => {{
            try {{
                if (globalThis.CSS && typeof globalThis.CSS.escape === 'function') return globalThis.CSS.escape(String(value));
            }} catch (e) {{
                // ignore
            }}
            return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${{c}}`);
        }};

        const collectRoots = (start) => {{
            const roots = [];
            const queue = [{{ root: start, depth: 0 }}];
            const MAX_ROOTS = 60;
            const MAX_DEPTH = 6;
            const MAX_SCAN = 4000;

            while (queue.length && roots.length < MAX_ROOTS) {{
                const item = queue.shift();
                const root = item && item.root;
                const depth = item && typeof item.depth === 'number' ? item.depth : 0;
                if (!root) continue;
                if (roots.includes(root)) continue;
                roots.push(root);
                if (depth >= MAX_DEPTH) continue;
                if (!root.querySelectorAll) continue;

                let scanned = 0;
                for (const el of root.querySelectorAll('*')) {{
                    scanned += 1;
                    if (scanned > MAX_SCAN) break;
                    if (el && el.shadowRoot) {{
                        queue.push({{ root: el.shadowRoot, depth: depth + 1 }});
                        if (roots.length + queue.length >= MAX_ROOTS) break;
                    }}
                    if (el && (el.tagName === 'IFRAME' || el.tagName === 'FRAME')) {{
                        try {{
                            const doc = el.contentDocument || (el.contentWindow && el.contentWindow.document);
                            if (doc) {{
                                queue.push({{ root: doc, depth: depth + 1 }});
                                if (roots.length + queue.length >= MAX_ROOTS) break;
                            }}
                        }} catch (e) {{
                            // Cross-origin frame; ignore.
                        }}
                    }}
                }}
            }}
            return roots;
        }};

        const DOC_ROOTS = collectRoots(document);
        const queryAllFrom = (roots, selector) => {{
            const out = [];
            for (const r of roots) {{
                try {{
                    out.push(...Array.from(r.querySelectorAll(selector)));
                }} catch (e) {{
                    // ignore
                }}
            }}
            return out;
        }};

        const forms = queryAllFrom(DOC_ROOTS, 'form');
        const form = forms[formIndex] || null;
        const searchScope = form || document;

        const ROOTS = form ? collectRoots(form) : DOC_ROOTS;
        const queryAll = (selector) => queryAllFrom(ROOTS, selector);

        // Helper: Check visibility
        const isVisible = (el) => {{
            if (!el) return false;
            const style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden';
        }};

        const getText = (el) => (el && el.textContent ? String(el.textContent) : '').replace(/\\s+/g, ' ').trim();

        const getLabelText = (input, labels) => {{
            try {{
                if (input && input.labels && input.labels[0]) return getText(input.labels[0]);
            }} catch (e) {{
                // ignore
            }}

            try {{
                const parentLabel = input && input.closest ? input.closest('label') : null;
                if (parentLabel) return getText(parentLabel);
            }} catch (e) {{
                // ignore
            }}

            const id = input && input.id ? String(input.id) : '';
            if (id && Array.isArray(labels)) {{
                const idEsc = cssEscape(id);
                for (const r of ROOTS) {{
                    try {{
                        const lbl = r.querySelector(`label[for="${{idEsc}}"]`);
                        if (lbl) return getText(lbl);
                    }} catch (e) {{
                        // ignore
                    }}
                }}

                for (const lbl of labels) {{
                    try {{
                        if (lbl && lbl.htmlFor && String(lbl.htmlFor) === id) return getText(lbl);
                    }} catch (e) {{
                        // ignore
                    }}
                }}
            }}

            return '';
        }};

        const labels = queryAll('label');
        const inputs = queryAll('input, select, textarea').filter(isVisible);
        const metas = inputs.map((el) => {{
            const tagName = (el.tagName || '').toLowerCase();
            const type = (el.getAttribute && el.getAttribute('type') ? el.getAttribute('type') : (el.type || tagName)).toLowerCase();
            const name = el.name || '';
            const id = el.id || '';
            const placeholder = el.placeholder || (el.getAttribute ? (el.getAttribute('placeholder') || '') : '');
            const ariaLabel = el.getAttribute ? (el.getAttribute('aria-label') || '') : '';
            const label = getLabelText(el, labels);

            return {{
                el,
                type,
                name,
                nameLower: String(name).toLowerCase(),
                id,
                idLower: String(id).toLowerCase(),
                label,
                labelLower: String(label).toLowerCase(),
                placeholder,
                placeholderLower: String(placeholder).toLowerCase(),
                ariaLabel,
                ariaLower: String(ariaLabel).toLowerCase(),
            }};
        }});

        // Helper: Find field by various strategies (works across open shadow roots)
        const findField = (key) => {{
            const keyStr = String(key || '').trim();
            const keyLower = keyStr.toLowerCase();

            let m = metas.find((x) => (x.name && x.name === keyStr) || (x.id && x.id === keyStr));
            if (m) return m.el;

            m = metas.find((x) => (x.nameLower && x.nameLower === keyLower) || (x.idLower && x.idLower === keyLower));
            if (m) return m.el;

            m = metas.find((x) => (x.nameLower && x.nameLower.includes(keyLower)) || (x.idLower && x.idLower.includes(keyLower)));
            if (m) return m.el;

            m = metas.find((x) => x.labelLower && x.labelLower.includes(keyLower));
            if (m) return m.el;

            m = metas.find((x) => x.placeholderLower && x.placeholderLower.includes(keyLower));
            if (m) return m.el;

            m = metas.find((x) => x.ariaLower && x.ariaLower.includes(keyLower));
            if (m) return m.el;

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
                // Best-effort: scroll to the field, including iframe owners.
                try {{
                    let win = field.ownerDocument && field.ownerDocument.defaultView ? field.ownerDocument.defaultView : null;
                    let guard = 0;
                    while (win && win.frameElement && guard < 8) {{
                        try {{
                            win.frameElement.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});
                        }} catch (_e) {{
                            // ignore
                        }}
                        try {{
                            win = win.parent;
                        }} catch (_e2) {{
                            break;
                        }}
                        guard += 1;
                    }}
                }} catch (_e) {{
                    // ignore
                }}

                try {{
                    field.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});
                }} catch (_e) {{
                    // ignore
                }}

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
    """


def _build_focus_field_js(key: str, form_index: int) -> str:
    """Build JavaScript for focusing a field by semantic key (best-effort)."""
    return f"""
    (() => {{
        const key = {json.dumps(key)};
        const formIndex = {int(form_index)};

        // Helper: Traverse open shadow roots + same-origin iframes (best-effort).
        const cssEscape = (value) => {{
            try {{
                if (globalThis.CSS && typeof globalThis.CSS.escape === 'function') return globalThis.CSS.escape(String(value));
            }} catch (e) {{
                // ignore
            }}
            return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${{c}}`);
        }};

        const collectRoots = (start) => {{
            const roots = [];
            const queue = [{{ root: start, depth: 0 }}];
            const MAX_ROOTS = 60;
            const MAX_DEPTH = 6;
            const MAX_SCAN = 4000;

            while (queue.length && roots.length < MAX_ROOTS) {{
                const item = queue.shift();
                const root = item && item.root;
                const depth = item && typeof item.depth === 'number' ? item.depth : 0;
                if (!root) continue;
                if (roots.includes(root)) continue;
                roots.push(root);
                if (depth >= MAX_DEPTH) continue;
                if (!root.querySelectorAll) continue;

                let scanned = 0;
                for (const el of root.querySelectorAll('*')) {{
                    scanned += 1;
                    if (scanned > MAX_SCAN) break;
                    if (el && el.shadowRoot) {{
                        queue.push({{ root: el.shadowRoot, depth: depth + 1 }});
                        if (roots.length + queue.length >= MAX_ROOTS) break;
                    }}
                    if (el && (el.tagName === 'IFRAME' || el.tagName === 'FRAME')) {{
                        try {{
                            const doc = el.contentDocument || (el.contentWindow && el.contentWindow.document);
                            if (doc) {{
                                queue.push({{ root: doc, depth: depth + 1 }});
                                if (roots.length + queue.length >= MAX_ROOTS) break;
                            }}
                        }} catch (e) {{
                            // Cross-origin frame; ignore.
                        }}
                    }}
                }}
            }}
            return roots;
        }};

        const DOC_ROOTS = collectRoots(document);
        const queryAllFrom = (roots, selector) => {{
            const out = [];
            for (const r of roots) {{
                try {{
                    out.push(...Array.from(r.querySelectorAll(selector)));
                }} catch (e) {{
                    // ignore
                }}
            }}
            return out;
        }};

        const forms = queryAllFrom(DOC_ROOTS, 'form');
        const form = forms[formIndex] || null;
        const ROOTS = form ? collectRoots(form) : DOC_ROOTS;
        const queryAll = (selector) => queryAllFrom(ROOTS, selector);

        const getText = (el) => (el && el.textContent ? String(el.textContent) : '').replace(/\\s+/g, ' ').trim();

        const getLabelText = (input, labels) => {{
            try {{
                if (input && input.labels && input.labels[0]) return getText(input.labels[0]);
            }} catch (e) {{
                // ignore
            }}

            try {{
                const parentLabel = input && input.closest ? input.closest('label') : null;
                if (parentLabel) return getText(parentLabel);
            }} catch (e) {{
                // ignore
            }}

            const id = input && input.id ? String(input.id) : '';
            if (id && Array.isArray(labels)) {{
                const idEsc = cssEscape(id);
                for (const r of ROOTS) {{
                    try {{
                        const lbl = r.querySelector(`label[for="${{idEsc}}"]`);
                        if (lbl) return getText(lbl);
                    }} catch (e) {{
                        // ignore
                    }}
                }}

                for (const lbl of labels) {{
                    try {{
                        if (lbl && lbl.htmlFor && String(lbl.htmlFor) === id) return getText(lbl);
                    }} catch (e) {{
                        // ignore
                    }}
                }}
            }}

            return '';
        }};

        const rectToTop = (el) => {{
            try {{
                if (!el || !el.getBoundingClientRect) return null;
                const r = el.getBoundingClientRect();
                let x = r.x;
                let y = r.y;
                const w = r.width;
                const h = r.height;
                let win = el.ownerDocument && el.ownerDocument.defaultView ? el.ownerDocument.defaultView : null;
                let guard = 0;
                while (win && win.frameElement && guard < 12) {{
                    const fe = win.frameElement;
                    const fr = fe.getBoundingClientRect();
                    x += fr.x + (fe.clientLeft || 0);
                    y += fr.y + (fe.clientTop || 0);
                    try {{
                        win = win.parent;
                    }} catch (_e) {{
                        break;
                    }}
                    guard += 1;
                }}
                return {{ x, y, width: w, height: h }};
            }} catch (_e) {{
                return null;
            }}
        }};

        const isVisible = (el) => {{
            try {{
                if (!el) return false;
                const style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }} catch (_e) {{
                return true;
            }}
        }};

        const labels = queryAll('label');
        const inputs = queryAll('input, select, textarea').filter(isVisible);
        const metas = inputs.map((el) => {{
            const tagName = (el.tagName || '').toLowerCase();
            const type = (el.getAttribute && el.getAttribute('type') ? el.getAttribute('type') : (el.type || tagName)).toLowerCase();
            const name = el.name || '';
            const id = el.id || '';
            const placeholder = el.placeholder || (el.getAttribute ? (el.getAttribute('placeholder') || '') : '');
            const ariaLabel = el.getAttribute ? (el.getAttribute('aria-label') || '') : '';
            const label = getLabelText(el, labels);

            return {{
                el,
                type,
                name,
                nameLower: String(name).toLowerCase(),
                id,
                idLower: String(id).toLowerCase(),
                label,
                labelLower: String(label).toLowerCase(),
                placeholder,
                placeholderLower: String(placeholder).toLowerCase(),
                ariaLabel,
                ariaLower: String(ariaLabel).toLowerCase(),
            }};
        }});

        const findField = (key) => {{
            const keyStr = String(key || '').trim();
            const keyLower = keyStr.toLowerCase();

            let m = metas.find((x) => (x.name && x.name === keyStr) || (x.id && x.id === keyStr));
            if (m) return m.el;

            m = metas.find((x) => (x.nameLower && x.nameLower === keyLower) || (x.idLower && x.idLower === keyLower));
            if (m) return m.el;

            m = metas.find((x) => (x.nameLower && x.nameLower.includes(keyLower)) || (x.idLower && x.idLower.includes(keyLower)));
            if (m) return m.el;

            m = metas.find((x) => x.labelLower && x.labelLower.includes(keyLower));
            if (m) return m.el;

            m = metas.find((x) => x.placeholderLower && x.placeholderLower.includes(keyLower));
            if (m) return m.el;

            m = metas.find((x) => x.ariaLower && x.ariaLower.includes(keyLower));
            if (m) return m.el;

            return null;
        }};

        const field = findField(key);
        if (!field) {{
            return {{
                error: true,
                reason: 'Field not found',
                suggestion: 'Try page(detail="locators") to see available inputs or use a different focus_key',
            }};
        }}

        // Scroll chain: iframe owners then field itself (best-effort).
        try {{
            let win = field.ownerDocument && field.ownerDocument.defaultView ? field.ownerDocument.defaultView : null;
            let guard = 0;
            while (win && win.frameElement && guard < 8) {{
                try {{
                    win.frameElement.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});
                }} catch (_e) {{
                    // ignore
                }}
                try {{
                    win = win.parent;
                }} catch (_e2) {{
                    break;
                }}
                guard += 1;
            }}
        }} catch (_e) {{
            // ignore
        }}

        try {{
            field.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});
        }} catch (_e) {{
            // ignore
        }}

        let focused = false;
        try {{
            field.focus();
            const w = field.ownerDocument && field.ownerDocument.defaultView ? field.ownerDocument.defaultView : null;
            const active = field.ownerDocument && field.ownerDocument.activeElement ? field.ownerDocument.activeElement : null;
            focused = active === field;
        }} catch (_e) {{
            focused = false;
        }}

        const bounds = rectToTop(field);
        return {{
            success: true,
            key: String(key),
            formIndex: form ? formIndex : null,
            focused,
            tagName: field.tagName,
            inputType: (field.type || field.tagName || '').toLowerCase(),
            ...(bounds && {{ bounds, center: {{ x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 }} }}),
        }};
    }})()
    """
