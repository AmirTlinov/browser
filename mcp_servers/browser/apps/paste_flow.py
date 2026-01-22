from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import time
from dataclasses import dataclass
from typing import Any

from .. import tools
from ..config import BrowserConfig
from ..tools.base import SmartToolError, get_session
from ..tools.smart.overlay import dismiss_blocking_overlay_best_effort


@dataclass(frozen=True)
class PasteAttempt:
    ok: bool
    method: str
    focus: dict[str, Any] | None = None
    screenshot: dict[str, Any] | None = None
    screenshotHash: str | None = None


def _screenshot_hash(
    config: BrowserConfig, *, backend_dom_node_id: int | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        shot = (
            tools.screenshot(config, backend_dom_node_id=backend_dom_node_id)
            if backend_dom_node_id
            else tools.screenshot(config)
        )
    except Exception:
        return None, None
    b64 = shot.get("image") if isinstance(shot, dict) else None
    if not isinstance(b64, str) or not b64:
        return shot if isinstance(shot, dict) else None, None

    # Prefer a perceptual hash (robust to small UI jitter); fallback to sha256 of base64.
    try:
        from PIL import Image  # type: ignore[import-not-found]

        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw)).convert("L").resize((16, 16))
        px = list(img.getdata())
        avg = sum(px) / max(1, len(px))
        bits = "".join("1" if p > avg else "0" for p in px)
        # 256-bit binary string -> 64 hex chars
        hx = f"{int(bits, 2):064x}"
        return shot if isinstance(shot, dict) else None, f"ahash:{hx}"
    except Exception:
        h = hashlib.sha256(b64.encode("utf-8")).hexdigest()
        return shot if isinstance(shot, dict) else None, f"sha256:{h}"


def _choose_workspace_point(config: BrowserConfig) -> dict[str, Any] | None:
    """Pick a likely 'main workspace' point via hit-testing (cross-site best-effort)."""
    js = r"""
    (() => {
      const vw = window.innerWidth || 0;
      const vh = window.innerHeight || 0;
      if (!vw || !vh) return null;

      const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
      const scoreEl = (el, rect) => {
        if (!el || !rect) return -1;
        const tag = String(el.tagName || '').toUpperCase();
        const role = String(el.getAttribute?.('role') || '').toLowerCase();
        const id = String(el.id || '');
        const cls = String(el.className || '');

        // ignore tiny/zero areas and structural roots
        const area = Math.max(0, rect.width) * Math.max(0, rect.height);
        if (area < 5000) return -1;
        if (tag === 'HTML' || tag === 'BODY') return -1;

        let score = area;

        // Prefer real canvases / svgs / app roots
        if (tag === 'CANVAS') score += area * 0.9;
        if (tag === 'SVG') score += area * 0.4;
        if (role === 'application') score += area * 0.25;

        const hint = (id + ' ' + cls).toLowerCase();
        if (hint.includes('canvas') || hint.includes('board') || hint.includes('workspace') || hint.includes('surface')) {
          score += area * 0.2;
        }

        // Penalize obvious chrome: headers/nav/sidebars/toolbars
        if (['HEADER','NAV','ASIDE','FOOTER'].includes(tag)) score -= area * 0.95;
        if (hint.includes('toolbar') || hint.includes('sidebar') || hint.includes('topbar') || hint.includes('menubar')) score -= area * 0.8;

        // Penalize typical top chrome region (even if it's a DIV)
        if (rect.y >= 0 && rect.y < vh * 0.18 && rect.height < vh * 0.4) score -= area * 0.6;

        // Prefer elements that actually cover the center of the viewport
        const cx = vw * 0.5;
        const cy = vh * 0.5;
        if (cx >= rect.x && cx <= rect.x + rect.width && cy >= rect.y && cy <= rect.y + rect.height) score += area * 0.15;

        // Filter out non-interactive overlays when possible
        try {
          const st = window.getComputedStyle(el);
          if (st && (st.pointerEvents === 'none' || st.visibility === 'hidden' || st.display === 'none')) return -1;
        } catch (e) {}

        return score;
      };

      const points = [];
      const xs = [0.2, 0.35, 0.5, 0.65, 0.8];
      const ys = [0.25, 0.4, 0.5, 0.6, 0.75];
      for (const fx of xs) for (const fy of ys) points.push([Math.floor(vw * fx), Math.floor(vh * fy)]);

      let best = null;
      let bestScore = -1;

      for (const [x0, y0] of points) {
        const x = clamp(x0, 1, vw - 2);
        const y = clamp(y0, 1, vh - 2);
        let el = document.elementFromPoint(x, y);
        for (let i = 0; i < 8 && el; i++) {
          const rect = el.getBoundingClientRect?.();
          if (rect) {
            const sc = scoreEl(el, rect);
            if (sc > bestScore) {
              bestScore = sc;
              best = { x, y, score: sc, tagName: el.tagName, id: el.id || null, className: String(el.className || '').slice(0, 120), rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height } };
            }
          }
          el = el.parentElement;
        }
      }

      if (!best) return null;

      // Prefer clicking the element center (safer than random sampled point).
      const r = best.rect;
      const cx = clamp(r.x + r.w * 0.5, 10, vw - 10);
      const cy = clamp(r.y + r.h * 0.5, 10, vh - 10);
      return { ...best, x: cx, y: cy, vw, vh, source: 'hit_test' };
    })()
    """
    try:
        res = tools.eval_js(config, js)
        return res if isinstance(res, dict) else None
    except Exception:
        return None


