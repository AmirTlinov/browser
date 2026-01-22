"""
JavaScript builders for page analysis.

Contains JS code generation for analyze_page function.
"""

from __future__ import annotations

# Common JavaScript helper functions used across analysis
JS_HELPERS = """
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
"""


def build_analyze_js(detail: str | None, offset: int, limit: int, form_index: int | None, include_content: bool) -> str:
    """Build JavaScript for page analysis based on mode."""
    if detail is None:
        return _build_overview_js(include_content)
    elif detail == "forms":
        return _build_forms_js(form_index)
    elif detail == "links":
        return _build_links_js(offset, limit)
    elif detail == "buttons":
        return _build_buttons_js()
    elif detail == "inputs":
        return _build_inputs_js()
    elif detail == "content":
        return _build_content_js(offset, limit)
    return '(() => ({ error: true, reason: "Unknown detail type" }))()'


def _build_overview_js(include_content: bool) -> str:
    """Build JavaScript for overview mode."""
    content_block = "if (true) {" if include_content else "if (false) {"
    return f"""
    (() => {{
        {JS_HELPERS}

        const result = {{ overview: {{}} }};
        const o = result.overview;

        o.url = window.location.href;
        o.title = document.title;

        // Canvas-app detection (Miro/Figma-class UIs):
        // Many such apps have a search box, so detect a dominant canvas/surface early to avoid misclassification.
        const vw = window.innerWidth || 0;
        const vh = window.innerHeight || 0;
        const vpArea = Math.max(1, vw * vh);
        const canvasCandidates = Array.from(document.querySelectorAll('canvas, svg, [role="application"]')).filter(el => isVisible(el));
        let bestSurface = null;
        let bestArea = 0;
        for (const el of canvasCandidates) {{
            try {{
                const r = el.getBoundingClientRect();
                const area = Math.max(0, r.width) * Math.max(0, r.height);
                if (area > bestArea) {{
                    bestArea = area;
                    bestSurface = {{
                        tagName: el.tagName,
                        role: el.getAttribute && el.getAttribute('role') ? el.getAttribute('role') : null,
                        id: el.id || null,
                        className: String(el.className || '').slice(0, 120),
                        rect: {{ x: r.x, y: r.y, w: r.width, h: r.height }},
                        areaRatio: Math.round((area / vpArea) * 1000) / 1000,
                    }};
                }}
            }} catch (e) {{}}
        }}
        const hasBigSurface = !!(bestSurface && bestSurface.areaRatio >= 0.25);

        const hasPassword = document.querySelector('input[type="password"]');
        const hasSearchInput = document.querySelector('input[type="search"], input[name="q"], [role="searchbox"]');
        const hasLoginForm = document.querySelector('form[action*="login" i], form[action*="signin" i]');
        const hasCheckout = document.querySelector('form[action*="checkout" i], form[action*="payment" i]');
        const hasArticle = document.querySelector('article, [role="article"], .article');
        const hasTables = document.querySelectorAll('table tbody tr').length > 3;

        if (hasPassword && hasLoginForm) o.pageType = 'login';
        else if (hasPassword) o.pageType = 'auth';
        else if (hasCheckout) o.pageType = 'checkout';
        else if (hasBigSurface) o.pageType = 'canvas_app';
        else if (hasSearchInput) o.pageType = 'search';
        else if (hasArticle) o.pageType = 'article';
        else if (hasTables) o.pageType = 'data_table';
        else if (document.querySelectorAll('a[href]').length > 20) o.pageType = 'listing';
        else o.pageType = 'generic';

        if (bestSurface) o.canvasSurface = bestSurface;

        const forms = getAllElements(document, 'form');
        const allLinks = getAllElements(document, 'a[href]').filter(a => isVisible(a) && !a.href.startsWith('javascript:'));
        const allButtons = getAllElements(document, 'button, input[type="button"], input[type="submit"], [role="button"]').filter(b => isVisible(b));
        const standaloneInputs = getAllElements(document, 'input:not(form input), textarea:not(form textarea)').filter(i => i.type !== 'hidden' && isVisible(i));

        o.counts = {{
            forms: forms.length,
            links: allLinks.length,
            buttons: allButtons.length,
            inputs: standaloneInputs.length
        }};

        o.preview = {{}};

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

        const linkTexts = [];
        for (const a of allLinks) {{
            const text = getCleanText(a).substring(0, 30);
            if (text && !linkTexts.includes(text) && linkTexts.length < 5) {{
                linkTexts.push(text);
            }}
        }}
        if (linkTexts.length) o.preview.topLinks = linkTexts;

        const btnTexts = [];
        for (const btn of allButtons) {{
            const text = (getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '').substring(0, 25);
            if (text && !looksLikeCode(text) && !btnTexts.includes(text) && btnTexts.length < 5) {{
                btnTexts.push(text);
            }}
        }}
        if (btnTexts.length) o.preview.topButtons = btnTexts;

        {content_block}
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

        // Frontend issues summary (best-effort; requires diagnostics instrumentation)
        try {{
            const d = globalThis.__mcpDiag;
            if (d && typeof d.summary === 'function') {{
                o.issues = d.summary();
            }}
        }} catch (e) {{
            // ignore
        }}

        // Frontend snapshot extras (framework/perf/resources/dev overlay)
        try {{
            const d = globalThis.__mcpDiag;
            if (d && typeof d.snapshot === 'function') {{
                const snap = d.snapshot({{ offset: 0, limit: 0, sort: 'start' }});
                if (snap) {{
                    if (snap.framework) o.framework = snap.framework;
                    if (snap.devOverlay) o.devOverlay = snap.devOverlay;

                    if (snap.vitals) {{
                        const v = snap.vitals;
                        o.vitals = {{
                            cls: v.cls,
                            lcpMs: v.lcp && typeof v.lcp.startTime === 'number' ? v.lcp.startTime : null,
                            fcpMs: v.fcp,
                            fpMs: v.fp,
                            longTaskMaxMs: v.longTasks ? v.longTasks.maxDuration : null,
                        }};
                    }}

                    if (snap.resources && snap.resources.summary) {{
                        const rs = snap.resources.summary;
                        o.resourcesSummary = {{
                            total: rs.total,
                            totalTransferSize: rs.totalTransferSize,
                            largest: Array.isArray(rs.largest) && rs.largest[0] ? rs.largest[0] : null,
                            slowest: Array.isArray(rs.slowest) && rs.slowest[0] ? rs.slowest[0] : null,
                        }};
                    }}
                }}
            }}
        }} catch (e) {{
            // ignore
        }}

        o.suggestedActions = [];
        if (o.pageType === 'login' || o.pageType === 'auth') {{
            o.suggestedActions.push('fill_form(data={{...}}, submit=true)');
        }} else if (o.pageType === 'canvas_app') {{
            o.suggestedActions.push("app(op='insert', params={{svg|text|file_paths, strategy:'auto'}})");
            o.suggestedActions.push("app(op='diagram', params={{...}})");
            o.suggestedActions.push("page(detail='locators')  # for UI chrome, not canvas");
        }} else if (o.pageType === 'search') {{
            o.suggestedActions.push('search_page(query="...")');
        }} else if (o.pageType === 'article') {{
            o.suggestedActions.push('extract_content(content_type="main")');
        }} else if (o.pageType === 'data_table') {{
            o.suggestedActions.push('extract_content(content_type="table")');
        }} else if (o.pageType === 'listing') {{
            o.suggestedActions.push('click_element(text="...")');
        }}

        if (o.issues && (o.issues.consoleErrors || o.issues.jsErrors || o.issues.resourceErrors || o.issues.failedRequests)) {{
            o.suggestedActions.unshift('page(detail="diagnostics")');
        }}

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
    """


