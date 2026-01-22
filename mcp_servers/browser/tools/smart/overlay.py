from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ..base import get_session


def dismiss_blocking_overlay_best_effort(
    config: BrowserConfig,
    *,
    session: Any | None = None,  # BrowserSession, but keep Any to avoid import cycles
) -> dict[str, Any] | None:
    """Best-effort close of blocking DOM overlays/modals (cookie banners, onboarding, etc.).

    Goal:
    - Improve robustness of canvas workflows and UI automation on arbitrary sites/apps.
    - Stay generic: no app-specific selectors.

    Strategy:
    - Look at elementFromPoint(center).
    - If it (or an ancestor) looks like a modal/dialog/backdrop, search inside for a close/dismiss
      button and click it.
    """

    js = r"""
    (() => {
      const vw = window.innerWidth || 0;
      const vh = window.innerHeight || 0;
      if (!vw || !vh) return null;

      const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
      const within = (rect) => rect && rect.width > 2 && rect.height > 2 && rect.right > 0 && rect.bottom > 0 && rect.left < vw && rect.top < vh;
      const isVisible = (el) => {
        try {
          const st = window.getComputedStyle(el);
          if (!st || st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0' || st.pointerEvents === 'none') return false;
        } catch (e) {}
        const r = el.getBoundingClientRect?.();
        return !!(r && within(r));
      };
      const textOf = (el) => {
        const pick = (s) => String(s || '').replace(/\s+/g, ' ').trim();
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

        // Only consider "blocking" surfaces that cover a meaningful portion of the viewport.
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

      const cx0 = clamp(Math.floor(vw * 0.5), 1, vw - 2);
      const cy0 = clamp(Math.floor(vh * 0.5), 1, vh - 2);
      let el = document.elementFromPoint(cx0, cy0);
      if (!el) return null;

      let overlay = null;
      for (let i = 0; i < 10 && el; i++) {
        if (looksLikeOverlay(el) && isVisible(el)) { overlay = el; break; }
        el = el.parentElement;
      }
      if (!overlay) return null;

      const scoreButton = (t, hint) => {
        const s = (String(t || '') + ' ' + String(hint || '')).toLowerCase();
        // Prefer explicit close/dismiss over accept/continue.
        const close = /(close|dismiss|cancel|skip|later|not now|×|x\b|закры|отмен|пропус|позже|не сейчас)/i;
        const accept = /(accept|agree|ok|got it|continue|allow|yes|соглас|принять|ок|продолж|разреш|да)/i;
        const reject = /(reject|decline|no|deny|отклон|нет|запрет)/i;
        if (close.test(s)) return 100;
        if (reject.test(s)) return 60;
        if (accept.test(s)) return 30;
        return 10;
      };

      const candidates = [];
      const nodes = overlay.querySelectorAll('button,[role="button"],a,input[type="button"],input[type="submit"],div[role="button"],span[role="button"]');
      for (const b of nodes) {
        if (!b || !isVisible(b) || !b.getBoundingClientRect) continue;
        const r = b.getBoundingClientRect();
        if (!within(r)) continue;
        const x = clamp(r.left + r.width * 0.5, 5, vw - 5);
        const y = clamp(r.top + r.height * 0.5, 5, vh - 5);
        const label = textOf(b);
        const hint = (String(b.getAttribute?.('data-testid') || '') + ' ' + String(b.id || '') + ' ' + String(b.className || '')).slice(0, 200);
        const score = scoreButton(label, hint);
        candidates.push({ x, y, label, score, tagName: b.tagName, hint });
      }

      if (!candidates.length) return { overlay: { tagName: overlay.tagName, id: overlay.id || null }, reason: 'overlay_no_buttons' };
      candidates.sort((a, b) => b.score - a.score);
      const best = candidates[0];

      return {
        x: best.x,
        y: best.y,
        score: best.score,
        label: best.label || null,
        reason: 'overlay_click',
        overlay: {
          tagName: overlay.tagName,
          id: overlay.id || null,
          className: String(overlay.className || '').slice(0, 120),
        }
      };
    })()
    """

    def _run(sess: Any) -> dict[str, Any] | None:
        try:
            res = sess.eval_js(js)
        except Exception:
            return None

        if not isinstance(res, dict):
            return None
        x = res.get("x")
        y = res.get("y")
        if x is None or y is None:
            return None
        try:
            sess.click(float(x), float(y), button="left", click_count=1)
            return {"ok": True, "action": "dismiss_overlay", "clicked": {"x": float(x), "y": float(y)}, "meta": res}
        except Exception:
            return None

    if session is not None:
        return _run(session)

    try:
        with get_session(config, ensure_diagnostics=False) as (sess, _t):
            return _run(sess)
    except Exception:
        return None