def _backend_node_for_location(config: BrowserConfig, *, x: float, y: float) -> dict[str, Any] | None:
    """Resolve a backend node id for a viewport point via CDP DOM.getNodeForLocation (best-effort)."""
    try:
        xi = int(round(float(x)))
        yi = int(round(float(y)))
    except Exception:
        return None
    if xi < 0 or yi < 0:
        return None
    try:
        with get_session(config, ensure_diagnostics=False) as (session, _target):
            with contextlib.suppress(Exception):
                session.enable_dom()

            res = None
            try:
                res = session.send(
                    "DOM.getNodeForLocation",
                    {"x": xi, "y": yi, "includeUserAgentShadowDOM": True},
                )
            except Exception:
                res = session.send("DOM.getNodeForLocation", {"x": xi, "y": yi})

            if not isinstance(res, dict):
                return None

            backend_node_id = res.get("backendNodeId")
            node_id = res.get("nodeId")
            out: dict[str, Any] = {}
            if isinstance(backend_node_id, int) and backend_node_id > 0:
                out["backendDOMNodeId"] = int(backend_node_id)
            if isinstance(node_id, int) and node_id > 0:
                out["nodeId"] = int(node_id)
            return out or None
    except Exception:
        return None


def focus_canvas_best_effort(config: BrowserConfig) -> dict[str, Any] | None:
    """Try to focus the main canvas/work area (cross-site best-effort)."""
    with contextlib.suppress(Exception):
        tools.press_key(config, "Escape", modifiers=0)

    # Generic overlay dismissal: helps when cookie banners/onboarding dialogs intercept clicks.
    # Run only a couple of attempts to keep this cognitively cheap.
    try:
        for _ in range(2):
            dismissed = dismiss_blocking_overlay_best_effort(config)
            if not dismissed:
                break
            time.sleep(0.08)
    except Exception:
        pass

    # Hit-test first: reduces misclicks on toolbars/topbars on apps like Miro/Figma.
    hit = _choose_workspace_point(config)
    if isinstance(hit, dict) and hit.get("x") is not None and hit.get("y") is not None:
        try:
            x = float(hit["x"])
            y = float(hit["y"])
            tools.click_at_pixel(config, x=x, y=y, button="left", click_count=1)
            backend = _backend_node_for_location(config, x=x, y=y) or {}
            return {
                "x": x,
                "y": y,
                "source": "hit_test",
                "candidate": {k: hit.get(k) for k in ("tagName", "id", "className", "rect", "score")},
                **backend,
            }
        except Exception:
            pass

    try:
        viewport = tools.eval_js(config, "({vw: window.innerWidth, vh: window.innerHeight})") or {}
        vw = float(viewport.get("vw", 0.0))
        vh = float(viewport.get("vh", 0.0))
        if vw <= 0 or vh <= 0:
            raise ValueError("invalid viewport")
        x = max(10.0, min(vw - 10.0, vw * 0.5))
        y = max(10.0, min(vh - 10.0, vh * 0.5))
        tools.click_at_pixel(config, x=x, y=y, button="left", click_count=1)
        backend = _backend_node_for_location(config, x=x, y=y) or {}
        return {"x": x, "y": y, "vw": vw, "vh": vh, "source": "center", **backend}
    except Exception:
        return None


