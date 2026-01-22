"""Performance snapshot (web-vitals-ish) for the current page."""

from __future__ import annotations

import json
import time
from contextlib import suppress
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def _safe_ms(x: Any) -> int | None:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return None
        if isinstance(x, (int, float)):
            return int(round(float(x)))
        s = str(x).strip()
        if not s:
            return None
        return int(round(float(s)))
    except Exception:
        return None


def _tier0_perf_snapshot(session) -> dict[str, Any] | None:
    """Tier-0 performance snapshot without relying on injected diagnostics."""
    out: dict[str, Any] = {"tier": "tier0", "available": True}

    # Navigation timings via Runtime (best-effort; may be blocked by dialogs).
    nav = None
    try:
        nav = session.eval_js(
            (
                "(() => {"
                "  try {"
                "    const out = {};"
                "    const e = (performance && performance.getEntriesByType) ? performance.getEntriesByType('navigation') : [];"
                "    const n = e && e.length ? e[0] : null;"
                "    if (n) {"
                "      out.nav = {"
                "        start: n.startTime,"
                "        ttfb: n.responseStart - n.startTime,"
                "        dcl: n.domContentLoadedEventEnd - n.startTime,"
                "        load: n.loadEventEnd - n.startTime,"
                "      };"
                "    } else {"
                "      const t = performance && performance.timing ? performance.timing : null;"
                "      if (t && t.navigationStart) {"
                "        out.nav = {"
                "          start: 0,"
                "          ttfb: t.responseStart - t.navigationStart,"
                "          dcl: t.domContentLoadedEventEnd - t.navigationStart,"
                "          load: t.loadEventEnd - t.navigationStart,"
                "        };"
                "      }"
                "    }"
                "    try {"
                "      const lt = (performance && performance.getEntriesByType) ? performance.getEntriesByType('longtask') : [];"
                "      if (lt && lt.length) {"
                "        const last = lt.slice(-50);"
                "        let total = 0;"
                "        let max = 0;"
                "        for (const x of last) {"
                "          const d = (x && typeof x.duration === 'number') ? x.duration : 0;"
                "          total += d;"
                "          if (d > max) max = d;"
                "        }"
                "        out.longTasks = { count: last.length, total, max };"
                "      }"
                "    } catch (e) {}"
                "    return out;"
                "  } catch (e) {}"
                "  return null;"
                "})()"
            ),
            timeout=1.2,
        )
    except Exception:
        nav = None

    if isinstance(nav, dict):
        timing_src = nav.get("nav") if isinstance(nav.get("nav"), dict) else nav
        timing = {
            **({"ttfb_ms": _safe_ms(timing_src.get("ttfb"))} if _safe_ms(timing_src.get("ttfb")) is not None else {}),
            **(
                {"domContentLoaded_ms": _safe_ms(timing_src.get("dcl"))}
                if _safe_ms(timing_src.get("dcl")) is not None
                else {}
            ),
            **({"load_ms": _safe_ms(timing_src.get("load"))} if _safe_ms(timing_src.get("load")) is not None else {}),
        }
        if timing:
            out["timing"] = timing
        lt = nav.get("longTasks") if isinstance(nav.get("longTasks"), dict) else None
        if isinstance(lt, dict):
            long_tasks = {
                **({"count": int(lt.get("count"))} if isinstance(lt.get("count"), (int, float)) else {}),
                **({"total_ms": _safe_ms(lt.get("total"))} if _safe_ms(lt.get("total")) is not None else {}),
                **({"max_ms": _safe_ms(lt.get("max"))} if _safe_ms(lt.get("max")) is not None else {}),
            }
            if long_tasks:
                out["longTasks"] = long_tasks

    # CPU/long-task-ish hints via CDP Performance.getMetrics (no injection).
    metrics = None
    try:
        with suppress(Exception):
            session.enable_performance()
        metrics = session.send("Performance.getMetrics")
    except Exception:
        metrics = None

    if isinstance(metrics, dict) and isinstance(metrics.get("metrics"), list):
        m: dict[str, Any] = {}
        for it in metrics.get("metrics", []):
            if not isinstance(it, dict):
                continue
            name = it.get("name")
            val = it.get("value")
            if isinstance(name, str):
                m[name] = val

        def sec_to_ms(v: Any) -> int | None:
            try:
                if v is None:
                    return None
                if isinstance(v, bool):
                    return None
                return int(round(float(v) * 1000.0))
            except Exception:
                return None

        cpu = {
            **({"task_ms": sec_to_ms(m.get("TaskDuration"))} if sec_to_ms(m.get("TaskDuration")) is not None else {}),
            **(
                {"script_ms": sec_to_ms(m.get("ScriptDuration"))}
                if sec_to_ms(m.get("ScriptDuration")) is not None
                else {}
            ),
            **(
                {"layout_ms": sec_to_ms(m.get("LayoutDuration"))}
                if sec_to_ms(m.get("LayoutDuration")) is not None
                else {}
            ),
            **(
                {"recalcStyle_ms": sec_to_ms(m.get("RecalcStyleDuration"))}
                if sec_to_ms(m.get("RecalcStyleDuration")) is not None
                else {}
            ),
        }
        if cpu:
            out["cpu"] = cpu

        mem = {
            **({"jsHeapUsed": m.get("JSHeapUsedSize")} if m.get("JSHeapUsedSize") is not None else {}),
            **({"jsHeapTotal": m.get("JSHeapTotalSize")} if m.get("JSHeapTotalSize") is not None else {}),
        }
        if mem:
            out["memory"] = mem

    return out if len(out) > 2 else None


