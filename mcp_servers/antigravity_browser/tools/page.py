"""
Page analysis and content extraction tools with pagination support.

Implements Overview + Detail pattern for AI-friendly context management:
- Overview mode (default): Returns compact summary with counts and hints
- Detail mode: Returns paginated data for specific sections

Key functions:
- analyze_page: Primary tool for understanding page structure
- extract_content: Extract specific content types with pagination
- wait_for: Wait for various conditions
- get_page_context: Quick access to cached page state
- get_page_info: Current page metadata
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..config import BrowserConfig
from .base import PageContext, SmartToolError, get_session

# Global page context for caching
_page_context: PageContext | None = None

# Default pagination limits
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


# ═══════════════════════════════════════════════════════════════════════════════
# analyze_page - Primary page understanding tool with pagination
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_page(
    config: BrowserConfig,
    detail: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    form_index: int | None = None,
    include_content: bool = False,
) -> dict[str, Any]:
    """
    Analyze the current page with Overview + Detail pattern.

    OVERVIEW MODE (detail=None, default):
    Returns compact summary optimized for AI context:
    - Page metadata (URL, title, pageType)
    - Counts of all elements (forms, links, buttons, inputs)
    - Preview samples (first few items of each type)
    - Suggested actions based on page type
    - Hints showing how to get more details

    DETAIL MODES:
    - detail="forms": List all forms with field counts
    - detail="forms" + form_index=N: Full details of form N with all fields
    - detail="links": Paginated list of links (use offset/limit)
    - detail="buttons": All buttons on page
    - detail="inputs": Standalone inputs (not in forms)
    - detail="content": Main page content (paginated)

    Args:
        config: Browser configuration
        detail: Section to get details for (None for overview)
        offset: Starting index for paginated results
        limit: Maximum items to return (default 10, max 50)
        form_index: Specific form index when detail="forms"
        include_content: Include content preview in overview (default False)

    Returns:
        Dictionary with overview or detail data, plus navigation hints

    Examples:
        # Get page overview
        analyze_page()

        # Get details of first form
        analyze_page(detail="forms", form_index=0)

        # Get links 20-30
        analyze_page(detail="links", offset=20, limit=10)
    """
    global _page_context

    # Validate parameters
    valid_details = [None, "forms", "links", "buttons", "inputs", "content"]
    if detail not in valid_details:
        raise SmartToolError(
            tool="analyze_page",
            action="validate",
            reason=f"Invalid detail: {detail}",
            suggestion=f"Use one of: {', '.join(str(d) for d in valid_details)}"
        )

    limit = min(limit, MAX_LIMIT)

    with get_session(config) as (session, target):
        # JavaScript for comprehensive page analysis
        js = _build_analyze_js(detail, offset, limit, form_index, include_content)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="analyze_page",
                action="evaluate",
                reason="Page analysis returned null",
                suggestion="Page may still be loading. Try wait_for(condition='load') first"
            )

        if result.get("error"):
            raise SmartToolError(
                tool="analyze_page",
                action="analyze",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Check page state")
            )

        # Cache context for overview mode
        if detail is None and "overview" in result:
            overview = result["overview"]
            _page_context = PageContext(
                url=overview.get("url", ""),
                title=overview.get("title", ""),
                forms=[],  # Only counts in overview
                links=[],
                buttons=[],
                inputs=[],
                text_content="",
                timestamp=time.time()
            )

        result["target"] = target["id"]
        return result


def _build_analyze_js(
    detail: str | None,
    offset: int,
    limit: int,
    form_index: int | None,
    include_content: bool
) -> str:
    """Build JavaScript for page analysis based on mode."""

    # Common helpers
    helpers = '''
    const isVisible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' &&
               style.visibility !== 'hidden' &&
               style.opacity !== '0' &&
               el.offsetWidth > 0 &&
               el.offsetHeight > 0;
    };

    const looksLikeCode = (text) => {
        if (!text || text.length < 5) return false;
        if (text.match(/[.#][a-zA-Z_-]+\\s*\\{/)) return true;
        if (text.match(/\\{[^}]*:[^}]*\\}/)) return true;
        if ((text.match(/\\{/g) || []).length > 2) return true;
        if ((text.match(/:/g) || []).length > 3 && (text.match(/;/g) || []).length > 2) return true;
        if (text.match(/^(function|const |let |var |=>|\\(\\))/)) return true;
        return false;
    };

    const getCleanText = (el) => {
        if (!el) return '';
        const clone = el.cloneNode(true);
        clone.querySelectorAll('script, style, noscript, svg, path').forEach(e => e.remove());
        let text = clone.textContent || '';
        text = text.replace(/\\s+/g, ' ').trim();
        if (looksLikeCode(text)) return '';
        return text;
    };

    const dedupe = (arr, keyFn) => {
        const seen = new Set();
        return arr.filter(item => {
            const key = keyFn(item);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    };

    const getAllElements = (root, selector) => {
        const elements = [];
        const collect = (node) => {
            if (!node) return;
            if (node.querySelectorAll) {
                node.querySelectorAll(selector).forEach(el => elements.push(el));
            }
            if (node.querySelectorAll) {
                node.querySelectorAll('*').forEach(el => {
                    if (el.shadowRoot) collect(el.shadowRoot);
                });
            }
        };
        collect(root);
        return elements;
    };
    '''

    if detail is None:
        # OVERVIEW MODE - compact summary
        return f'''
        (() => {{
            {helpers}

            const result = {{ overview: {{}} }};
            const o = result.overview;

            // Basic info
            o.url = window.location.href;
            o.title = document.title;

            // Detect page type
            const hasPassword = document.querySelector('input[type="password"]');
            const hasSearchInput = document.querySelector('input[type="search"], input[name="q"], [role="searchbox"]');
            const hasLoginForm = document.querySelector('form[action*="login" i], form[action*="signin" i]');
            const hasCheckout = document.querySelector('form[action*="checkout" i], form[action*="payment" i]');
            const hasArticle = document.querySelector('article, [role="article"], .article');
            const hasTables = document.querySelectorAll('table tbody tr').length > 3;

            if (hasPassword && hasLoginForm) o.pageType = 'login';
            else if (hasPassword) o.pageType = 'auth';
            else if (hasSearchInput) o.pageType = 'search';
            else if (hasCheckout) o.pageType = 'checkout';
            else if (hasArticle) o.pageType = 'article';
            else if (hasTables) o.pageType = 'data_table';
            else if (document.querySelectorAll('a[href]').length > 20) o.pageType = 'listing';
            else o.pageType = 'generic';

            // Count elements
            const forms = document.querySelectorAll('form');
            const allLinks = getAllElements(document, 'a[href]').filter(a => isVisible(a) && !a.href.startsWith('javascript:'));
            const allButtons = getAllElements(document, 'button, input[type="button"], input[type="submit"], [role="button"]').filter(b => isVisible(b));
            const standaloneInputs = getAllElements(document, 'input:not(form input), textarea:not(form textarea)').filter(i => i.type !== 'hidden' && isVisible(i));

            o.counts = {{
                forms: forms.length,
                links: allLinks.length,
                buttons: allButtons.length,
                inputs: standaloneInputs.length
            }};

            // Preview - first few items of each type
            o.preview = {{}};

            // Forms preview
            if (forms.length > 0) {{
                o.preview.forms = [];
                forms.forEach((form, idx) => {{
                    if (idx >= 3) return;
                    const fields = form.querySelectorAll('input:not([type="hidden"]), select, textarea');
                    const visibleFields = Array.from(fields).filter(f => isVisible(f)).length;
                    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
                    o.preview.forms.push({{
                        index: idx,
                        fields: visibleFields,
                        submit: submitBtn ? getCleanText(submitBtn).substring(0, 20) || 'Submit' : null
                    }});
                }});
            }}

            // Top links (first 5 unique texts)
            const linkTexts = [];
            for (const a of allLinks) {{
                const text = getCleanText(a).substring(0, 30);
                if (text && !linkTexts.includes(text) && linkTexts.length < 5) {{
                    linkTexts.push(text);
                }}
            }}
            if (linkTexts.length) o.preview.topLinks = linkTexts;

            // Top buttons (first 5 unique texts)
            const btnTexts = [];
            for (const btn of allButtons) {{
                const text = (getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '').substring(0, 25);
                if (text && !looksLikeCode(text) && !btnTexts.includes(text) && btnTexts.length < 5) {{
                    btnTexts.push(text);
                }}
            }}
            if (btnTexts.length) o.preview.topButtons = btnTexts;

            // Content preview (optional)
            {'if (true) {' if include_content else 'if (false) {'}
                const mainSelectors = ['main', 'article', '[role="main"]', '.content'];
                let mainEl = null;
                for (const sel of mainSelectors) {{
                    mainEl = document.querySelector(sel);
                    if (mainEl) break;
                }}
                if (!mainEl) mainEl = document.body;

                const firstP = mainEl.querySelector('p');
                if (firstP) {{
                    const text = getCleanText(firstP);
                    if (text.length > 20) o.preview.content = text.substring(0, 150) + (text.length > 150 ? '...' : '');
                }}
            }}

            // Suggested actions based on page type
            o.suggestedActions = [];
            if (o.pageType === 'login' || o.pageType === 'auth') {{
                o.suggestedActions.push('fill_form(data={{...}}, submit=true)');
            }} else if (o.pageType === 'search') {{
                o.suggestedActions.push('search_page(query="...")');
            }} else if (o.pageType === 'article') {{
                o.suggestedActions.push('extract_content(content_type="main")');
            }} else if (o.pageType === 'data_table') {{
                o.suggestedActions.push('extract_content(content_type="table")');
            }} else if (o.pageType === 'listing') {{
                o.suggestedActions.push('click_element(text="...")');
            }}

            // Hints for getting more details
            o.hints = {{}};
            if (o.counts.forms > 0) {{
                o.hints.forms = "detail='forms' form_index=N for form fields";
            }}
            if (o.counts.links > 5) {{
                o.hints.links = "detail='links' offset=0 limit=10";
            }}
            if (o.counts.buttons > 5) {{
                o.hints.buttons = "detail='buttons'";
            }}

            return result;
        }})()
        '''

    elif detail == "forms":
        if form_index is not None:
            # Single form with all fields
            return f'''
            (() => {{
                {helpers}
                const forms = document.querySelectorAll('form');
                const formIndex = {form_index};

                if (formIndex >= forms.length) {{
                    return {{ error: true, reason: 'Form index ' + formIndex + ' not found. Available: 0-' + (forms.length - 1) }};
                }}

                const form = forms[formIndex];
                const fields = [];

                form.querySelectorAll('input, select, textarea').forEach(el => {{
                    if (el.type === 'hidden' || !isVisible(el)) return;

                    let label = '';
                    if (el.labels && el.labels[0]) {{
                        label = getCleanText(el.labels[0]);
                    }} else if (el.getAttribute('aria-label')) {{
                        label = el.getAttribute('aria-label');
                    }} else if (el.placeholder) {{
                        label = el.placeholder;
                    }}

                    const field = {{
                        type: el.tagName.toLowerCase() === 'select' ? 'select' : (el.type || 'text'),
                        name: el.name || el.id || '',
                        label: label.substring(0, 50),
                        required: el.required
                    }};

                    if (el.placeholder) field.placeholder = el.placeholder.substring(0, 40);
                    if (el.value && el.type !== 'password') field.hasValue = true;

                    // For select, include options
                    if (el.tagName.toLowerCase() === 'select') {{
                        field.options = Array.from(el.options).slice(0, 10).map(opt => ({{
                            value: opt.value,
                            text: opt.text.substring(0, 30)
                        }}));
                        if (el.options.length > 10) {{
                            field.optionsTotal = el.options.length;
                        }}
                    }}

                    fields.push(field);
                }});

                const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');

                return {{
                    detail: 'forms',
                    form: {{
                        index: formIndex,
                        id: form.id || null,
                        name: form.name || null,
                        action: form.action ? new URL(form.action, window.location.href).pathname : null,
                        method: (form.method || 'get').toUpperCase(),
                        fields: fields,
                        submitText: submitBtn ? getCleanText(submitBtn).substring(0, 30) || 'Submit' : null
                    }}
                }};
            }})()
            '''
        else:
            # All forms overview
            return f'''
            (() => {{
                {helpers}
                const forms = document.querySelectorAll('form');
                const items = [];

                forms.forEach((form, idx) => {{
                    const fields = form.querySelectorAll('input:not([type="hidden"]), select, textarea');
                    const visibleFields = Array.from(fields).filter(f => isVisible(f));
                    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');

                    // Get field names/labels preview
                    const fieldNames = visibleFields.slice(0, 5).map(f => {{
                        if (f.labels && f.labels[0]) return getCleanText(f.labels[0]).substring(0, 20);
                        if (f.placeholder) return f.placeholder.substring(0, 20);
                        if (f.name) return f.name;
                        return f.type;
                    }});

                    items.push({{
                        index: idx,
                        id: form.id || null,
                        action: form.action ? new URL(form.action, window.location.href).pathname : null,
                        method: (form.method || 'get').toUpperCase(),
                        fieldCount: visibleFields.length,
                        fieldNames: fieldNames,
                        submitText: submitBtn ? getCleanText(submitBtn).substring(0, 25) || 'Submit' : null
                    }});
                }});

                return {{
                    detail: 'forms',
                    total: forms.length,
                    items: items,
                    hint: items.length > 0 ? "Use form_index=N to see all fields of form N" : null
                }};
            }})()
            '''

    elif detail == "links":
        return f'''
        (() => {{
            {helpers}
            const offset = {offset};
            const limit = {limit};

            const allLinks = getAllElements(document, 'a[href]').filter(a => {{
                if (!isVisible(a)) return false;
                const href = a.href;
                if (href.startsWith('javascript:') || href === '#' || href === window.location.href) return false;
                const text = getCleanText(a);
                return text && text.length > 0;
            }});

            // Dedupe by href
            const seen = new Set();
            const unique = allLinks.filter(a => {{
                if (seen.has(a.href)) return false;
                seen.add(a.href);
                return true;
            }});

            const total = unique.length;
            const items = unique.slice(offset, offset + limit).map(a => ({{
                text: getCleanText(a).substring(0, 60),
                href: a.href,
                isExternal: a.hostname !== window.location.hostname
            }}));

            const result = {{
                detail: 'links',
                total: total,
                offset: offset,
                limit: limit,
                hasMore: offset + limit < total,
                items: items
            }};

            // Navigation hints
            if (offset > 0 || offset + limit < total) {{
                result.navigation = {{}};
                if (offset > 0) {{
                    result.navigation.prev = `offset=${{Math.max(0, offset - limit)}} limit=${{limit}}`;
                }}
                if (offset + limit < total) {{
                    result.navigation.next = `offset=${{offset + limit}} limit=${{limit}}`;
                }}
            }}

            return result;
        }})()
        '''

    elif detail == "buttons":
        return f'''
        (() => {{
            {helpers}

            const allButtons = getAllElements(document, 'button, input[type="button"], input[type="submit"], [role="button"]').filter(btn => {{
                if (!isVisible(btn)) return false;
                const text = getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '';
                return text && text.length > 0 && text.length < 60 && !looksLikeCode(text);
            }});

            // Dedupe by text
            const seen = new Set();
            const items = allButtons.filter(btn => {{
                const text = (getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '').substring(0, 40);
                if (seen.has(text)) return false;
                seen.add(text);
                return true;
            }}).map(btn => {{
                const inShadow = btn.getRootNode() !== document;
                return {{
                    text: (getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '').substring(0, 40),
                    type: btn.type || 'button',
                    disabled: btn.disabled || false,
                    ...(inShadow && {{ inShadowDOM: true }})
                }};
            }});

            return {{
                detail: 'buttons',
                total: items.length,
                items: items
            }};
        }})()
        '''

    elif detail == "inputs":
        return f'''
        (() => {{
            {helpers}

            const inputs = getAllElements(document, 'input:not(form input), textarea:not(form textarea)').filter(el => {{
                return el.type !== 'hidden' && isVisible(el);
            }});

            const items = inputs.map(el => {{
                const label = el.getAttribute('aria-label') || el.placeholder || el.name || '';
                const inShadow = el.getRootNode() !== document;
                return {{
                    type: el.type || 'text',
                    name: el.name || el.id || '',
                    label: label.substring(0, 50),
                    ...(el.placeholder && {{ placeholder: el.placeholder.substring(0, 40) }}),
                    ...(inShadow && {{ inShadowDOM: true }})
                }};
            }});

            return {{
                detail: 'inputs',
                total: items.length,
                items: items
            }};
        }})()
        '''

    elif detail == "content":
        return f'''
        (() => {{
            {helpers}
            const offset = {offset};
            const limit = {limit};

            const mainSelectors = ['main', 'article', '[role="main"]', '.content', '.main-content'];
            let mainEl = null;
            for (const sel of mainSelectors) {{
                mainEl = document.querySelector(sel);
                if (mainEl) break;
            }}
            if (!mainEl) mainEl = document.body;

            const contentParts = [];
            const walker = document.createTreeWalker(mainEl, NodeFilter.SHOW_ELEMENT);
            let node;

            while ((node = walker.nextNode())) {{
                if (!isVisible(node)) continue;
                if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'NAV', 'HEADER', 'FOOTER'].includes(node.tagName)) continue;

                const directText = Array.from(node.childNodes)
                    .filter(n => n.nodeType === Node.TEXT_NODE)
                    .map(n => n.textContent.trim())
                    .join(' ')
                    .trim();

                if (directText.length > 20 && !looksLikeCode(directText)) {{
                    contentParts.push({{
                        tag: node.tagName.toLowerCase(),
                        text: directText.substring(0, 300)
                    }});
                }}
            }}

            const total = contentParts.length;
            const items = contentParts.slice(offset, offset + limit);

            const result = {{
                detail: 'content',
                total: total,
                offset: offset,
                limit: limit,
                hasMore: offset + limit < total,
                items: items
            }};

            if (offset > 0 || offset + limit < total) {{
                result.navigation = {{}};
                if (offset > 0) {{
                    result.navigation.prev = `offset=${{Math.max(0, offset - limit)}} limit=${{limit}}`;
                }}
                if (offset + limit < total) {{
                    result.navigation.next = `offset=${{offset + limit}} limit=${{limit}}`;
                }}
            }}

            return result;
        }})()
        '''

    return '(() => ({ error: true, reason: "Unknown detail type" }))()'


# ═══════════════════════════════════════════════════════════════════════════════
# extract_content - Structured content extraction with pagination
# ═══════════════════════════════════════════════════════════════════════════════

def extract_content(
    config: BrowserConfig,
    content_type: str = "overview",
    selector: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    table_index: int | None = None,
) -> dict[str, Any]:
    """
    Extract structured content from the page with pagination.

    OVERVIEW MODE (content_type="overview", default):
    Returns content structure summary:
    - Counts of paragraphs, tables, links, headings, images
    - Preview of title and first paragraph
    - Hints for getting detailed content

    DETAIL MODES with pagination:
    - content_type="main": Main text paragraphs (offset/limit)
    - content_type="table": List of tables with metadata
    - content_type="table" + table_index=N: Rows of table N (offset/limit)
    - content_type="links": All links (offset/limit)
    - content_type="headings": Document outline
    - content_type="images": Images with metadata (offset/limit)

    Args:
        config: Browser configuration
        content_type: What to extract
        selector: Optional CSS selector to limit scope
        offset: Starting index for paginated results
        limit: Maximum items (default 10, max 50)
        table_index: Specific table when content_type="table"

    Returns:
        Dictionary with content data and navigation hints

    Examples:
        # Get content overview
        extract_content()

        # Get paragraphs 10-20
        extract_content(content_type="main", offset=10, limit=10)

        # Get rows from first table
        extract_content(content_type="table", table_index=0, offset=0, limit=20)
    """
    valid_types = ["overview", "main", "table", "links", "headings", "images"]
    if content_type not in valid_types:
        raise SmartToolError(
            tool="extract_content",
            action="validate",
            reason=f"Invalid content_type: {content_type}",
            suggestion=f"Use one of: {', '.join(valid_types)}"
        )

    limit = min(limit, MAX_LIMIT)

    with get_session(config) as (session, target):
        js = _build_extract_js(content_type, selector, offset, limit, table_index)
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
                suggestion=result.get("suggestion", "Check parameters")
            )

        result["target"] = target["id"]
        return result


def _build_extract_js(
    content_type: str,
    selector: str | None,
    offset: int,
    limit: int,
    table_index: int | None
) -> str:
    """Build JavaScript for content extraction."""

    scope_js = f'''
    const customSelector = {json.dumps(selector)};
    const scope = customSelector ? document.querySelector(customSelector) : document.body;
    if (!scope) {{
        return {{ error: true, reason: 'Selector not found: ' + customSelector }};
    }}
    '''

    helpers = '''
    const isVisible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden';
    };

    const getCleanText = (el) => {
        if (!el) return '';
        const clone = el.cloneNode(true);
        clone.querySelectorAll('script, style, noscript, svg').forEach(e => e.remove());
        return (clone.textContent || '').replace(/\\s+/g, ' ').trim();
    };

    const dedupe = (arr, keyFn) => {
        const seen = new Set();
        return arr.filter(item => {
            const key = keyFn(item);
            if (!key || seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    };
    '''

    if content_type == "overview":
        return f'''
        (() => {{
            {scope_js}
            {helpers}

            const result = {{ contentType: 'overview' }};

            // Count elements
            const mainSelectors = ['article', 'main', '[role="main"]', '.content'];
            let mainEl = null;
            for (const sel of mainSelectors) {{
                mainEl = scope.querySelector(sel);
                if (mainEl) break;
            }}
            if (!mainEl) mainEl = scope;

            const paragraphs = mainEl.querySelectorAll('p');
            const tables = scope.querySelectorAll('table');
            const links = scope.querySelectorAll('a[href]');
            const headings = scope.querySelectorAll('h1, h2, h3, h4, h5, h6');
            const images = scope.querySelectorAll('img[src]');

            result.counts = {{
                paragraphs: paragraphs.length,
                tables: tables.length,
                links: links.length,
                headings: headings.length,
                images: images.length
            }};

            // Preview
            result.preview = {{
                title: document.title,
                url: window.location.href
            }};

            // First meaningful paragraph
            for (const p of paragraphs) {{
                if (!isVisible(p)) continue;
                const text = getCleanText(p);
                if (text.length > 30) {{
                    result.preview.firstParagraph = text.substring(0, 200) + (text.length > 200 ? '...' : '');
                    break;
                }}
            }}

            // Top headings
            const topHeadings = [];
            headings.forEach(h => {{
                if (!isVisible(h) || topHeadings.length >= 5) return;
                const text = getCleanText(h);
                if (text) topHeadings.push(text.substring(0, 50));
            }});
            if (topHeadings.length) result.preview.headings = topHeadings;

            // Hints
            result.hints = {{}};
            if (result.counts.paragraphs > 0) {{
                result.hints.main = "content_type='main' offset=0 limit=10";
            }}
            if (result.counts.tables > 0) {{
                result.hints.tables = "content_type='table' for list, add table_index=N for rows";
            }}
            if (result.counts.links > 10) {{
                result.hints.links = "content_type='links' offset=0 limit=20";
            }}
            if (result.counts.images > 0) {{
                result.hints.images = "content_type='images' offset=0 limit=10";
            }}

            return result;
        }})()
        '''

    elif content_type == "main":
        return f'''
        (() => {{
            {scope_js}
            {helpers}
            const offset = {offset};
            const limit = {limit};

            const mainSelectors = ['article', 'main', '[role="main"]', '.content', '.post'];
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

            const total = paragraphs.length;
            const items = paragraphs.slice(offset, offset + limit);

            const result = {{
                contentType: 'main',
                total: total,
                offset: offset,
                limit: limit,
                hasMore: offset + limit < total,
                items: items
            }};

            if (offset > 0 || offset + limit < total) {{
                result.navigation = {{}};
                if (offset > 0) {{
                    result.navigation.prev = `offset=${{Math.max(0, offset - limit)}} limit=${{limit}}`;
                }}
                if (offset + limit < total) {{
                    result.navigation.next = `offset=${{offset + limit}} limit=${{limit}}`;
                }}
            }}

            return result;
        }})()
        '''

    elif content_type == "table":
        if table_index is not None:
            # Specific table rows
            return f'''
            (() => {{
                {scope_js}
                {helpers}
                const tableIndex = {table_index};
                const offset = {offset};
                const limit = {limit};

                const tables = scope.querySelectorAll('table');
                if (tableIndex >= tables.length) {{
                    return {{ error: true, reason: 'Table index ' + tableIndex + ' not found. Available: 0-' + (tables.length - 1) }};
                }}

                const table = tables[tableIndex];

                // Get headers
                const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th'))
                    .map(th => getCleanText(th))
                    .filter(t => t);

                // Get all rows
                const allRows = [];
                table.querySelectorAll('tbody tr, tr').forEach((tr, rowIdx) => {{
                    if (rowIdx === 0 && headers.length > 0) return;
                    const cells = Array.from(tr.querySelectorAll('td, th'))
                        .map(td => getCleanText(td).substring(0, 150));
                    if (cells.some(c => c)) {{
                        allRows.push(cells);
                    }}
                }});

                const total = allRows.length;
                const rows = allRows.slice(offset, offset + limit);

                const result = {{
                    contentType: 'table',
                    tableIndex: tableIndex,
                    headers: headers,
                    total: total,
                    offset: offset,
                    limit: limit,
                    hasMore: offset + limit < total,
                    rows: rows
                }};

                if (offset > 0 || offset + limit < total) {{
                    result.navigation = {{}};
                    if (offset > 0) {{
                        result.navigation.prev = `offset=${{Math.max(0, offset - limit)}} limit=${{limit}}`;
                    }}
                    if (offset + limit < total) {{
                        result.navigation.next = `offset=${{offset + limit}} limit=${{limit}}`;
                    }}
                }}

                return result;
            }})()
            '''
        else:
            # List of tables
            return f'''
            (() => {{
                {scope_js}
                {helpers}

                const tables = scope.querySelectorAll('table');
                const items = [];

                tables.forEach((table, idx) => {{
                    if (!isVisible(table)) return;

                    const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th'))
                        .map(th => getCleanText(th).substring(0, 30))
                        .filter(t => t);

                    const rowCount = table.querySelectorAll('tbody tr, tr').length - (headers.length > 0 ? 1 : 0);

                    items.push({{
                        index: idx,
                        headers: headers.slice(0, 8),
                        headerCount: headers.length,
                        rowCount: Math.max(0, rowCount)
                    }});
                }});

                return {{
                    contentType: 'table',
                    total: items.length,
                    items: items,
                    hint: items.length > 0 ? "Use table_index=N offset=0 limit=20 to get table rows" : null
                }};
            }})()
            '''

    elif content_type == "links":
        return f'''
        (() => {{
            {scope_js}
            {helpers}
            const offset = {offset};
            const limit = {limit};

            const allLinks = [];
            scope.querySelectorAll('a[href]').forEach(a => {{
                if (!isVisible(a)) return;
                const text = getCleanText(a);
                const href = a.href;
                if (!text || text.length < 2 || href.startsWith('javascript:')) return;
                allLinks.push({{
                    text: text.substring(0, 80),
                    href: href,
                    isExternal: a.hostname !== window.location.hostname
                }});
            }});

            const unique = dedupe(allLinks, l => l.href);
            const total = unique.length;
            const items = unique.slice(offset, offset + limit);

            const result = {{
                contentType: 'links',
                total: total,
                offset: offset,
                limit: limit,
                hasMore: offset + limit < total,
                items: items
            }};

            if (offset > 0 || offset + limit < total) {{
                result.navigation = {{}};
                if (offset > 0) {{
                    result.navigation.prev = `offset=${{Math.max(0, offset - limit)}} limit=${{limit}}`;
                }}
                if (offset + limit < total) {{
                    result.navigation.next = `offset=${{offset + limit}} limit=${{limit}}`;
                }}
            }}

            return result;
        }})()
        '''

    elif content_type == "headings":
        return f'''
        (() => {{
            {scope_js}
            {helpers}

            const headings = [];
            scope.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {{
                if (!isVisible(h)) return;
                const text = getCleanText(h);
                if (text && text.length > 1) {{
                    headings.push({{
                        level: parseInt(h.tagName[1]),
                        text: text.substring(0, 100)
                    }});
                }}
            }});

            return {{
                contentType: 'headings',
                total: headings.length,
                items: headings
            }};
        }})()
        '''

    elif content_type == "images":
        return f'''
        (() => {{
            {scope_js}
            {helpers}
            const offset = {offset};
            const limit = {limit};

            const allImages = [];
            scope.querySelectorAll('img[src]').forEach(img => {{
                if (!isVisible(img)) return;
                const src = img.src;
                if (src.startsWith('data:') || src.includes('pixel') || src.includes('tracking')) return;
                allImages.push({{
                    src: src,
                    alt: img.alt || '',
                    width: img.naturalWidth || img.width,
                    height: img.naturalHeight || img.height
                }});
            }});

            const unique = dedupe(allImages, i => i.src);
            const total = unique.length;
            const items = unique.slice(offset, offset + limit);

            const result = {{
                contentType: 'images',
                total: total,
                offset: offset,
                limit: limit,
                hasMore: offset + limit < total,
                items: items
            }};

            if (offset > 0 || offset + limit < total) {{
                result.navigation = {{}};
                if (offset > 0) {{
                    result.navigation.prev = `offset=${{Math.max(0, offset - limit)}} limit=${{limit}}`;
                }}
                if (offset + limit < total) {{
                    result.navigation.next = `offset=${{offset + limit}} limit=${{limit}}`;
                }}
            }}

            return result;
        }})()
        '''

    return '(() => ({ error: true, reason: "Unknown content type" }))()'


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
            "age_seconds": round(time.time() - _page_context.timestamp, 1)
        }

    # Refresh context
    result = analyze_page(config)
    return {
        "cached": False,
        "overview": result.get("overview"),
        "target": result.get("target")
    }


# ═══════════════════════════════════════════════════════════════════════════════
# get_page_info - Page information wrapper
# ═══════════════════════════════════════════════════════════════════════════════

def get_page_info(config: BrowserConfig) -> dict[str, Any]:
    """
    Get current page information (URL, title, scroll position, viewport size).

    Args:
        config: Browser configuration

    Returns:
        Dictionary with pageInfo and target
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