def paste_best_effort(
    config: BrowserConfig,
    *,
    prefer: str = "ctrl",
    verify_screenshot: bool = False,
    settle_ms: int = 350,
) -> dict[str, Any]:
    """Paste clipboard into the focused app (best-effort).

    Returns a dict containing:
    - ok: whether key dispatch succeeded
    - method: 'ctrl+v' or 'meta+v'
    - focus: focus click metadata (best-effort)
    - screenshotHashBefore/After (optional)
    """
    prefer = str(prefer or "ctrl").strip().lower()
    verify_screenshot = bool(verify_screenshot)
    settle_ms = max(50, min(int(settle_ms), 3000))

    focus = focus_canvas_best_effort(config)
    focus_backend = focus.get("backendDOMNodeId") if isinstance(focus, dict) else None

    shot_before: dict[str, Any] | None = None
    hash_before: str | None = None
    if verify_screenshot:
        backend_id = int(focus_backend) if isinstance(focus_backend, int) else None
        shot_before, hash_before = _screenshot_hash(config, backend_dom_node_id=backend_id)

    method = None
    last_err: Exception | None = None

    try_order = ["ctrl", "meta"] if prefer != "meta" else ["meta", "ctrl"]
    for kind in try_order:
        try:
            if kind == "meta":
                tools.press_key(config, "v", modifiers=4)
                method = "meta+v"
            else:
                tools.press_key(config, "v", modifiers=2)
                method = "ctrl+v"
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    if last_err is not None:
        raise SmartToolError(
            tool="paste_flow",
            action="paste",
            reason=str(last_err),
            suggestion="Ensure the tab is focused and does not have a blocking dialog; try clicking the canvas and retry",
        ) from last_err

    time.sleep(settle_ms / 1000.0)

    shot_after: dict[str, Any] | None = None
    hash_after: str | None = None
    if verify_screenshot:
        backend_id = int(focus_backend) if isinstance(focus_backend, int) else None
        shot_after, hash_after = _screenshot_hash(config, backend_dom_node_id=backend_id)

    changed: bool | None = None
    distance: int | None = None
    threshold = 10
    if verify_screenshot and hash_before and hash_after:
        if hash_before.startswith("ahash:") and hash_after.startswith("ahash:"):
            try:
                a = int(hash_before.split(":", 1)[1], 16)
                b = int(hash_after.split(":", 1)[1], 16)
                distance = int((a ^ b).bit_count())
                changed = distance >= threshold
            except Exception:
                changed = hash_before != hash_after
        else:
            changed = hash_before != hash_after

    return {
        "ok": True,
        "method": method or "ctrl+v",
        "focus": focus,
        **(
            {
                "verify": {
                    "before": {"hash": hash_before},
                    "after": {"hash": hash_after},
                    **({"hamming": distance, "threshold": threshold} if distance is not None else {}),
                },
                "changed": changed,
            }
            if verify_screenshot
            else {}
        ),
    }
