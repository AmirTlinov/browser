"""
JavaScript builders for content extraction.

Contains JS code generation for extract_content function.
"""

from __future__ import annotations

import json

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
"""


def build_extract_js(content_type: str, selector: str | None, offset: int, limit: int, table_index: int | None) -> str:
    """Build JavaScript for content extraction."""
    scope_js = f"""
    const customSelector = {json.dumps(selector)};
    const scope = customSelector ? document.querySelector(customSelector) : document.body;
    if (!scope) {{
        return {{ error: true, reason: 'Selector not found: ' + customSelector }};
    }}
    """

    if content_type == "overview":
        return _build_overview_js(scope_js)
    elif content_type == "main":
        return _build_main_js(scope_js, offset, limit)
    elif content_type == "table":
        return _build_table_js(scope_js, offset, limit, table_index)
    elif content_type == "links":
        return _build_links_js(scope_js, offset, limit)
    elif content_type == "headings":
        return _build_headings_js(scope_js)
    elif content_type == "images":
        return _build_images_js(scope_js, offset, limit)

    return '(() => ({ error: true, reason: "Unknown content type" }))()'


def _build_overview_js(scope_js: str) -> str:
    """Build JavaScript for content overview."""
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}

        const result = {{ contentType: 'overview' }};

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


def _build_main_js(scope_js: str, offset: int, limit: int) -> str:
    """Build JavaScript for main content extraction."""
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
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
    """


def _build_table_js(scope_js: str, offset: int, limit: int, table_index: int | None) -> str:
    """Build JavaScript for table extraction."""
    if table_index is not None:
        return f"""
        (() => {{
            {scope_js}
            {JS_HELPERS}
            const tableIndex = {table_index};
            const offset = {offset};
            const limit = {limit};

            const tables = scope.querySelectorAll('table');
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
        """


def _build_links_js(scope_js: str, offset: int, limit: int) -> str:
    """Build JavaScript for links extraction."""
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
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
    """


def _build_headings_js(scope_js: str) -> str:
    """Build JavaScript for headings extraction."""
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}

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
    """


def _build_images_js(scope_js: str, offset: int, limit: int) -> str:
    """Build JavaScript for images extraction."""
    return f"""
    (() => {{
        {scope_js}
        {JS_HELPERS}
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
    """
