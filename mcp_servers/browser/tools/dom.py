"""
DOM tools for browser automation.

Provides:
- get_dom: Get HTML content from page or element with size limits
- get_element_info: Get detailed element information
- screenshot: Capture page screenshot
"""

from __future__ import annotations

import base64
import contextlib
import json
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError, get_session
from .shadow_dom import DEEP_QUERY_JS

# Default and max limits for HTML content
DEFAULT_MAX_CHARS = 50000  # 50KB default
MAX_CHARS_LIMIT = 200000  # 200KB max


def get_dom(
    config: BrowserConfig,
    selector: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    include_metadata: bool = True,
) -> dict[str, Any]:
    """Get DOM HTML from session's tab with size limiting.

    IMPORTANT: Consider using analyze_page() or extract_content() for
    structured data - they are more context-efficient.

    Args:
        config: Browser configuration
        selector: Optional CSS selector to get HTML of specific element
        max_chars: Maximum HTML characters to return (default: 50000, max: 200000)
        include_metadata: Include HTML size metadata (default: True)

    Returns:
        Dict with:
        - html: HTML content (truncated if exceeds max_chars)
        - truncated: True if HTML was truncated
        - totalChars: Original HTML size before truncation
        - returnedChars: Actual returned size
        - target: Target ID
        - hint: Suggestion if truncated
    """
    max_chars = min(max_chars, MAX_CHARS_LIMIT)

    with get_session(config) as (session, target):
        try:
            meta: dict[str, Any] = {}
            if selector:
                js = f"""
                (() => {{
                    {DEEP_QUERY_JS}
                    const selector = {json.dumps(selector)};
                    const nodes = __mcpQueryAllDeep(selector, 1000);
                    const matchesFound = nodes.length;
                    const pickFrom = nodes.filter(__mcpIsVisible);
                    const el = (pickFrom.length ? pickFrom : nodes)[0] || null;
                    if (!el) return null;

                    let inShadowDOM = false;
                    try {{
                        inShadowDOM = !!(el.getRootNode && el.getRootNode() !== document);
                    }} catch (e) {{
                        inShadowDOM = false;
                    }}

                    let html = '';
                    try {{
                        html = el.outerHTML || '';
                    }} catch (e) {{
                        html = '';
                    }}

                    let includedShadowRoot = false;
                    try {{
                        if (el.shadowRoot && el.shadowRoot.innerHTML != null) {{
                            includedShadowRoot = true;
                            html = html + "\n<!-- shadowRoot -->\n" + String(el.shadowRoot.innerHTML);
                        }}
                    }} catch (e) {{
                        includedShadowRoot = false;
                    }}

                    return {{ html, matchesFound, inShadowDOM, includedShadowRoot }};
                }})()
                """
                found = session.eval_js(js)
                if not found or not isinstance(found, dict) or not found.get("html"):
                    raise SmartToolError(
                        tool="get_dom",
                        action="get",
                        reason=f"Element not found: {selector}",
                        suggestion="Check selector or use page(detail='locators') to find stable selectors",
                    )
                html = str(found.get("html") or "")
                meta = {
                    "selector": selector,
                    "matchesFound": found.get("matchesFound"),
                    "inShadowDOM": found.get("inShadowDOM", False),
                    "includedShadowRoot": found.get("includedShadowRoot", False),
                }
            else:
                html = session.eval_js("document.documentElement.outerHTML") or ""

            total_chars = len(html)
            truncated = total_chars > max_chars

            if truncated:
                html = html[:max_chars]

            result: dict[str, Any] = {
                "html": html,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
                **meta,
            }

            if include_metadata:
                result["totalChars"] = total_chars
                result["returnedChars"] = len(html)
                result["truncated"] = truncated

            if truncated:
                result["hint"] = (
                    f"HTML truncated ({total_chars} -> {max_chars} chars). "
                    f"Options: 1) Use selector='...' to get specific element, "
                    f"2) Use max_chars={min(total_chars, MAX_CHARS_LIMIT)} for full content, "
                    f"3) Use analyze_page() or extract_content() for structured data."
                )

            return result
        except Exception as e:
            raise SmartToolError(
                tool="get_dom",
                action="get",
                reason=str(e),
                suggestion="Check selector is valid. Consider using analyze_page() instead.",
            ) from e


