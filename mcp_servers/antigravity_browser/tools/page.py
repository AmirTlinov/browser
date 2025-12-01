"""
Page analysis and content extraction tools.

Provides comprehensive page understanding capabilities:
- analyze_page: Primary tool for understanding page structure and content
- extract_content: Extract specific content types (main, table, links, headings, images)
- wait_for: Wait for various conditions (navigation, load, text, element, network_idle)
- get_page_context: Quick access to cached page state
- get_page_info: Current page metadata (URL, title, scroll, viewport)

All functions use robust error handling and the context manager pattern for session management.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..config import BrowserConfig
from .base import PageContext, SmartToolError, get_session

# Global page context for caching
_page_context: PageContext | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# analyze_page - Primary page understanding tool
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_page(config: BrowserConfig, include_content: bool = True) -> dict[str, Any]:
    """
    Analyze the current page and return a structured summary for AI understanding.

    This is the PRIMARY tool an AI should use to understand what's on a page.
    Returns:
    - Page metadata (URL, title)
    - All interactive elements (buttons, links, inputs, forms)
    - Main content summary (filtered, no CSS/scripts)
    - Suggested actions based on page type

    Use this BEFORE attempting any interactions to understand the page structure.

    Args:
        config: Browser configuration
        include_content: Include main content text in analysis

    Returns:
        Dictionary with 'analysis' and 'target' keys

    Raises:
        SmartToolError: If page analysis fails or returns null
    """
    global _page_context

    with get_session(config) as (session, target):
        # Robust page analysis with proper filtering
        js = '''
        (() => {
            const result = {
                url: window.location.href,
                title: document.title,
                pageType: 'unknown',
                forms: [],
                links: [],
                buttons: [],
                inputs: [],
                mainContent: '',
                suggestedActions: []
            };

            // Helper: Check if element is visible
            const isVisible = (el) => {
                if (!el) return false;
                const style = getComputedStyle(el);
                return style.display !== 'none' &&
                       style.visibility !== 'hidden' &&
                       style.opacity !== '0' &&
                       el.offsetWidth > 0 &&
                       el.offsetHeight > 0;
            };

            // Helper: Check if text looks like CSS/JS code
            const looksLikeCode = (text) => {
                if (!text || text.length < 5) return false;
                // CSS patterns
                if (text.match(/[.#][a-zA-Z_-]+\\s*\\{/)) return true;  // .class{ or #id{
                if (text.match(/\\{[^}]*:[^}]*\\}/)) return true;  // {property: value}
                if (text.match(/;\\s*[a-z-]+\\s*:/i)) return true;  // ; property:
                if (text.match(/^[a-z-]+:[^:]+;/i)) return true;  // property: value;
                if ((text.match(/\\{/g) || []).length > 2) return true;  // Multiple {
                if ((text.match(/:/g) || []).length > 3 && (text.match(/;/g) || []).length > 2) return true;  // Many : and ;
                // JS patterns
                if (text.match(/^(function|const |let |var |=>|\\(\\))/)) return true;
                return false;
            };

            // Helper: Get clean text (no CSS, no scripts)
            const getCleanText = (el) => {
                if (!el) return '';
                const clone = el.cloneNode(true);
                // Remove script, style, noscript tags
                clone.querySelectorAll('script, style, noscript, svg, path, link[rel="stylesheet"]').forEach(e => e.remove());
                let text = clone.textContent || '';
                // Clean up whitespace
                text = text.replace(/\\s+/g, ' ').trim();
                // Skip if looks like CSS/JS
                if (looksLikeCode(text)) return '';
                return text;
            };

            // Helper: Deduplicate array by key
            const dedupe = (arr, keyFn) => {
                const seen = new Set();
                return arr.filter(item => {
                    const key = keyFn(item);
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });
            };

            // Helper: Recursively get all elements including Shadow DOM
            const getAllElements = (root, selector) => {
                const elements = [];
                const collect = (node) => {
                    if (!node) return;
                    // Query in current context
                    if (node.querySelectorAll) {
                        node.querySelectorAll(selector).forEach(el => elements.push(el));
                    }
                    // Traverse shadow roots
                    if (node.querySelectorAll) {
                        node.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) {
                                collect(el.shadowRoot);
                            }
                        });
                    }
                };
                collect(root);
                return elements;
            };

            // Helper: Get iframe contents (same-origin only)
            const getIframeData = () => {
                const iframeData = [];
                document.querySelectorAll('iframe').forEach((iframe, idx) => {
                    try {
                        const doc = iframe.contentDocument || iframe.contentWindow?.document;
                        if (doc) {
                            const forms = [];
                            doc.querySelectorAll('form').forEach(form => {
                                forms.push({
                                    action: form.action,
                                    method: form.method,
                                    fieldCount: form.querySelectorAll('input, select, textarea').length
                                });
                            });
                            const buttons = [];
                            doc.querySelectorAll('button, [role="button"]').forEach(btn => {
                                const text = getCleanText(btn);
                                if (text && text.length < 60) buttons.push(text);
                            });
                            const inputs = [];
                            doc.querySelectorAll('input:not([type="hidden"]), textarea').forEach(inp => {
                                inputs.push({
                                    type: inp.type || 'text',
                                    name: inp.name || inp.id,
                                    placeholder: inp.placeholder
                                });
                            });
                            if (forms.length || buttons.length || inputs.length) {
                                iframeData.push({
                                    index: idx,
                                    src: iframe.src || 'inline',
                                    forms, buttons: buttons.slice(0, 10), inputs: inputs.slice(0, 10)
                                });
                            }
                        }
                    } catch (e) {
                        // Cross-origin iframe - can't access
                        iframeData.push({
                            index: idx,
                            src: iframe.src,
                            crossOrigin: true
                        });
                    }
                });
                return iframeData;
            };

            // Detect page type
            const hasPassword = document.querySelector('input[type="password"]');
            const hasSearchInput = document.querySelector('input[type="search"], input[name="q"], textarea[name="q"], input[name*="search" i], [role="searchbox"], [role="combobox"]');
            const hasLoginForm = document.querySelector('form[action*="login" i], form[action*="signin" i], form[action*="auth" i]');
            const hasCheckout = document.querySelector('form[action*="checkout" i], form[action*="payment" i], .checkout, #checkout');
            const hasArticle = document.querySelector('article, [role="article"], .article, .post-content, .entry-content');
            const hasTables = document.querySelectorAll('table tbody tr').length > 3;

            if (hasPassword && hasLoginForm) {
                result.pageType = 'login';
                result.suggestedActions.push('fill_form with credentials, then submit=true');
            } else if (hasPassword) {
                result.pageType = 'login';
                result.suggestedActions.push('fill_form with credentials');
            } else if (hasSearchInput) {
                result.pageType = 'search';
                result.suggestedActions.push('search_page(query="your search term")');
            } else if (hasCheckout) {
                result.pageType = 'checkout';
                result.suggestedActions.push('fill_form with payment/shipping details');
            } else if (hasArticle) {
                result.pageType = 'article';
                result.suggestedActions.push('extract_content(content_type="main")');
            } else if (hasTables) {
                result.pageType = 'data_table';
                result.suggestedActions.push('extract_content(content_type="table")');
            } else if (document.querySelectorAll('a[href]').length > 15) {
                result.pageType = 'listing';
                result.suggestedActions.push('click_element(text="item name") or extract_content(content_type="links")');
            }

            // Analyze forms with fields
            document.querySelectorAll('form').forEach((form, formIndex) => {
                const fields = [];
                form.querySelectorAll('input, select, textarea').forEach(el => {
                    if (el.type === 'hidden' || !isVisible(el)) return;

                    // Get label
                    let label = '';
                    if (el.labels && el.labels[0]) {
                        label = getCleanText(el.labels[0]);
                    } else if (el.getAttribute('aria-label')) {
                        label = el.getAttribute('aria-label');
                    } else if (el.placeholder) {
                        label = el.placeholder;
                    }

                    fields.push({
                        type: el.tagName.toLowerCase() === 'select' ? 'select' : (el.type || 'text'),
                        name: el.name || el.id || '',
                        label: label.substring(0, 50),
                        placeholder: (el.placeholder || '').substring(0, 50),
                        required: el.required,
                        hasValue: !!el.value && el.type !== 'password'
                    });
                });

                if (fields.length > 0) {
                    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
                    result.forms.push({
                        index: formIndex,
                        id: form.id || null,
                        name: form.name || null,
                        action: form.action ? new URL(form.action, window.location.href).pathname : null,
                        method: (form.method || 'get').toUpperCase(),
                        fields: fields.slice(0, 15),
                        submitText: submitBtn ? getCleanText(submitBtn).substring(0, 30) || 'Submit' : null
                    });
                }
            });

            // Collect visible links (deduplicated) - including Shadow DOM
            const links = [];
            getAllElements(document, 'a[href]').forEach(a => {
                if (!isVisible(a)) return;
                const text = getCleanText(a).substring(0, 80);
                const href = a.href;
                if (!text || href.startsWith('javascript:') || href === '#') return;
                const inShadow = a.getRootNode() !== document;
                links.push({
                    text: text,
                    href: href,
                    isExternal: a.hostname !== window.location.hostname,
                    ...(inShadow && { inShadowDOM: true })
                });
            });
            result.links = dedupe(links, l => l.href).slice(0, 30);

            // Collect visible buttons (deduplicated) - including Shadow DOM
            const buttons = [];
            getAllElements(document, 'button, input[type="button"], input[type="submit"], [role="button"]').forEach(btn => {
                if (!isVisible(btn)) return;
                const text = getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '';
                // Skip empty, too long, or CSS-like text
                if (!text || text.length > 60 || looksLikeCode(text)) return;
                const inShadow = btn.getRootNode() !== document;
                buttons.push({
                    text: text.substring(0, 50),
                    type: btn.type || 'button',
                    disabled: btn.disabled || false,
                    ...(inShadow && { inShadowDOM: true })
                });
            });
            result.buttons = dedupe(buttons, b => b.text).slice(0, 20);

            // Collect standalone inputs (not in forms) - including Shadow DOM
            getAllElements(document, 'input:not(form input), textarea:not(form textarea)').forEach(el => {
                if (el.type === 'hidden' || !isVisible(el)) return;
                const label = el.getAttribute('aria-label') || el.placeholder || el.name || '';
                if (!label) return;
                const inShadow = el.getRootNode() !== document;
                result.inputs.push({
                    type: el.type || 'text',
                    name: el.name || el.id || '',
                    label: label.substring(0, 50),
                    ...(inShadow && { inShadowDOM: true })
                });
            });
            result.inputs = result.inputs.slice(0, 15);

            // Collect iframe data
            result.iframes = getIframeData();

            // Extract main content (filtered, clean text only)
            const mainSelectors = ['main', 'article', '[role="main"]', '.content', '.main-content', '#content', '#main'];
            let mainEl = null;
            for (const sel of mainSelectors) {
                mainEl = document.querySelector(sel);
                if (mainEl) break;
            }
            if (!mainEl) mainEl = document.body;

            const contentParts = [];
            const walker = document.createTreeWalker(mainEl, NodeFilter.SHOW_ELEMENT);
            let node;
            while ((node = walker.nextNode()) && contentParts.length < 30) {
                // Skip invisible, script, style elements
                if (!isVisible(node)) continue;
                if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'NAV', 'HEADER', 'FOOTER', 'HEAD', 'LINK', 'META'].includes(node.tagName)) continue;

                // Get direct text content (not from children)
                const directText = Array.from(node.childNodes)
                    .filter(n => n.nodeType === Node.TEXT_NODE)
                    .map(n => n.textContent.trim())
                    .join(' ')
                    .trim();

                // Use looksLikeCode for robust CSS/JS filtering
                if (directText.length > 20 && !looksLikeCode(directText)) {
                    contentParts.push(directText.substring(0, 200));
                }
            }
            result.mainContent = contentParts.join(' ').substring(0, 1500);

            return result;
        })()
        '''

        analysis = session.eval_js(js)

        if not analysis:
            raise SmartToolError(
                tool="analyze_page",
                action="evaluate",
                reason="Page analysis returned null",
                suggestion="Page may still be loading. Try wait_for(condition='load') first"
            )

        # Cache context
        _page_context = PageContext(
            url=analysis.get("url", ""),
            title=analysis.get("title", ""),
            forms=analysis.get("forms", []),
            links=analysis.get("links", []),
            buttons=analysis.get("buttons", []),
            inputs=analysis.get("inputs", []),
            text_content=analysis.get("mainContent", "") if include_content else "",
            timestamp=time.time()
        )

        return {
            "analysis": analysis,
            "target": target["id"]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# extract_content - Structured content extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_content(
    config: BrowserConfig,
    content_type: str = "main",
    selector: str | None = None
) -> dict[str, Any]:
    """
    Extract structured content from the page.

    Args:
        config: Browser configuration
        content_type: What to extract:
            - "main": Main article/content text (cleaned, no CSS)
            - "table": All tables as structured data
            - "links": All links with text and URLs (deduplicated)
            - "headings": Document outline (h1-h6)
            - "images": All images with alt text and URLs
            - "all": Everything combined
        selector: Optional CSS selector to limit extraction scope

    Returns:
        Dictionary with extracted content, content_type, and target

    Raises:
        SmartToolError: If extraction fails or selector not found
    """
    with get_session(config) as (session, target):
        js = f'''
        (() => {{
            const contentType = {json.dumps(content_type)};
            const customSelector = {json.dumps(selector)};

            const scope = customSelector ? document.querySelector(customSelector) : document.body;
            if (!scope) {{
                return {{ error: true, reason: 'Selector not found: ' + customSelector }};
            }}

            // Helper: Check visibility
            const isVisible = (el) => {{
                if (!el) return false;
                const style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }};

            // Helper: Get clean text
            const getCleanText = (el) => {{
                if (!el) return '';
                const clone = el.cloneNode(true);
                clone.querySelectorAll('script, style, noscript, svg').forEach(e => e.remove());
                return (clone.textContent || '').replace(/\\s+/g, ' ').trim();
            }};

            // Helper: Deduplicate
            const dedupe = (arr, keyFn) => {{
                const seen = new Set();
                return arr.filter(item => {{
                    const key = keyFn(item);
                    if (!key || seen.has(key)) return false;
                    seen.add(key);
                    return true;
                }});
            }};

            const result = {{}};

            // Main content extraction
            if (contentType === 'main' || contentType === 'all') {{
                const mainSelectors = ['article', 'main', '[role="main"]', '.content', '.article', '.post', '.entry-content'];
                let mainEl = null;
                for (const sel of mainSelectors) {{
                    mainEl = scope.querySelector(sel);
                    if (mainEl) break;
                }}
                if (!mainEl) mainEl = scope;

                const paragraphs = [];
                mainEl.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li').forEach(el => {{
                    if (!isVisible(el)) return;
                    const text = getCleanText(el);
                    if (text.length > 15 && !text.match(/^[.#{{}}:;]|function|const |var /)) {{
                        paragraphs.push({{
                            tag: el.tagName.toLowerCase(),
                            text: text.substring(0, 500)
                        }});
                    }}
                }});

                result.main = {{
                    title: document.title,
                    url: window.location.href,
                    paragraphs: paragraphs.slice(0, 50)
                }};
            }}

            // Tables extraction
            if (contentType === 'table' || contentType === 'all') {{
                const tables = [];
                scope.querySelectorAll('table').forEach((table, idx) => {{
                    if (!isVisible(table)) return;

                    const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th'))
                        .map(th => getCleanText(th))
                        .filter(t => t);

                    const rows = [];
                    table.querySelectorAll('tbody tr, tr').forEach((tr, rowIdx) => {{
                        if (rowIdx === 0 && headers.length > 0) return;  // Skip header row
                        if (rows.length >= 50) return;  // Limit rows

                        const cells = Array.from(tr.querySelectorAll('td, th'))
                            .map(td => getCleanText(td).substring(0, 200));
                        if (cells.some(c => c)) {{
                            rows.push(cells);
                        }}
                    }});

                    if (rows.length > 0 || headers.length > 0) {{
                        tables.push({{
                            index: idx,
                            headers: headers,
                            rows: rows,
                            rowCount: rows.length
                        }});
                    }}
                }});
                result.tables = tables.slice(0, 10);
            }}

            // Links extraction
            if (contentType === 'links' || contentType === 'all') {{
                const links = [];
                scope.querySelectorAll('a[href]').forEach(a => {{
                    if (!isVisible(a)) return;
                    const text = getCleanText(a);
                    const href = a.href;
                    if (!text || text.length < 2 || href.startsWith('javascript:')) return;
                    links.push({{
                        text: text.substring(0, 100),
                        href: href,
                        isExternal: a.hostname !== window.location.hostname
                    }});
                }});
                result.links = dedupe(links, l => l.href).slice(0, 50);
            }}

            // Headings extraction
            if (contentType === 'headings' || contentType === 'all') {{
                const headings = [];
                scope.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {{
                    if (!isVisible(h)) return;
                    const text = getCleanText(h);
                    if (text && text.length > 1) {{
                        headings.push({{
                            level: parseInt(h.tagName[1]),
                            text: text.substring(0, 150)
                        }});
                    }}
                }});
                result.headings = headings.slice(0, 30);
            }}

            // Images extraction
            if (contentType === 'images' || contentType === 'all') {{
                const images = [];
                scope.querySelectorAll('img[src]').forEach(img => {{
                    if (!isVisible(img)) return;
                    const src = img.src;
                    if (src.startsWith('data:') || src.includes('pixel') || src.includes('tracking')) return;
                    images.push({{
                        src: src,
                        alt: img.alt || '',
                        width: img.naturalWidth || img.width,
                        height: img.naturalHeight || img.height
                    }});
                }});
                result.images = dedupe(images, i => i.src).slice(0, 30);
            }}

            return result;
        }})()
        '''

        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="extract_content",
                action="evaluate",
                reason="Extraction returned null",
                suggestion="Check page has loaded completely"
            )

        if result.get("error"):
            raise SmartToolError(
                tool="extract_content",
                action="extract",
                reason=result.get("reason", "Unknown error"),
                suggestion="Check selector is valid"
            )

        return {
            "content": result,
            "content_type": content_type,
            "target": target["id"]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# wait_for - Smart waiting for conditions
# ═══════════════════════════════════════════════════════════════════════════════

def wait_for(
    config: BrowserConfig,
    condition: str,
    timeout: float = 10.0,
    text: str | None = None,
    selector: str | None = None
) -> dict[str, Any]:
    """
    Wait for a condition before proceeding.

    Args:
        config: Browser configuration
        condition: What to wait for:
            - "navigation": Page URL change
            - "load": Page fully loaded
            - "text": Specific text appears on page
            - "element": Element matching selector appears
            - "network_idle": No network activity for 500ms
        timeout: Maximum wait time in seconds
        text: Text to wait for (when condition="text")
        selector: CSS selector (when condition="element")

    Returns:
        Dictionary with success status, elapsed time, and condition details

    Raises:
        SmartToolError: If condition or parameters are invalid

    Use this after actions that trigger page changes.
    """
    valid_conditions = ["navigation", "load", "text", "element", "network_idle"]
    if condition not in valid_conditions:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason=f"Invalid condition: {condition}",
            suggestion=f"Use one of: {', '.join(valid_conditions)}"
        )

    if condition == "text" and not text:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason="text parameter required for condition='text'",
            suggestion="Provide text='expected text'"
        )

    if condition == "element" and not selector:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason="selector parameter required for condition='element'",
            suggestion="Provide selector='css selector'"
        )

    with get_session(config) as (session, target):
        start_time = time.time()
        start_url = session.eval_js("window.location.href")

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time

            if condition == "navigation":
                current_url = session.eval_js("window.location.href")
                if current_url != start_url:
                    return {
                        "success": True,
                        "condition": condition,
                        "elapsed": round(elapsed, 2),
                        "old_url": start_url,
                        "new_url": current_url,
                        "target": target["id"]
                    }

            elif condition == "load":
                ready_state = session.eval_js("document.readyState")
                if ready_state == "complete":
                    return {
                        "success": True,
                        "condition": condition,
                        "elapsed": round(elapsed, 2),
                        "target": target["id"]
                    }

            elif condition == "text" and text:
                found = session.eval_js(f"document.body.innerText.includes({json.dumps(text)})")
                if found:
                    return {
                        "success": True,
                        "condition": condition,
                        "text": text,
                        "elapsed": round(elapsed, 2),
                        "target": target["id"]
                    }

            elif condition == "element" and selector:
                js = f"document.querySelector({json.dumps(selector)}) !== null"
                found = session.eval_js(js)
                if found:
                    return {
                        "success": True,
                        "condition": condition,
                        "selector": selector,
                        "elapsed": round(elapsed, 2),
                        "target": target["id"]
                    }

            elif condition == "network_idle":
                # Check if page has been stable
                js = '''
                (() => {
                    if (!window._networkIdleTracker) {
                        window._networkIdleTracker = { count: 0, lastActivity: Date.now() };
                        const observer = new PerformanceObserver((list) => {
                            window._networkIdleTracker.count++;
                            window._networkIdleTracker.lastActivity = Date.now();
                        });
                        observer.observe({ entryTypes: ['resource'] });
                    }
                    return Date.now() - window._networkIdleTracker.lastActivity > 500;
                })()
                '''
                is_idle = session.eval_js(js)
                if is_idle:
                    return {
                        "success": True,
                        "condition": condition,
                        "elapsed": round(elapsed, 2),
                        "target": target["id"]
                    }

            time.sleep(0.15)

        return {
            "success": False,
            "condition": condition,
            "timeout": timeout,
            "elapsed": round(time.time() - start_time, 2),
            "suggestion": f"Condition '{condition}' not met within {timeout}s",
            "target": target["id"]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# get_page_context - Quick context access
# ═══════════════════════════════════════════════════════════════════════════════

def get_page_context(config: BrowserConfig) -> dict[str, Any]:
    """
    Get cached page context or refresh if stale.

    Use for quick access to page information without re-analyzing.
    Returns the last analyzed page state if still fresh (< 5 seconds old).

    Args:
        config: Browser configuration

    Returns:
        Dictionary with cached or fresh page context
    """
    global _page_context

    if _page_context and not _page_context.is_stale():
        return {
            "cached": True,
            "url": _page_context.url,
            "title": _page_context.title,
            "forms_count": len(_page_context.forms),
            "links_count": len(_page_context.links),
            "buttons_count": len(_page_context.buttons),
            "age_seconds": round(time.time() - _page_context.timestamp, 1)
        }

    # Refresh context
    result = analyze_page(config)
    return {
        "cached": False,
        "analysis": result.get("analysis"),
        "target": result.get("target")
    }


# ═══════════════════════════════════════════════════════════════════════════════
# get_page_info - Page information wrapper (uses active tab)
# ═══════════════════════════════════════════════════════════════════════════════

def get_page_info(config: BrowserConfig) -> dict[str, Any]:
    """
    Get current page information (URL, title, scroll position, viewport size).

    Uses the active tab set by switch_tab() if available.

    Args:
        config: Browser configuration

    Returns:
        Dictionary with pageInfo (URL, title, scroll, viewport) and target

    Raises:
        SmartToolError: If unable to get page information
    """
    with get_session(config) as (session, target):
        try:
            js = (
                "(() => ({"
                "  url: window.location.href,"
                "  title: document.title,"
                "  scrollX: window.scrollX,"
                "  scrollY: window.scrollY,"
                "  innerWidth: window.innerWidth,"
                "  innerHeight: window.innerHeight,"
                "  documentWidth: document.documentElement.scrollWidth,"
                "  documentHeight: document.documentElement.scrollHeight"
                "}))()"
            )
            result = session.eval_js(js)
            return {"pageInfo": result, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="get_page_info",
                action="get",
                reason=str(e),
                suggestion="Ensure the page is loaded and responsive"
            ) from e