def get_page_performance(config: BrowserConfig) -> dict[str, Any]:
    """Return a compact performance snapshot (web-vitals-ish).

    Tier-1 is best-effort (page injection). If unavailable (CSP, hardened pages, dialogs),
    degrade gracefully to Tier-0 (HAR-lite + navigation signals) instead of hard failing.
    """

    # Do not force diagnostics injection at session-creation time:
    # dialogs can block Runtime.evaluate and cause tool timeouts.
    with get_session(config, ensure_diagnostics=False) as (session, target):
        try:
            # Tier-0 is the reliability baseline (works without injection).
            tier0 = session_manager.ensure_telemetry(session)
            tier0_perf = None
            try:
                tier0_perf = _tier0_perf_snapshot(session)
            except Exception:
                tier0_perf = None

            # If a JS dialog is open, Runtime.evaluate will likely hang. Return Tier-0 only.
            try:
                tab_id = session.tab_id
                t0 = session_manager.tier0_snapshot(
                    tab_id,
                    since=max(0, int(time.time() * 1000) - 30_000),
                    offset=0,
                    limit=3,
                )
                if isinstance(t0, dict) and t0.get("dialogOpen") is True:
                    return {
                        "performance": {
                            "available": True,
                            "tier": "tier0",
                            "reason": "dialog_open",
                            "harLite": t0.get("harLite") if isinstance(t0.get("harLite"), list) else [],
                            "navigation": t0.get("navigation") if isinstance(t0.get("navigation"), list) else [],
                            "dialog": t0.get("dialog") if isinstance(t0.get("dialog"), dict) else None,
                            **({"tier0Perf": tier0_perf} if isinstance(tier0_perf, dict) else {}),
                        },
                        "tier0": tier0,
                        "target": target["id"],
                        "sessionTabId": session_manager.tab_id,
                    }
            except Exception:
                pass

            install = session_manager.ensure_diagnostics(session)

            js = (
                "(() => {"
                "  const d = globalThis.__mcpDiag;"
                "  if (!d || typeof d.vitals !== 'function' || typeof d.snapshot !== 'function') return null;"
                f"  const base = d.snapshot({json.dumps({'limit': 0, 'offset': 0, 'sort': 'start'})});"
                "  return {"
                "    url: base && base.url ? base.url : (location && location.href ? String(location.href) : ''),"
                "    title: base && base.title ? base.title : (document && document.title ? document.title : ''),"
                "    framework: base ? base.framework : null,"
                "    timing: base ? base.timing : null,"
                "    vitals: d.vitals(),"
                "    resourcesSummary: base && base.resources ? base.resources.summary : null,"
                "  };"
                "})()"
            )

            perf = session.eval_js(js)
            if not perf:
                # Tier-1 unavailable (common on hardened pages). Keep a useful Tier-0 fallback.
                t0 = None
                try:
                    if session.tab_id:
                        t0 = session_manager.tier0_snapshot(session.tab_id, since=None, offset=0, limit=20)
                except Exception:
                    t0 = None
                return {
                    "performance": {
                        "available": True,
                        "tier": "tier0",
                        "reason": "tier1_unavailable",
                        "harLite": (
                            t0.get("harLite") if isinstance(t0, dict) and isinstance(t0.get("harLite"), list) else []
                        ),
                        "navigation": (
                            t0.get("navigation")
                            if isinstance(t0, dict) and isinstance(t0.get("navigation"), list)
                            else []
                        ),
                        "note": "Tier-1 vitals unavailable on this page; using Tier-0 telemetry only",
                        **({"tier0Perf": tier0_perf} if isinstance(tier0_perf, dict) else {}),
                    },
                    "installed": install,
                    "tier0": tier0,
                    "target": target["id"],
                    "sessionTabId": session_manager.tab_id,
                }

            return {
                "performance": perf,
                "installed": install,
                "tier0": tier0,
                **({"tier0Perf": tier0_perf} if isinstance(tier0_perf, dict) else {}),
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except SmartToolError:
            raise
        except Exception as exc:
            raise SmartToolError(
                tool="page",
                action="performance",
                reason=str(exc),
                suggestion="Ensure the page is loaded and responsive",
            ) from exc
