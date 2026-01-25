"""
JavaScript builders for content extraction.

Contains JS code generation for extract_content function.
"""

from __future__ import annotations

import json

from ..shadow_dom import DEEP_QUERY_JS

# Common JavaScript helper functions
JS_HELPERS = """
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

const _badTags = new Set(['NAV', 'HEADER', 'FOOTER', 'ASIDE', 'FORM']);
const _badRoles = new Set(['navigation', 'banner', 'contentinfo', 'complementary']);
const _badHints = ['nav', 'navbar', 'footer', 'header', 'sidebar', 'menu', 'breadcrumb', 'cookie', 'promo', 'ad'];

const isBadNode = (el) => {
    if (!el || !el.tagName) return true;
    if (_badTags.has(el.tagName)) return true;
    const role = (el.getAttribute && el.getAttribute('role')) || '';
    if (role && _badRoles.has(role)) return true;
    const hint = ((el.id || '') + ' ' + (el.className || '')).toLowerCase();
    return _badHints.some(h => hint.includes(h));
};

const linkTextLength = (el) => {
    if (!el) return 0;
    let total = 0;
    el.querySelectorAll('a[href]').forEach(a => {
        if (!isVisible(a)) return;
        const text = getCleanText(a);
        if (text) total += text.length;
    });
    return total;
};

const scoreNode = (el) => {
    if (!el || !isVisible(el) || isBadNode(el)) return 0;
    const textLen = getCleanText(el).length;
    if (textLen < 120) return 0;
    const linkLen = linkTextLength(el);
    const density = textLen > 0 ? (linkLen / textLen) : 1;
    const penalty = Math.min(0.8, density * 0.85);
    return textLen * (1 - penalty);
};

const _trim = (value, maxLen) => {
    if (!value) return '';
    const s = String(value);
    return s.length > maxLen ? s.slice(0, maxLen) : s;
};

const buildSelectorHint = (el) => {
    if (!el || !el.tagName) return null;
    const id = el.id ? `#${el.id}` : '';
    const classes = (el.className && typeof el.className === 'string')
        ? el.className.split(/\s+/).filter(Boolean).slice(0, 2).map(c => `.${c}`).join('')
        : '';
    return `${el.tagName.toLowerCase()}${id}${classes}`;
};

const collectDataAttrs = (el, limit = 6) => {
    if (!el || !el.attributes) return [];
    const out = [];
    for (const attr of Array.from(el.attributes)) {
        if (!attr || !attr.name || !attr.name.startsWith('data-')) continue;
        out.push({ name: attr.name, value: _trim(attr.value, 80) });
        if (out.length >= limit) break;
    }
    return out;
};

const buildDomPath = (el, maxDepth = 6) => {
    const path = [];
    let node = el;
    let depth = 0;
    while (node && node.tagName && depth < maxDepth) {
        const id = node.id ? `#${node.id}` : '';
        const classes = (node.className && typeof node.className === 'string')
            ? node.className.split(/\\s+/).filter(Boolean).slice(0, 2).map(c => `.${c}`).join('')
            : '';
        path.push(`${node.tagName.toLowerCase()}${id}${classes}`);
        node = node.parentElement;
        depth += 1;
    }
    return path;
};

const buildNodeDebug = (el, score) => {
    if (!el) return null;
    const text = getCleanText(el);
    const textLen = text.length;
    const linkLen = linkTextLength(el);
    const density = textLen > 0 ? (linkLen / textLen) : 1;
    return {
        tag: el.tagName,
        id: el.id || null,
        className: _trim(el.className, 120),
        selectorHint: buildSelectorHint(el),
        dataAttrs: collectDataAttrs(el, 6),
        domPath: buildDomPath(el, 6),
        score: Math.round(score * 100) / 100,
        textLen: textLen,
        linkLen: linkLen,
        linkDensity: Math.round(density * 1000) / 1000,
        preview: _trim(text, 160)
    };
};

const pickContentRoot = (scope, wantDebug) => {
    if (!scope) return document.body || scope;
    const preferred = ['article', 'main', '[role="main"]'];
    for (const sel of preferred) {
        const candidate = scope.querySelector(sel);
        if (candidate && isVisible(candidate)) {
            return wantDebug ? { node: candidate, debug: { best: buildNodeDebug(candidate, scoreNode(candidate)) } } : { node: candidate, debug: null };
        }
    }
    const nodes = Array.from(scope.querySelectorAll('article, main, section, div')).slice(0, 600);
    let best = null;
    let bestScore = 0;
    const candidates = [];
    for (const node of nodes) {
        const score = scoreNode(node);
        if (score > bestScore) {
            bestScore = score;
            best = node;
        }
        if (wantDebug && score > 0 && candidates.length < 6) {
            const debug = buildNodeDebug(node, score);
            if (debug) candidates.push(debug);
        }
    }
    if (wantDebug) {
        return {
            node: best || scope,
            debug: {
                best: buildNodeDebug(best || scope, bestScore),
                candidates: candidates
            }
        };
    }
    return { node: best || scope, debug: null };
};
"""


