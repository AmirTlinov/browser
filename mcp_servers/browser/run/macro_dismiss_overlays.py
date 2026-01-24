"""Macro: dismiss_overlays.

Best-effort DOM overlay dismissal implemented as a single JS evaluation.
Kept in a separate module so `run/macros.py` stays within size limits.
"""

from __future__ import annotations

from typing import Any


DISMISS_OVERLAYS_JS = r"""
(() => {
  try {
    const vw = window.innerWidth || 0;
    const vh = window.innerHeight || 0;
    if (!vw || !vh) return { ok: false, reason: "no_viewport" };

    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const within = (r) => r && r.width > 2 && r.height > 2 && r.right > 0 && r.bottom > 0 && r.left < vw && r.top < vh;
    const isVisible = (el) => {
      try {
        const st = window.getComputedStyle(el);
        if (!st || st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0' || st.pointerEvents === 'none') return false;
      } catch (e) {}
      const r = el.getBoundingClientRect?.();
      return !!(r && within(r));
    };
    const textOf = (el) => {
      const pick = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
      let t = '';
      try { t = pick(el.getAttribute?.('aria-label')); } catch (e) {}
      if (!t) { try { t = pick(el.getAttribute?.('title')); } catch (e) {} }
      if (!t) { try { t = pick(el.innerText); } catch (e) {} }
      if (!t) { try { t = pick(el.textContent); } catch (e) {} }
      return t.slice(0, 120);
    };
    const looksLikeOverlay = (el) => {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      if (!within(r)) return false;
      const area = Math.max(0, r.width) * Math.max(0, r.height);
      const vp = vw * vh;
      const coversCenter = (vw * 0.5 >= r.left && vw * 0.5 <= r.right && vh * 0.5 >= r.top && vh * 0.5 <= r.bottom);
      let pos = '';
      let z = 0;
      try {
        const st = window.getComputedStyle(el);
        pos = String(st?.position || '');
        z = Number.parseInt(String(st?.zIndex || '0'), 10);
        if (!Number.isFinite(z)) z = 0;
      } catch (e) {}
      const role = String(el.getAttribute?.('role') || '').toLowerCase();
      const ariaModal = String(el.getAttribute?.('aria-modal') || '').toLowerCase();
      const hint = (String(el.id || '') + ' ' + String(el.className || '')).toLowerCase();
      if (role === 'dialog' || role === 'alertdialog' || ariaModal === 'true') return coversCenter;
      if ((pos === 'fixed' || pos === 'sticky') && coversCenter && area >= vp * 0.25) return true;
      if (coversCenter && area >= vp * 0.35) return true;
      if (coversCenter && area >= vp * 0.20 && (hint.includes('modal') || hint.includes('dialog') || hint.includes('overlay') || hint.includes('backdrop') || hint.includes('consent') || hint.includes('cookie'))) return true;
      if (coversCenter && z >= 1000 && area >= vp * 0.15) return true;
      return false;
    };

    const scoreButton = (t, hint) => {
      const s = (String(t || '') + ' ' + String(hint || '')).toLowerCase();
      const close = /(close|dismiss|cancel|skip|later|not now|×|x\\b|закры|отмен|пропус|позже|не сейчас)/i;
      const accept = /(accept|agree|ok|got it|continue|allow|yes|соглас|принять|ок|продолж|разреш|да)/i;
      const reject = /(reject|decline|no|deny|отклон|нет|запрет)/i;
      if (close.test(s)) return 100;
      if (reject.test(s)) return 60;
      if (accept.test(s)) return 30;
      return 10;
    };

    const cx = clamp(Math.floor(vw * 0.5), 1, vw - 2);
    const cy = clamp(Math.floor(vh * 0.5), 1, vh - 2);
    let el = document.elementFromPoint(cx, cy);
    if (!el) return { ok: false, reason: "no_element" };

    let overlay = null;
    for (let i = 0; i < 10 && el; i++) {
      if (looksLikeOverlay(el) && isVisible(el)) { overlay = el; break; }
      el = el.parentElement;
    }
    if (!overlay) return { ok: false, reason: "no_overlay" };

    const nodes = overlay.querySelectorAll('button,[role=\"button\"],a,input[type=\"button\"],input[type=\"submit\"],div[role=\"button\"],span[role=\"button\"]');
    const candidates = [];
    for (const b of nodes) {
      if (!b || !isVisible(b)) continue;
      const label = textOf(b);
      const hint = (String(b.getAttribute?.('data-testid') || '') + ' ' + String(b.id || '') + ' ' + String(b.className || '')).slice(0, 200);
      candidates.push({ el: b, label, score: scoreButton(label, hint) });
    }
    if (!candidates.length) return { ok: false, reason: "overlay_no_buttons" };
    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0];
    try { best.el.click(); } catch (e) { return { ok: false, reason: "click_failed" }; }
    return { ok: true, label: best.label || null, score: best.score };
  } catch (e) {
    return { ok: false, reason: "exception" };
  }
})()
""".strip()


def dismiss_overlays_steps() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    steps = [{"js": {"code": _DISMISS_OVERLAYS_JS}, "optional": True, "label": "dismiss_overlays"}]
    plan_args: dict[str, Any] = {}
    return steps, plan_args
