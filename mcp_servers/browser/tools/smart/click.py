"""
Smart element clicking by natural language.

Uses text, role, and proximity instead of CSS selectors.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session, with_retry
from .overlay import dismiss_blocking_overlay_best_effort


@with_retry(max_attempts=3, delay=0.3)
def click_element(
    config: BrowserConfig,
    text: str | None = None,
    role: str | None = None,
    near_text: str | None = None,
    index: int = 0,
    wait_timeout: float = 3.0,
    button: str = "left",
    double: bool = False,
) -> dict[str, Any]:
    """
    Click an element using natural language description instead of CSS selector.

    PREFERRED over browser_click. Automatically:
    - Waits for element to appear
    - Scrolls element into view
    - Handles visibility checks

    Args:
        text: Visible text of the element (button text, link text)
        role: Element role - "button", "link", "checkbox", "radio", "tab"
        near_text: Find element near this text (for unlabeled buttons)
        index: If multiple matches, which one (0 = first, -1 = last)
        wait_timeout: Max time to wait for element (default 3s)
        button: Mouse button (left|right|middle)
        double: Double click (default False)

    Examples:
        click_element(text="Sign In")
        click_element(text="Submit", role="button")
        click_element(near_text="Remember me", role="checkbox")
    """
    if not text and not role and not near_text:
        raise SmartToolError(
            tool="click_element",
            action="validate",
            reason="No search criteria provided",
            suggestion="Provide at least one of: text, role, or near_text",
        )

    with get_session(config) as (session, target):
        if button not in {"left", "right", "middle"}:
            raise SmartToolError(
                tool="click_element",
                action="validate",
                reason=f"Invalid mouse button: {button}",
                suggestion="Use one of: left, right, middle",
            )

        # Best-effort: cookie banners/onboarding dialogs often intercept clicks.
        # Keep this cheap: attempt at most once per click attempt.
        with contextlib.suppress(Exception):
            dismiss_blocking_overlay_best_effort(config, session=session)

        js = _build_click_js(text, role, near_text, index, wait_timeout)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="click_element",
                action="evaluate",
                reason="Click evaluation returned null",
                suggestion="Page may have navigated or crashed",
            )

        if result.get("error"):
            raise SmartToolError(
                tool="click_element",
                action="find",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Check element exists"),
                details=result.get("searchCriteria", {}),
            )

        bounds = result.get("bounds") if isinstance(result, dict) else None
        if not isinstance(bounds, dict):
            raise SmartToolError(
                tool="click_element",
                action="click",
                reason="Missing element bounds",
                suggestion="Try again or use click(selector=...) / click(x,y)",
            )

        x = float(bounds.get("x", 0.0)) + float(bounds.get("width", 0.0)) / 2
        y = float(bounds.get("y", 0.0)) + float(bounds.get("height", 0.0)) / 2
        session.click(x, y, button=button, click_count=2 if double else 1)

        return {
            "result": {
                **result,
                "clicked": {"x": x, "y": y, "button": button, "clickCount": 2 if double else 1},
            },
            "target": target["id"],
        }


def _build_click_js(text: str | None, role: str | None, near_text: str | None, index: int, wait_timeout: float) -> str:
    """Build JavaScript for smart click operation."""
    return f"""
    (() => {{
        const searchText = {json.dumps(text)};
        const searchRole = {json.dumps(role)};
        const nearText = {json.dumps(near_text)};
        const targetIndex = {index};
        const timeout = {wait_timeout * 1000};

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

        const ROOTS = collectRoots(document);
        const queryAll = (selector) => {{
            const out = [];
            for (const r of ROOTS) {{
                try {{
                    out.push(...Array.from(r.querySelectorAll(selector)));
                }} catch (e) {{
                    // ignore
                }}
            }}
            return out;
        }};

        // Helper: Check visibility
        const isVisible = (el) => {{
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' &&
                   style.visibility !== 'hidden' &&
                   style.opacity !== '0' &&
                   rect.width > 0 &&
                   rect.height > 0;
        }};

        // Helper: Best-effort dismiss a blocking overlay/modal that intercepts clicks.
        // Conservative by default: prefer close/dismiss/cancel/skip over accept.
        let overlayDismissed = false;
        const dismissBlockingOverlayOnce = () => {{
            if (overlayDismissed) return false;
            overlayDismissed = true;
            try {{
                const vw = window.innerWidth || 0;
                const vh = window.innerHeight || 0;
                if (!vw || !vh) return false;
                const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
                const cx = clamp(Math.floor(vw * 0.5), 1, vw - 2);
                const cy = clamp(Math.floor(vh * 0.5), 1, vh - 2);
                let el = document.elementFromPoint(cx, cy);
                if (!el) return false;

                const within = (r) => r && r.width > 2 && r.height > 2 && r.right > 0 && r.bottom > 0 && r.left < vw && r.top < vh;
                const looksOverlay = (node) => {{
                    if (!node || !node.getBoundingClientRect) return false;
                    const r = node.getBoundingClientRect();
                    if (!within(r)) return false;
                    const vp = vw * vh;
                    const area = Math.max(0, r.width) * Math.max(0, r.height);
                    const coversCenter = (vw * 0.5 >= r.left && vw * 0.5 <= r.right && vh * 0.5 >= r.top && vh * 0.5 <= r.bottom);

                    const role = String(node.getAttribute?.('role') || '').toLowerCase();
                    const ariaModal = String(node.getAttribute?.('aria-modal') || '').toLowerCase();
                    const hint = (String(node.id || '') + ' ' + String(node.className || '')).toLowerCase();
                    let pos = '';
                    let z = 0;
                    try {{
                        const st = window.getComputedStyle(node);
                        pos = String(st?.position || '');
                        z = Number.parseInt(String(st?.zIndex || '0'), 10);
                        if (!Number.isFinite(z)) z = 0;
                    }} catch (e) {{}}

                    if (role === 'dialog' || role === 'alertdialog' || ariaModal === 'true') return coversCenter;
                    if ((pos === 'fixed' || pos === 'sticky') && coversCenter && area >= vp * 0.25) return true;
                    if (coversCenter && z >= 1000 && area >= vp * 0.15) return true;
                    if (coversCenter && area >= vp * 0.20 && (hint.includes('modal') || hint.includes('dialog') || hint.includes('overlay') || hint.includes('backdrop') || hint.includes('consent') || hint.includes('cookie'))) return true;
                    return false;
                }};

                let overlay = null;
                for (let i = 0; i < 10 && el; i++) {{
                    if (looksOverlay(el)) {{ overlay = el; break; }}
                    el = el.parentElement;
                }}
                if (!overlay) return false;

                const normalize = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
                const labelOf = (b) => {{
                    const aria = normalize(b.getAttribute?.('aria-label'));
                    const title = normalize(b.getAttribute?.('title'));
                    const txt = normalize(b.innerText || b.textContent || '');
                    return (aria || title || txt).slice(0, 120);
                }};
                const isVisibleBtn = (b) => {{
                    try {{
                        const st = window.getComputedStyle(b);
                        if (!st || st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0' || st.pointerEvents === 'none') return false;
                    }} catch (e) {{}}
                    const r = b.getBoundingClientRect?.();
                    return !!(r && within(r));
                }};

                const closeRe = /(close|dismiss|cancel|skip|later|not now|×|x\\b|закры|отмен|пропус|позже|не сейчас)/i;
                const rejectRe = /(reject|decline|deny|no|отклон|нет|запрет)/i;
                const acceptRe = /(accept|agree|ok|got it|continue|allow|yes|соглас|принять|ок|продолж|разреш|да)/i;

                const nodes = overlay.querySelectorAll('button,[role="button"],a,input[type="button"],input[type="submit"],div[role="button"],span[role="button"]');
                let best = null;
                let bestScore = -1;
                for (const b of nodes) {{
                    if (!b || !isVisibleBtn(b)) continue;
                    const label = labelOf(b);
                    const hint = (String(b.getAttribute?.('data-testid') || '') + ' ' + String(b.id || '') + ' ' + String(b.className || '')).toLowerCase();
                    const s = (label + ' ' + hint).toLowerCase();
                    let score = 0;
                    if (closeRe.test(s)) score = 100;
                    else if (rejectRe.test(s)) score = 60;
                    else if (acceptRe.test(s)) score = 25;
                    else continue;
                    if (score > bestScore) {{ bestScore = score; best = b; }}
                }}
                if (!best) return false;

                try {{ best.click(); }} catch (e) {{}}
                const waitUntil = Date.now() + 120;
                while (Date.now() < waitUntil) {{}}
                return true;
            }} catch (_e) {{
                return false;
            }}
        }};

        // Helper: Convert an element's bounding rect to top-level viewport coordinates.
        // This is critical for same-origin iframes: getBoundingClientRect() is relative to the
        // iframe viewport, but Input.dispatchMouseEvent expects top-level viewport coordinates.
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
                    const dx = fr.x + (fe.clientLeft || 0);
                    const dy = fr.y + (fe.clientTop || 0);
                    x += dx;
                    y += dy;
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

        // Helper: Get clean text
        const getCleanText = (el) => {{
            if (!el) return '';
            const clone = el.cloneNode(true);
            clone.querySelectorAll('script, style, svg').forEach(e => e.remove());
            return (clone.textContent || '').replace(/\\s+/g, ' ').trim();
        }};

        // Helper: Get label text for an input element
        const getLabelText = (input) => {{
            if (!input) return '';
            // Check for associated label via for/id
            if (input.id) {{
                const id = cssEscape(input.id);
                for (const r of ROOTS) {{
                    try {{
                        const label = r.querySelector(`label[for="${{id}}"]`);
                        if (label) return getCleanText(label);
                    }} catch (e) {{
                        // ignore
                    }}
                }}
            }}
            // Check for wrapping label
            const parentLabel = input.closest('label');
            if (parentLabel) return getCleanText(parentLabel);
            // Check for adjacent label (sibling)
            const prevSibling = input.previousElementSibling;
            if (prevSibling && prevSibling.tagName === 'LABEL') return getCleanText(prevSibling);
            const nextSibling = input.nextElementSibling;
            if (nextSibling && nextSibling.tagName === 'LABEL') return getCleanText(nextSibling);
            return '';
        }};

        // Helper: Find elements matching criteria
        const findMatches = () => {{
            let candidates = [];

            // Role-based selection
            const roleSelectors = {{
                'button': 'button, input[type="button"], input[type="submit"], [role="button"]',
                'link': 'a[href], [role="link"]',
                'checkbox': 'input[type="checkbox"], [role="checkbox"]',
                'radio': 'input[type="radio"], [role="radio"]',
                'tab': '[role="tab"]',
                'menuitem': '[role="menuitem"]'
            }};

            if (searchRole && roleSelectors[searchRole]) {{
                candidates = queryAll(roleSelectors[searchRole]);
            }} else if (searchText) {{
                // Search all clickable elements including inputs with labels
                const clickableSelector = 'a, button, input[type="button"], input[type="submit"], ' +
                    'input[type="checkbox"], input[type="radio"], ' +
                    '[role="button"], [role="link"], [onclick], [tabindex]';
                candidates = queryAll(clickableSelector);
            }}

            // Filter by visibility
            candidates = candidates.filter(isVisible);

            // Filter by text if provided
            if (searchText) {{
                const searchLower = searchText.toLowerCase();
                candidates = candidates.filter(el => {{
                    const elText = getCleanText(el).toLowerCase();
                    const value = (el.value || '').toLowerCase();
                    const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                    const labelText = getLabelText(el).toLowerCase();
                    return elText.includes(searchLower) ||
                           value.includes(searchLower) ||
                           ariaLabel.includes(searchLower) ||
                           labelText.includes(searchLower);
                }});

                // Sort by exact match first, then by text length (shorter = more specific)
                candidates.sort((a, b) => {{
                    const aText = getCleanText(a).toLowerCase() || getLabelText(a).toLowerCase();
                    const bText = getCleanText(b).toLowerCase() || getLabelText(b).toLowerCase();
                    const aExact = aText === searchLower ? 0 : 1;
                    const bExact = bText === searchLower ? 0 : 1;
                    if (aExact !== bExact) return aExact - bExact;
                    return aText.length - bText.length;
                }});
            }}

            // Filter by proximity to nearText
            if (nearText) {{
                const nearLower = nearText.toLowerCase();
                // Find elements containing the reference text
                const refElements = Array.from(document.querySelectorAll('*')).filter(el => {{
                    const text = getCleanText(el);
                    return text.toLowerCase().includes(nearLower) && el.children.length < 3;
                }});

                if (refElements.length > 0) {{
                    const refEl = refElements[0];
                    const refRect = rectToTop(refEl) || refEl.getBoundingClientRect();

                    // Find closest matching element
                    candidates = candidates.map(el => {{
                        const elRect = rectToTop(el) || el.getBoundingClientRect();
                        const distance = Math.sqrt(
                            Math.pow(elRect.x - refRect.x, 2) +
                            Math.pow(elRect.y - refRect.y, 2)
                        );
                        return {{ el, distance }};
                    }})
                    .filter(item => item.distance < 300)  // Max 300px away
                    .sort((a, b) => a.distance - b.distance)
                    .map(item => item.el);
                }}
            }}

            return candidates;
        }};

        // Wait and find
        const startTime = Date.now();
        let matches = [];

        while (Date.now() - startTime < timeout) {{
            matches = findMatches();
            if (matches.length > 0) break;
            // One-time overlay dismissal: reduces flake on cookie/onboarding modals.
            dismissBlockingOverlayOnce();
            // Synchronous wait (not ideal but works in eval context)
            const waitUntil = Date.now() + 100;
            while (Date.now() < waitUntil) {{}}
        }}

        if (matches.length === 0) {{
            return {{
                error: true,
                reason: 'Element not found',
                searchCriteria: {{ text: searchText, role: searchRole, nearText: nearText }},
                suggestion: 'Try analyze_page first to see available elements, or use different text/role'
            }};
        }}

        // Select element by index
        const idx = targetIndex < 0 ? matches.length + targetIndex : targetIndex;
        const element = matches[Math.min(idx, matches.length - 1)];

        if (!element) {{
            return {{
                error: true,
                reason: 'Index out of range',
                found: matches.length,
                suggestion: `Found ${{matches.length}} matches, use index 0-${{matches.length - 1}}`
            }};
        }}

        // Scroll into view
        element.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});

        // Small delay for scroll to complete
        const scrollWait = Date.now() + 100;
        while (Date.now() < scrollWait) {{}}

        return {{
            success: true,
            tagName: element.tagName,
            text: getCleanText(element).substring(0, 60),
            href: element.href || null,
            download: (element.getAttribute && element.getAttribute('download')) || null,
            type: element.type || null,
            matchesFound: matches.length,
            bounds: (() => {{
                try {{
                    const top = rectToTop(element);
                    if (top) return top;
                    const r = element.getBoundingClientRect();
                    return {{ x: r.x, y: r.y, width: r.width, height: r.height }};
                }} catch (e) {{
                    return null;
                }}
            }})(),
        }};
    }})()
    """