def _build_forms_js(form_index: int | None) -> str:
    """Build JavaScript for forms detail mode."""
    if form_index is not None:
        return f"""
        (() => {{
            {JS_HELPERS}
            const forms = getAllElements(document, 'form');
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
        """
    else:
        return f"""
        (() => {{
            {JS_HELPERS}
            const forms = getAllElements(document, 'form');
            const items = [];

            forms.forEach((form, idx) => {{
                const fields = form.querySelectorAll('input:not([type="hidden"]), select, textarea');
                const visibleFields = Array.from(fields).filter(f => isVisible(f));
                const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');

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
        """


def _build_links_js(offset: int, limit: int) -> str:
    """Build JavaScript for links detail mode."""
    return f"""
    (() => {{
        {JS_HELPERS}
        const offset = {offset};
        const limit = {limit};

        const allLinks = getAllElements(document, 'a[href]').filter(a => {{
            if (!isVisible(a)) return false;
            const href = a.href;
            if (href.startsWith('javascript:') || href === '#' || href === window.location.href) return false;
            const text = getCleanText(a);
            return text && text.length > 0;
        }});

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
    """


def _build_buttons_js() -> str:
    """Build JavaScript for buttons detail mode."""
    return f"""
    (() => {{
        {JS_HELPERS}

        const allButtons = getAllElements(document, 'button, input[type="button"], input[type="submit"], [role="button"]').filter(btn => {{
            if (!isVisible(btn)) return false;
            const text = getCleanText(btn) || btn.value || btn.getAttribute('aria-label') || '';
            return text && text.length > 0 && text.length < 60 && !looksLikeCode(text);
        }});

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
    """


def _build_inputs_js() -> str:
    """Build JavaScript for inputs detail mode."""
    return f"""
    (() => {{
        {JS_HELPERS}

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
    """


def _build_content_js(offset: int, limit: int) -> str:
    """Build JavaScript for content detail mode."""
    return f"""
    (() => {{
        {JS_HELPERS}
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
    """