def build_extract_js(
    content_type: str,
    selector: str | None,
    offset: int,
    limit: int,
    table_index: int | None,
    content_root_debug: bool = False,
) -> str:
    """Build JavaScript for content extraction."""
    scope_js = f"""
    {DEEP_QUERY_JS}
    const customSelector = {json.dumps(selector)};
    const scope = customSelector ? (() => {{
        const nodes = __mcpQueryAllDeep(customSelector, 1000);
        const pickFrom = nodes.filter(__mcpIsVisible);
        return (pickFrom.length ? pickFrom : nodes)[0] || null;
    }})() : document.body;
    if (!scope) {{
        return {{ error: true, reason: 'Selector not found: ' + customSelector }};
    }}
    """

    if content_type == "overview":
        return _build_overview_js(scope_js, content_root_debug)
    elif content_type == "main":
        return _build_main_js(scope_js, offset, limit, content_root_debug)
    elif content_type == "table":
        return _build_table_js(scope_js, offset, limit, table_index, content_root_debug)
    elif content_type == "links":
        return _build_links_js(scope_js, offset, limit, content_root_debug)
    elif content_type == "headings":
        return _build_headings_js(scope_js, content_root_debug)
    elif content_type == "images":
        return _build_images_js(scope_js, offset, limit, content_root_debug)

    return '(() => ({ error: true, reason: "Unknown content type" }))()'