def get_element_info(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Get detailed element information by CSS selector.

    Args:
        config: Browser configuration
        selector: CSS selector to find element

    Returns:
        Dict with element info (tag, id, class, text, bounds, attributes), target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                {DEEP_QUERY_JS}

                const selector = {json.dumps(selector)};
                const nodes = __mcpQueryAllDeep(selector, 1000);
                const matchesFound = nodes.length;
                const pickFrom = nodes.filter(__mcpIsVisible);
                const el = (pickFrom.length ? pickFrom : nodes)[0] || null;
                if (!el) return null;

                const cssEscape = (value) => {{
                    try {{
                        if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(String(value));
                    }} catch (e) {{
                        // ignore
                    }}
                    return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${{c}}`);
                }};

                const isUnique = (sel) => {{
                    try {{
                        return __mcpQueryAllDeep(sel, 2).length === 1;
                    }} catch (e) {{
                        return false;
                    }}
                }};

                const bestSelector = (node) => {{
                    const tag = (node.tagName || '').toLowerCase();
                    const candidates = [];

                    const testAttrs = ['data-testid', 'data-test', 'data-qa', 'data-cy', 'data-e2e', 'data-test-id'];
                    for (const a of testAttrs) {{
                        const v = node.getAttribute && node.getAttribute(a);
                        if (!v) continue;
                        const sel = `[${{a}}="${{cssEscape(v)}}"]`;
                        candidates.push({{ selector: sel, reason: a }});
                        if (isUnique(sel)) return {{ best: sel, candidates }};
                    }}

                    if (node.id) {{
                        const sel = `#${{cssEscape(node.id)}}`;
                        candidates.push({{ selector: sel, reason: 'id' }});
                        if (isUnique(sel)) return {{ best: sel, candidates }};
                    }}

                    const name = node.getAttribute && node.getAttribute('name');
                    if (name) {{
                        const sel = `${{tag}}[name="${{cssEscape(name)}}"]`;
                        candidates.push({{ selector: sel, reason: 'name' }});
                        if (isUnique(sel)) return {{ best: sel, candidates }};
                    }}

                    const aria = node.getAttribute && node.getAttribute('aria-label');
                    if (aria) {{
                        const sel = `${{tag}}[aria-label="${{cssEscape(aria)}}"]`;
                        candidates.push({{ selector: sel, reason: 'aria-label' }});
                        if (isUnique(sel)) return {{ best: sel, candidates }};
                    }}

                    // Fallback path
                    try {{
                        const parts = [];
                        let cur = node;
                        for (let depth = 0; depth < 6 && cur && cur.nodeType === 1 && cur !== document.documentElement; depth++) {{
                            const t = cur.tagName.toLowerCase();
                            let part = t;
                            if (cur.id) {{
                                part = `${{t}}#${{cssEscape(cur.id)}}`;
                                parts.unshift(part);
                                const sel = parts.join(' > ');
                                candidates.push({{ selector: sel, reason: 'path' }});
                                if (isUnique(sel)) return {{ best: sel, candidates }};
                                break;
                            }}
                            const parent = cur.parentElement;
                            if (!parent) break;
                            const siblings = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
                            const idx = siblings.indexOf(cur) + 1;
                            if (siblings.length > 1) part = `${{t}}:nth-of-type(${{idx}})`;
                            parts.unshift(part);
                            const sel = parts.join(' > ');
                            candidates.push({{ selector: sel, reason: 'path' }});
                            if (isUnique(sel)) return {{ best: sel, candidates }};
                            cur = parent;
                        }}
                    }} catch (e) {{
                        // ignore
                    }}

                    const fallback = candidates.length ? candidates[candidates.length - 1].selector : tag;
                    return {{ best: fallback, candidates }};
                }};

                const rect = el.getBoundingClientRect();
                const selectorInfo = bestSelector(el);
                let inShadowDOM = false;
                try {{
                    inShadowDOM = !!(el.getRootNode && el.getRootNode() !== document);
                }} catch (e) {{
                    inShadowDOM = false;
                }}
                return {{
                    tagName: el.tagName,
                    id: el.id,
                    className: el.className,
                    text: el.textContent?.slice(0, 200),
                    bounds: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
                    attributes: Object.fromEntries([...el.attributes].map(a => [a.name, a.value])),
                    bestSelector: selectorInfo.best,
                    selectorCandidates: selectorInfo.candidates.slice(0, 5),
                    inShadowDOM,
                    selector,
                    matchesFound
                }};
            }})()
            """
            result = session.eval_js(js)
            if result is None:
                raise SmartToolError(
                    tool="get_element",
                    action="find",
                    reason=f"Element not found: {selector}",
                    suggestion="Check selector is correct",
                )
            return {"element": result, "target": target["id"], "sessionTabId": session_manager.tab_id}
        except SmartToolError:
            raise
        except Exception as e:
            raise SmartToolError(
                tool="get_element",
                action="get",
                reason=str(e),
                suggestion="Check selector syntax",
            ) from e


def screenshot(
    config: BrowserConfig,
    selector: str | None = None,
    full_page: bool = False,
    backend_dom_node_id: int | None = None,
) -> dict[str, Any]:
    """Take screenshot of session's tab.

    Args:
        config: Browser configuration
        selector: Optional CSS selector to screenshot a specific element
        full_page: Capture full page (best-effort; may fall back to viewport)
        backend_dom_node_id: Optional stable backend node id to screenshot an element

    Returns:
        Dict with base64 screenshot, byte size, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            mode = "viewport"
            warning: str | None = None

            # Element screenshot (preferred over full_page if both provided)
            clip: dict[str, Any] | None = None
            if backend_dom_node_id is not None:
                mode = "backend_node"
                backend_id = int(backend_dom_node_id)
                if backend_id <= 0:
                    raise SmartToolError(
                        tool="screenshot",
                        action="capture",
                        reason="backend_dom_node_id must be a positive integer",
                        suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
                    )

                with contextlib.suppress(Exception):
                    session.enable_dom()

                with contextlib.suppress(Exception):
                    session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_id})
                try:
                    box = session.send("DOM.getBoxModel", {"backendNodeId": backend_id})
                except Exception as exc:  # noqa: BLE001
                    raise SmartToolError(
                        tool="screenshot",
                        action="capture",
                        reason=str(exc),
                        suggestion="The node may be detached; re-query via page(detail='ax')",
                        details={"backendDOMNodeId": backend_id},
                    ) from exc
                model = box.get("model") if isinstance(box, dict) else None
                quad = None
                if isinstance(model, dict):
                    quad = model.get("border") or model.get("content") or model.get("padding")
                if not isinstance(quad, list) or len(quad) < 8:
                    raise SmartToolError(
                        tool="screenshot",
                        action="capture",
                        reason="Missing box model quad for backend node",
                        suggestion="The node may be detached; re-query via page(detail='ax')",
                        details={"backendDOMNodeId": backend_id},
                    )

                xs = [float(quad[i]) for i in (0, 2, 4, 6)]
                ys = [float(quad[i]) for i in (1, 3, 5, 7)]
                x0 = min(xs)
                y0 = min(ys)
                x1 = max(xs)
                y1 = max(ys)
                w = max(0.0, x1 - x0)
                h = max(0.0, y1 - y0)

                viewport = session.eval_js("({ vw: window.innerWidth, vh: window.innerHeight })") or {}
                vw = max(1.0, float(viewport.get("vw", 1.0)))
                vh = max(1.0, float(viewport.get("vh", 1.0)))

                x = max(0.0, float(x0))
                y = max(0.0, float(y0))
                w = min(w, max(0.0, vw - x))
                h = min(h, max(0.0, vh - y))

                if w <= 0.0 or h <= 0.0:
                    raise SmartToolError(
                        tool="screenshot",
                        action="capture",
                        reason="Element has zero visible size (backend_dom_node_id)",
                        suggestion="Scroll to the element and retry, or screenshot the full page",
                        details={"backendDOMNodeId": backend_id},
                    )

                clip = {"x": x, "y": y, "width": w, "height": h, "scale": 1}

            elif selector:
                mode = "element"
                js = f"""
                (() => {{
                    {DEEP_QUERY_JS}
                    const selector = {json.dumps(selector)};
                    const nodes = __mcpQueryAllDeep(selector, 1000);
                    const pickFrom = nodes.filter(__mcpIsVisible);
                    const el = (pickFrom.length ? pickFrom : nodes)[0] || null;
                    if (!el) return null;
                    el.scrollIntoView({{behavior: 'instant', block: 'center', inline: 'center'}});
                    const rect = el.getBoundingClientRect();
                    return {{
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        viewportWidth: window.innerWidth,
                        viewportHeight: window.innerHeight,
                    }};
                }})()
                """
                rect = session.eval_js(js)
                if not rect:
                    raise SmartToolError(
                        tool="screenshot",
                        action="capture",
                        reason=f"Element not found: {selector}",
                        suggestion="Check selector or use page() to discover elements",
                    )

                x = max(0.0, float(rect.get("x", 0.0)))
                y = max(0.0, float(rect.get("y", 0.0)))
                vw = max(1.0, float(rect.get("viewportWidth", 1.0)))
                vh = max(1.0, float(rect.get("viewportHeight", 1.0)))
                w = max(0.0, float(rect.get("width", 0.0)))
                h = max(0.0, float(rect.get("height", 0.0)))

                # Clamp to viewport to avoid CDP errors
                w = min(w, max(0.0, vw - x))
                h = min(h, max(0.0, vh - y))
                if w <= 0.0 or h <= 0.0:
                    raise SmartToolError(
                        tool="screenshot",
                        action="capture",
                        reason=f"Element has zero visible size: {selector}",
                        suggestion="Scroll to the element and retry, or screenshot the full page",
                    )

                clip = {"x": x, "y": y, "width": w, "height": h, "scale": 1}

            # Full page screenshot
            if full_page and not selector:
                mode = "full_page"
                metrics = session.send("Page.getLayoutMetrics")
                content = metrics.get("contentSize") or {}
                w = float(content.get("width", 0.0))
                h = float(content.get("height", 0.0))
                if w > 0.0 and h > 0.0:
                    clip = {"x": 0.0, "y": 0.0, "width": w, "height": h, "scale": 1}
                else:
                    warning = "Full-page metrics unavailable; falling back to viewport screenshot"
                    mode = "viewport"

            if mode == "full_page":
                try:
                    data_b64 = session.screenshot(clip=clip, capture_beyond_viewport=True)
                except Exception:  # noqa: BLE001
                    # Best-effort fallback
                    warning = warning or "Full-page capture not supported; falling back to viewport screenshot"
                    mode = "viewport"
                    data_b64 = session.screenshot()
            elif clip:
                data_b64 = session.screenshot(clip=clip)
            else:
                data_b64 = session.screenshot()

            binary = base64.b64decode(data_b64, validate=False)
            return {
                "content_b64": data_b64,
                "bytes": len(binary),
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
                "mode": mode,
                **({"warning": warning} if warning else {}),
            }
        except Exception as e:
            raise SmartToolError(
                tool="screenshot",
                action="capture",
                reason=str(e),
                suggestion="Ensure page is loaded",
            ) from e
