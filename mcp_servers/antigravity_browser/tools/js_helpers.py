"""
JavaScript helper functions for browser automation.

This module contains reusable JavaScript code snippets that are injected
into pages for element detection, form analysis, and content extraction.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# Core DOM helpers
# ═══════════════════════════════════════════════════════════════════════════════

IS_VISIBLE = '''
const isVisible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    return style.display !== 'none' &&
           style.visibility !== 'hidden' &&
           style.opacity !== '0' &&
           el.offsetWidth > 0 &&
           el.offsetHeight > 0;
};
'''

LOOKS_LIKE_CODE = '''
const looksLikeCode = (text) => {
    if (!text || text.length < 5) return false;
    if (text.match(/[.#][a-zA-Z_-]+\\s*\\{/)) return true;
    if (text.match(/\\{[^}]*:[^}]*\\}/)) return true;
    if ((text.match(/\\{/g) || []).length > 2) return true;
    if ((text.match(/:/g) || []).length > 3 && (text.match(/;/g) || []).length > 2) return true;
    if (text.match(/^(function|const |let |var |=>|\\(\\))/)) return true;
    return false;
};
'''

GET_CLEAN_TEXT = '''
const getCleanText = (el) => {
    if (!el) return '';
    const clone = el.cloneNode(true);
    clone.querySelectorAll('script, style, noscript, svg, path').forEach(e => e.remove());
    let text = clone.textContent || '';
    text = text.replace(/\\s+/g, ' ').trim();
    if (looksLikeCode(text)) return '';
    return text;
};
'''

DEDUPE = '''
const dedupe = (arr, keyFn) => {
    const seen = new Set();
    return arr.filter(item => {
        const key = keyFn(item);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
};
'''

GET_ALL_ELEMENTS = '''
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


# ═══════════════════════════════════════════════════════════════════════════════
# Element selection helpers
# ═══════════════════════════════════════════════════════════════════════════════

GET_SELECTOR = '''
const getSelector = (el) => {
    if (!el) return '';
    if (el.id) return '#' + el.id;
    if (el === document.body) return 'body';

    const path = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
        let selector = node.tagName.toLowerCase();
        if (node.id) {
            path.unshift('#' + node.id);
            break;
        }
        if (node.className) {
            const classes = node.className.split(' ').filter(c => c.trim() && !c.match(/^(ng-|_|sc-)/)).slice(0, 2);
            if (classes.length) selector += '.' + classes.join('.');
        }
        const siblings = node.parentNode ? Array.from(node.parentNode.children).filter(c => c.tagName === node.tagName) : [];
        if (siblings.length > 1) {
            const idx = siblings.indexOf(node) + 1;
            selector += ':nth-of-type(' + idx + ')';
        }
        path.unshift(selector);
        node = node.parentNode;
    }
    return path.join(' > ');
};
'''


FIND_ELEMENT_BY_TEXT = '''
const findElementByText = (text, role, nearText, index) => {
    text = text ? text.toLowerCase().trim() : '';
    role = role || null;
    nearText = nearText ? nearText.toLowerCase().trim() : '';
    index = index || 0;

    const getRoleSelector = (r) => {
        const m = {
            button: 'button, input[type="button"], input[type="submit"], [role="button"]',
            link: 'a[href], [role="link"]',
            checkbox: 'input[type="checkbox"], [role="checkbox"]',
            radio: 'input[type="radio"], [role="radio"]',
            tab: '[role="tab"]',
            menuitem: '[role="menuitem"]'
        };
        return m[r] || '*';
    };

    const selector = role ? getRoleSelector(role) : 'button, a, input, [role="button"], [role="link"], span, div, p';
    let candidates = Array.from(document.querySelectorAll(selector)).filter(el => isVisible(el));

    if (text) {
        candidates = candidates.filter(el => {
            const t = (el.textContent || '').toLowerCase().trim();
            const v = (el.value || '').toLowerCase();
            const ar = (el.getAttribute('aria-label') || '').toLowerCase();
            const ti = (el.title || '').toLowerCase();
            return t.includes(text) || v.includes(text) || ar.includes(text) || ti.includes(text);
        });
    }

    if (nearText) {
        candidates = candidates.map(el => {
            const rect = el.getBoundingClientRect();
            const labels = document.querySelectorAll('label, span, div, p');
            let minDist = Infinity;
            labels.forEach(lbl => {
                if ((lbl.textContent || '').toLowerCase().includes(nearText)) {
                    const lr = lbl.getBoundingClientRect();
                    const d = Math.hypot(rect.left - lr.left, rect.top - lr.top);
                    if (d < minDist) minDist = d;
                }
            });
            return { el, dist: minDist };
        }).filter(x => x.dist < Infinity).sort((a, b) => a.dist - b.dist).map(x => x.el);
    }

    return candidates[index] || null;
};
'''


# ═══════════════════════════════════════════════════════════════════════════════
# Form analysis helpers
# ═══════════════════════════════════════════════════════════════════════════════

MATCH_FIELD = '''
const matchField = (fieldKey, inputs) => {
    const key = fieldKey.toLowerCase().trim().replace(/[^a-z0-9]/g, '');
    let best = null;
    let bestScore = 0;

    inputs.forEach(inp => {
        const name = (inp.name || '').toLowerCase();
        const id = (inp.id || '').toLowerCase();
        const placeholder = (inp.placeholder || '').toLowerCase();
        const ariaLabel = (inp.getAttribute('aria-label') || '').toLowerCase();
        const label = inp.closest('label')?.textContent?.toLowerCase() ||
                     document.querySelector('label[for="' + inp.id + '"]')?.textContent?.toLowerCase() || '';
        const type = inp.type || 'text';

        let score = 0;
        [name, id, placeholder, ariaLabel, label].forEach(attr => {
            const attrClean = attr.replace(/[^a-z0-9]/g, '');
            if (attrClean === key) score += 10;
            else if (attrClean.includes(key) || key.includes(attrClean)) score += 5;
        });

        const common = {
            email: ['email', 'mail', 'user', 'login'],
            password: ['password', 'pass', 'pwd', 'secret'],
            username: ['user', 'login', 'name', 'account'],
            phone: ['phone', 'tel', 'mobile', 'cell'],
            address: ['address', 'addr', 'street'],
            search: ['search', 'query', 'q', 'find']
        };
        Object.entries(common).forEach(([semantic, keywords]) => {
            if (keywords.some(k => key.includes(k))) {
                if (type === semantic || keywords.some(k => name.includes(k) || id.includes(k))) {
                    score += 3;
                }
            }
        });

        if (score > bestScore) {
            bestScore = score;
            best = inp;
        }
    });
    return best;
};
'''


EXTRACT_FORM_DETAILS = '''
const extractFormDetails = (form, idx) => {
    const fields = form.querySelectorAll('input:not([type="hidden"]), select, textarea');
    const visibleFields = Array.from(fields).filter(f => isVisible(f));

    return {
        index: idx,
        id: form.id || null,
        action: form.action || null,
        method: form.method || 'GET',
        fieldCount: visibleFields.length,
        fields: visibleFields.map(f => {
            const label = f.closest('label')?.textContent?.trim() ||
                         document.querySelector('label[for="' + f.id + '"]')?.textContent?.trim() ||
                         f.placeholder ||
                         f.getAttribute('aria-label') || '';
            return {
                type: f.type || f.tagName.toLowerCase(),
                name: f.name || null,
                id: f.id || null,
                label: label.substring(0, 50),
                required: f.required,
                selector: getSelector(f)
            };
        }),
        submitButton: (() => {
            const btn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
            return btn ? { text: getCleanText(btn).substring(0, 30), selector: getSelector(btn) } : null;
        })()
    };
};
'''


# ═══════════════════════════════════════════════════════════════════════════════
# Combined helper bundles
# ═══════════════════════════════════════════════════════════════════════════════

CORE_HELPERS = IS_VISIBLE + LOOKS_LIKE_CODE + GET_CLEAN_TEXT + DEDUPE + GET_ALL_ELEMENTS

ELEMENT_HELPERS = CORE_HELPERS + GET_SELECTOR + FIND_ELEMENT_BY_TEXT

FORM_HELPERS = ELEMENT_HELPERS + MATCH_FIELD + EXTRACT_FORM_DETAILS


def build_js_with_helpers(helpers: str, body: str) -> str:
    """
    Build JavaScript code with helper functions and body wrapped in IIFE.

    Args:
        helpers: JavaScript helper functions to include
        body: Main JavaScript code to execute

    Returns:
        Complete JavaScript wrapped in IIFE
    """
    return f'''
(() => {{
    {helpers}
    {body}
}})()
'''