def _build_overview_js(scope_js: str, content_root_debug: bool) -> str:
    """Build JavaScript for content overview."""
    debug_js = "true" if content_root_debug else "false"
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
        const __mcpWantDebug = {debug_js};

        const result = {{ contentType: 'overview' }};

        const contentPick = pickContentRoot(scope, __mcpWantDebug);
        const contentRoot = contentPick.node;

        const paragraphs = contentRoot.querySelectorAll('p');
        const tables = contentRoot.querySelectorAll('table');
        const links = contentRoot.querySelectorAll('a[href]');
        const headings = contentRoot.querySelectorAll('h1, h2, h3, h4, h5, h6');
        const images = contentRoot.querySelectorAll('img[src]');

        result.counts = {{
            paragraphs: paragraphs.length,
            tables: tables.length,
            links: links.length,
            headings: headings.length,
            images: images.length
        }};
        if (__mcpWantDebug && contentPick.debug) {{
            result.contentRootDebug = contentPick.debug;
        }}

        result.preview = {{
            title: document.title,
            url: window.location.href
        }};

        for (const p of paragraphs) {{
            if (!isVisible(p)) continue;
            const text = getCleanText(p);
            if (text.length > 30) {{
                result.preview.firstParagraph = text.substring(0, 200) + (text.length > 200 ? '...' : '');
                break;
            }}
        }}

        const topHeadings = [];
        headings.forEach(h => {{
            if (!isVisible(h) || topHeadings.length >= 5) return;
            const text = getCleanText(h);
            if (text) topHeadings.push(text.substring(0, 50));
        }});
        if (topHeadings.length) result.preview.headings = topHeadings;

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
    """


def _build_main_js(scope_js: str, offset: int, limit: int, content_root_debug: bool) -> str:
    """Build JavaScript for main content extraction."""
    debug_js = "true" if content_root_debug else "false"
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
        const __mcpWantDebug = {debug_js};
        const offset = {offset};
        const limit = {limit};

        const contentPick = pickContentRoot(scope, __mcpWantDebug);
        const contentRoot = contentPick.node;

        const paragraphs = [];
        contentRoot.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li').forEach(el => {{
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
        if (__mcpWantDebug && contentPick.debug) {{
            result.contentRootDebug = contentPick.debug;
        }}

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


def _build_table_js(
    scope_js: str,
    offset: int,
    limit: int,
    table_index: int | None,
    content_root_debug: bool,
) -> str:
    """Build JavaScript for table extraction."""
    debug_js = "true" if content_root_debug else "false"
    if table_index is not None:
        return f"""
        (() => {{
            {scope_js}
            {JS_HELPERS}
            const __mcpWantDebug = {debug_js};
            const tableIndex = {table_index};
            const offset = {offset};
            const limit = {limit};

            const contentPick = pickContentRoot(scope, __mcpWantDebug);
            const contentRoot = contentPick.node;
            const tables = contentRoot.querySelectorAll('table');
            if (tableIndex >= tables.length) {{
                return {{ error: true, reason: 'Table index ' + tableIndex + ' not found. Available: 0-' + (tables.length - 1) }};
            }}

            const table = tables[tableIndex];

            const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th'))
                .map(th => getCleanText(th))
                .filter(t => t);

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
            if (__mcpWantDebug && contentPick.debug) {{
                result.contentRootDebug = contentPick.debug;
            }}

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
    else:
        return f"""
        (() => {{
            {scope_js}
            {JS_HELPERS}
            const __mcpWantDebug = {debug_js};

            const contentPick = pickContentRoot(scope, __mcpWantDebug);
            const contentRoot = contentPick.node;
            const tables = contentRoot.querySelectorAll('table');
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

            const result = {{
                contentType: 'table',
                total: items.length,
                items: items,
                hint: items.length > 0 ? "Use table_index=N offset=0 limit=20 to get table rows" : null
            }};
            if (__mcpWantDebug && contentPick.debug) {{
                result.contentRootDebug = contentPick.debug;
            }}
            return result;
        }})()
        """


def _build_links_js(scope_js: str, offset: int, limit: int, content_root_debug: bool) -> str:
    """Build JavaScript for links extraction."""
    debug_js = "true" if content_root_debug else "false"
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
        const __mcpWantDebug = {debug_js};
        const offset = {offset};
        const limit = {limit};

        const allLinks = [];
        const contentPick = pickContentRoot(scope, __mcpWantDebug);
        const contentRoot = contentPick.node;
        contentRoot.querySelectorAll('a[href]').forEach(a => {{
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
        if (__mcpWantDebug && contentPick.debug) {{
            result.contentRootDebug = contentPick.debug;
        }}

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


def _build_headings_js(scope_js: str, content_root_debug: bool) -> str:
    """Build JavaScript for headings extraction."""
    debug_js = "true" if content_root_debug else "false"
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
        const __mcpWantDebug = {debug_js};

        const headings = [];
        const contentPick = pickContentRoot(scope, __mcpWantDebug);
        const contentRoot = contentPick.node;
        contentRoot.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {{
            if (!isVisible(h)) return;
            const text = getCleanText(h);
            if (text && text.length > 1) {{
                headings.push({{
                    level: parseInt(h.tagName[1]),
                    text: text.substring(0, 100)
                }});
            }}
        }});

        const result = {{
            contentType: 'headings',
            total: headings.length,
            items: headings
        }};
        if (__mcpWantDebug && contentPick.debug) {{
            result.contentRootDebug = contentPick.debug;
        }}
        return result;
    }})()
    """


def _build_images_js(scope_js: str, offset: int, limit: int, content_root_debug: bool) -> str:
    """Build JavaScript for images extraction."""
    debug_js = "true" if content_root_debug else "false"
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
        const __mcpWantDebug = {debug_js};
        const offset = {offset};
        const limit = {limit};

        const allImages = [];
        const contentPick = pickContentRoot(scope, __mcpWantDebug);
        const contentRoot = contentPick.node;
        contentRoot.querySelectorAll('img[src]').forEach(img => {{
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
        if (__mcpWantDebug && contentPick.debug) {{
            result.contentRootDebug = contentPick.debug;
        }}

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
