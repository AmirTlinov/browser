from __future__ import annotations

DIAGNOSTICS_SCRIPT_VERSION = "7"


# NOTE: This script is intentionally self-contained and idempotent.
# It installs a small in-page ring-buffer capturing:
# - console.{debug,log,info,warn,error}
# - uncaught errors + resource load errors
# - unhandled promise rejections
# - fetch/XHR failures
#
# And provides best-effort insight helpers:
# - Web-vitals-ish (LCP/CLS/FCP) + long-tasks via PerformanceObserver
# - Resource timing snapshots (waterfall-ish) via ResourceTiming API
# - Locator suggestions (stable CSS selectors) for interactive elements
#
# It exposes `globalThis.__mcpDiag` with:
# - summary(): compact counts + last error
# - snapshot({limit, offset, sort}): last N entries + vitals + resources slice
# - resources({offset, limit, sort}): resource timing list
# - vitals(): performance + web-vitals-ish snapshot
# - locators({offset, limit, kind}): stable selector suggestions
# - clear(): reset buffers
DIAGNOSTICS_SCRIPT_SOURCE = r"""
(() => {
  const VERSION = "7";
  const g = globalThis;

  if (g.__mcpDiag && g.__mcpDiag.__version === VERSION) {
    return { ok: true, already: true, version: VERSION };
  }

  const prev = g.__mcpDiag && g.__mcpDiag.__version !== VERSION ? g.__mcpDiag : null;

  const MAX = 200;
  // Preserve more fidelity for stack traces / console payloads.
  // Tool output stays cognitively-cheap via server-side CTX rendering + artifact drilldown.
  const MAX_STR = 5000;

  const buf = prev
    ? null
    : {
        console: [],
        errors: [],
        rejections: [],
        network: [],
      };

  function now() {
    return Date.now();
  }

  function clampStr(s) {
    if (typeof s !== "string") return String(s);
    if (s.length <= MAX_STR) return s;
    return s.slice(0, MAX_STR) + `… <truncated len=${s.length}>`;
  }

  function safeToString(v) {
    try {
      if (v == null) return String(v);
      if (typeof v === "string") return clampStr(v);
      if (typeof v === "number" || typeof v === "boolean") return String(v);
      if (v instanceof Error) return clampStr(v.stack || v.message || String(v));

      const json = JSON.stringify(
        v,
        (_k, value) => {
          if (typeof value === "string") return clampStr(value);
          return value;
        },
        0,
      );
      return clampStr(json);
    } catch (_e) {
      try {
        return clampStr(String(v));
      } catch (_e2) {
        return "<unserializable>";
      }
    }
  }

  function push(kind, entry) {
    if (!buf) return;
    try {
      const arr = buf[kind];
      arr.push(entry);
      if (arr.length > MAX) arr.splice(0, arr.length - MAX);
    } catch (_e) {
      // ignore
    }
  }

  function sanitizeUrl(input) {
    try {
      const u = new URL(String(input || ""), g.location ? g.location.href : undefined);
      u.search = "";
      u.hash = "";
      return u.toString();
    } catch (_e) {
      return safeToString(input);
    }
  }

  function detectFramework() {
    try {
      const fw = {
        nextjs: !!g.__NEXT_DATA__ || !!document.querySelector("script#__NEXT_DATA__"),
        react: !!g.__REACT_DEVTOOLS_GLOBAL_HOOK__ || !!document.querySelector("[data-reactroot],[data-reactid]"),
        vue: !!g.__VUE_DEVTOOLS_GLOBAL_HOOK__ || !!document.querySelector("[data-v-app],[data-vue-meta]"),
        angular: !!document.querySelector("[ng-version]") || typeof g.getAllAngularRootElements === "function",
        svelte: !!g.__SVELTE_HMR,
      };

      const versions = {};
      try {
        if (fw.react && g.React && g.React.version) versions.react = safeToString(g.React.version);
      } catch (_e) {
        // ignore
      }

      try {
        if (fw.vue && g.Vue && g.Vue.version) versions.vue = safeToString(g.Vue.version);
      } catch (_e) {
        // ignore
      }

      try {
        const ng = document.querySelector("[ng-version]");
        if (ng) versions.angular = safeToString(ng.getAttribute("ng-version"));
      } catch (_e) {
        // ignore
      }

      try {
        const nextData = g.__NEXT_DATA__;
        if (nextData && typeof nextData === "object") {
          if (nextData.buildId) versions.nextjsBuildId = safeToString(nextData.buildId);
          if (nextData.nextExport != null) versions.nextjsExport = !!nextData.nextExport;
        }
      } catch (_e) {
        // ignore
      }

      const scripts = Array.from(document.scripts || [])
        .map((s) => s.src || "")
        .filter(Boolean)
        .slice(0, 200);

      fw.vite = scripts.some((s) => s.includes("@vite") || s.includes("vite"));
      fw.webpack = scripts.some((s) => s.includes("webpack"));
      fw.versions = versions;
      return fw;
    } catch (_e) {
      return {};
    }
  }

  function detectDevOverlay() {
    try {
      const vite = document.querySelector("vite-error-overlay");
      if (vite) {
        let text = "";
        try {
          text = (vite.shadowRoot ? vite.shadowRoot.textContent : vite.textContent) || "";
        } catch (_e) {
          text = "";
        }
        text = clampStr(String(text).replace(/\s+/g, " ").trim());
        return { type: "vite", text };
      }

      const next = document.querySelector("nextjs-portal");
      if (next) {
        let text = "";
        try {
          text = (next.shadowRoot ? next.shadowRoot.textContent : next.textContent) || "";
        } catch (_e) {
          text = "";
        }
        text = clampStr(String(text).replace(/\s+/g, " ").trim());
        return { type: "nextjs", text };
      }

      const wds =
        document.querySelector("webpack-dev-server-client-overlay") ||
        document.querySelector("webpack-dev-server-overlay") ||
        document.querySelector("#webpack-dev-server-client-overlay");
      if (wds) {
        const text = clampStr(String(wds.textContent || "").replace(/\s+/g, " ").trim());
        return { type: "webpack", text };
      }

      return null;
    } catch (_e) {
      return null;
    }
  }

  function tail(arr, limit) {
    if (!Array.isArray(arr)) return [];
    if (limit <= 0) return [];
    const start = Math.max(0, arr.length - limit);
    return arr.slice(start);
  }

  function filterSince(arr, since) {
    if (!Array.isArray(arr)) return [];
    if (typeof since !== "number" || !Number.isFinite(since) || since <= 0) return arr;
    return arr.filter((e) => e && typeof e.ts === "number" && e.ts > since);
  }

  function baseSummary() {
    if (prev && typeof prev.summary === "function") return prev.summary();
    if (!buf) return {};

    const consoleErrors = buf.console.filter((e) => e.level === "error").length;
    const consoleWarnings = buf.console.filter((e) => e.level === "warn").length;
    const jsErrors = buf.errors.filter((e) => e.type === "error").length;
    const resourceErrors = buf.errors.filter((e) => e.type === "resource").length;
    const unhandledRejections = buf.rejections.length;
    const failedRequests = buf.network.length;

    const lastError = (() => {
      const e = buf.errors[buf.errors.length - 1];
      if (!e) return null;
      if (e.type === "resource") return `${e.tag} failed: ${e.url}`;
      return e.message || null;
    })();

    return {
      consoleErrors,
      consoleWarnings,
      jsErrors,
      resourceErrors,
      unhandledRejections,
      failedRequests,
      lastError,
    };
  }

  function baseSnapshot(opts) {
    if (prev && typeof prev.snapshot === "function") return prev.snapshot(opts);
    const limit = Math.max(0, Math.min(MAX, (opts && opts.limit) || 50));
    return {
      version: VERSION,
      installedAt,
      url: g.location ? String(g.location.href) : "",
      title: (g.document && g.document.title) || "",
      readyState: (g.document && g.document.readyState) || "",
      userAgent: (g.navigator && g.navigator.userAgent) || "",
      framework: detectFramework(),
      timing: timing(),
      summary: baseSummary(),
      console: tail(buf.console, limit),
      errors: tail(buf.errors, limit),
      unhandledRejections: tail(buf.rejections, limit),
      network: tail(buf.network, limit),
    };
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Console / errors / network buffers (installed only on fresh pages)
  // ──────────────────────────────────────────────────────────────────────────

  if (!prev) {
    try {
      const orig = g.console;
      const levels = ["debug", "log", "info", "warn", "error"];
      for (const level of levels) {
        const fn = orig && orig[level];
        if (typeof fn !== "function") continue;

        const wrapped = function (...args) {
          push("console", {
            ts: now(),
            level,
            args: args.map(safeToString),
          });
          return fn.apply(this, args);
        };
        orig[level] = wrapped;
      }
    } catch (_e) {
      // ignore
    }

    try {
      g.addEventListener(
        "error",
        (ev) => {
          const t = ev && ev.target;
          const isResource = t && t !== g && t.tagName;

          if (isResource) {
            const tag = String(t.tagName || "");
            const url = t.src || t.href || "";
            push("errors", {
              ts: now(),
              type: "resource",
              tag,
              url: sanitizeUrl(url),
            });
            return;
          }

          push("errors", {
            ts: now(),
            type: "error",
            message: safeToString(ev && ev.message),
            filename: sanitizeUrl(ev && ev.filename),
            lineno: ev && ev.lineno,
            colno: ev && ev.colno,
            stack: ev && ev.error ? safeToString(ev.error.stack || ev.error.message || ev.error) : undefined,
          });
        },
        true,
      );
    } catch (_e) {
      // ignore
    }

    try {
      g.addEventListener("unhandledrejection", (ev) => {
        const reason = ev ? ev.reason : undefined;
        push("rejections", {
          ts: now(),
          message: safeToString(reason && (reason.message || reason)),
          stack: reason && reason.stack ? safeToString(reason.stack) : undefined,
        });
      });
    } catch (_e) {
      // ignore
    }

    try {
      const origFetch = g.fetch;
      if (typeof origFetch === "function") {
        const wrappedFetch = function (input, init) {
          const started = now();
          let url = "";
          try {
            url = typeof input === "string" ? input : input && input.url ? input.url : "";
          } catch (_e) {
            url = "";
          }
          const method = (init && init.method) || "GET";

          return origFetch
            .call(this, input, init)
            .then((resp) => {
              if (!resp || !resp.ok) {
                push("network", {
                  ts: started,
                  type: "fetch",
                  method,
                  url: sanitizeUrl(url),
                  status: resp ? resp.status : 0,
                  ok: !!(resp && resp.ok),
                  durationMs: now() - started,
                });
              }
              return resp;
            })
            .catch((err) => {
              push("network", {
                ts: started,
                type: "fetch",
                method,
                url: sanitizeUrl(url),
                status: 0,
                ok: false,
                error: safeToString(err && (err.message || err)),
                durationMs: now() - started,
              });
              throw err;
            });
        };
        g.fetch = wrappedFetch;
      }
    } catch (_e) {
      // ignore
    }

    try {
      const OrigXHR = g.XMLHttpRequest;
      if (typeof OrigXHR === "function") {
        function PatchedXHR() {
          const xhr = new OrigXHR();
          let method = "GET";
          let url = "";
          let started = 0;
          const origOpen = xhr.open;
          const origSend = xhr.send;

          xhr.open = function (m, u, ...rest) {
            method = String(m || "GET").toUpperCase();
            url = String(u || "");
            return origOpen.call(this, m, u, ...rest);
          };

          xhr.send = function (...args) {
            started = now();
            const onLoadEnd = () => {
              try {
                const status = xhr.status;
                const ok = status >= 200 && status < 400;
                if (!ok) {
                  push("network", {
                    ts: started,
                    type: "xhr",
                    method,
                    url: sanitizeUrl(url),
                    status,
                    ok,
                    durationMs: now() - started,
                  });
                }
              } catch (_e) {
                // ignore
              }
            };
            xhr.addEventListener("loadend", onLoadEnd, { once: true });
            return origSend.apply(this, args);
          };

          return xhr;
        }
        PatchedXHR.prototype = OrigXHR.prototype;
        g.XMLHttpRequest = PatchedXHR;
      }
    } catch (_e) {
      // ignore
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Performance observers (install once per page)
  // ──────────────────────────────────────────────────────────────────────────

  const perf = g.__mcpDiagPerf || (g.__mcpDiagPerf = { cls: 0, lcp: null, longtasks: [], installedAt: now() });

  if (!perf._installed) {
    perf._installed = true;

    try {
      const po = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          if (!e) continue;
          if (e.hadRecentInput) continue;
          perf.cls += e.value || 0;
        }
      });
      po.observe({ type: "layout-shift", buffered: true });
    } catch (_e) {
      // ignore
    }

    try {
      const po = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const e = entries && entries.length ? entries[entries.length - 1] : null;
        if (!e) return;
        const out = {
          startTime: e.startTime,
          renderTime: e.renderTime,
          loadTime: e.loadTime,
          size: e.size,
          url: e.url ? sanitizeUrl(e.url) : undefined,
        };

        try {
          if (e.element && e.element.getBoundingClientRect) {
            const el = e.element;
            const r = el.getBoundingClientRect();
            out.element = {
              tagName: el.tagName,
              id: el.id || null,
              className: el.className || null,
              text: clampStr((el.textContent || "").trim()),
              bounds: { x: r.x, y: r.y, width: r.width, height: r.height },
            };
          }
        } catch (_e2) {
          // ignore
        }

        perf.lcp = out;
      });
      po.observe({ type: "largest-contentful-paint", buffered: true });
    } catch (_e) {
      // ignore
    }

    try {
      const po = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          if (!e) continue;
          perf.longtasks.push({ startTime: e.startTime, duration: e.duration, name: e.name || "longtask" });
          if (perf.longtasks.length > 50) perf.longtasks.splice(0, perf.longtasks.length - 50);
        }
      });
      po.observe({ type: "longtask", buffered: true });
    } catch (_e) {
      // ignore
    }
  }

  function timing() {
    try {
      const nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
      if (!nav) return null;
      return {
        type: nav.type,
        startTime: nav.startTime,
        duration: nav.duration,
        redirectCount: nav.redirectCount,
        transferSize: nav.transferSize,
        encodedBodySize: nav.encodedBodySize,
        decodedBodySize: nav.decodedBodySize,
        domainLookup: nav.domainLookupEnd - nav.domainLookupStart,
        connect: nav.connectEnd - nav.connectStart,
        ttfb: nav.responseStart,
        response: nav.responseEnd - nav.responseStart,
        domContentLoaded: nav.domContentLoadedEventEnd,
        loadEventEnd: nav.loadEventEnd,
      };
    } catch (_e) {
      return null;
    }
  }

  function getPaint() {
    try {
      const out = {};
      const paints = performance.getEntriesByType ? performance.getEntriesByType("paint") : [];
      for (const p of paints || []) {
        if (!p || !p.name) continue;
        out[p.name] = p.startTime;
      }
      return out;
    } catch (_e) {
      return {};
    }
  }

  function vitals() {
    const paints = getPaint();
    const nav = timing();

    const longTasks = Array.isArray(perf.longtasks) ? perf.longtasks.slice(-10) : [];
    const longTaskTotal = longTasks.reduce((acc, t) => acc + (t.duration || 0), 0);
    const longTaskMax = longTasks.reduce((acc, t) => Math.max(acc, t.duration || 0), 0);

    let heap = null;
    try {
      if (performance && performance.memory) {
        heap = {
          usedJSHeapSize: performance.memory.usedJSHeapSize,
          totalJSHeapSize: performance.memory.totalJSHeapSize,
          jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
        };
      }
    } catch (_e) {
      heap = null;
    }

    return {
      fp: paints["first-paint"],
      fcp: paints["first-contentful-paint"],
      lcp: perf.lcp,
      cls: perf.cls,
      nav,
      longTasks: {
        count: longTasks.length,
        totalDuration: longTaskTotal,
        maxDuration: longTaskMax,
        recent: longTasks,
      },
      memory: heap,
    };
  }

  function resources(opts) {
    opts = opts || {};
    const limit = Math.max(0, Math.min(200, opts.limit || 50));
    const offset = Math.max(0, opts.offset || 0);
    const sort = String(opts.sort || "start");
    const since = typeof opts.since === "number" && Number.isFinite(opts.since) ? opts.since : 0;

    let timeOrigin = 0;
    try {
      if (performance && typeof performance.timeOrigin === "number") timeOrigin = performance.timeOrigin;
      else if (performance && performance.timing && typeof performance.timing.navigationStart === "number")
        timeOrigin = performance.timing.navigationStart;
      else if (performance && typeof performance.now === "function") timeOrigin = now() - performance.now();
    } catch (_e) {
      timeOrigin = 0;
    }

    let entries = [];
    try {
      entries = performance.getEntriesByType ? performance.getEntriesByType("resource") : [];
    } catch (_e) {
      entries = [];
    }

    const total = entries.length;

    const cache =
      g.__mcpDiagResourceCache ||
      (g.__mcpDiagResourceCache = { count: 0, builtAt: 0, mapped: null, summary: null, sorted: {} });

    const nowTs = now();
    const canUseCache =
      !!cache.mapped && !!cache.summary && cache.count === total && typeof cache.builtAt === "number" && nowTs - cache.builtAt < 1000;

    let mapped = canUseCache ? cache.mapped : null;
    let summary = canUseCache ? cache.summary : null;

    if (!mapped || !summary) {
      mapped = (entries || []).map((e) => {
        const url = sanitizeUrl(e.name);
        let host = "";
        try {
          host = new URL(url).host;
        } catch (_e) {
          host = "";
        }

        const startTime = e.startTime || 0;
        const epochMs = timeOrigin ? timeOrigin + startTime : 0;

        const out = {
          url,
          host,
          initiatorType: e.initiatorType,
          startTime,
          epochMs,
          duration: e.duration,
          transferSize: e.transferSize,
          encodedBodySize: e.encodedBodySize,
          decodedBodySize: e.decodedBodySize,
        };

        if (e.nextHopProtocol) out.nextHopProtocol = e.nextHopProtocol;
        if (typeof e.responseStatus === "number") out.responseStatus = e.responseStatus;
        if (e.renderBlockingStatus) out.renderBlockingStatus = e.renderBlockingStatus;
        if (e.deliveryType) out.deliveryType = e.deliveryType;
        if (e.cacheState) out.cacheState = e.cacheState;

        return out;
      });

      summary = (() => {
        const byType = {};
        let totalTransfer = 0;
        for (const r of mapped) {
          const k = r.initiatorType || "other";
          byType[k] = byType[k] || { count: 0, transferSize: 0 };
          byType[k].count += 1;
          byType[k].transferSize += r.transferSize || 0;
          totalTransfer += r.transferSize || 0;
        }
        const slowest = mapped
          .slice()
          .sort((a, b) => (b.duration || 0) - (a.duration || 0))
          .slice(0, 10)
          .map((r) => ({ url: r.url, duration: r.duration, initiatorType: r.initiatorType }));
        const largest = mapped
          .slice()
          .sort((a, b) => (b.transferSize || 0) - (a.transferSize || 0))
          .slice(0, 10)
          .map((r) => ({ url: r.url, transferSize: r.transferSize, initiatorType: r.initiatorType }));

        return { total, totalTransferSize: totalTransfer, byType, slowest, largest };
      })();

      // Refresh cache
      cache.count = total;
      cache.builtAt = nowTs;
      cache.mapped = mapped;
      cache.summary = summary;
      cache.sorted = {};
    }

    let sorted = cache.sorted && cache.sorted[sort];
    if (!Array.isArray(sorted)) {
      if (sort === "duration") {
        sorted = mapped.slice().sort((a, b) => (b.duration || 0) - (a.duration || 0));
      } else if (sort === "size") {
        sorted = mapped.slice().sort((a, b) => (b.transferSize || 0) - (a.transferSize || 0));
      } else {
        sorted = mapped.slice().sort((a, b) => (a.startTime || 0) - (b.startTime || 0));
      }
      cache.sorted[sort] = sorted;
    }

    const list = since > 0 ? sorted.filter((r) => typeof r.epochMs === "number" && r.epochMs > since) : sorted;

    if (since > 0) {
      const deltaSummary = (() => {
        const byType = {};
        let totalTransfer = 0;
        for (const r of list) {
          const k = r.initiatorType || "other";
          byType[k] = byType[k] || { count: 0, transferSize: 0 };
          byType[k].count += 1;
          byType[k].transferSize += r.transferSize || 0;
          totalTransfer += r.transferSize || 0;
        }
        const slowest = list
          .slice()
          .sort((a, b) => (b.duration || 0) - (a.duration || 0))
          .slice(0, 10)
          .map((r) => ({ url: r.url, duration: r.duration, initiatorType: r.initiatorType }));
        const largest = list
          .slice()
          .sort((a, b) => (b.transferSize || 0) - (a.transferSize || 0))
          .slice(0, 10)
          .map((r) => ({ url: r.url, transferSize: r.transferSize, initiatorType: r.initiatorType }));
        return { total: list.length, totalTransferSize: totalTransfer, byType, slowest, largest };
      })();

      const items = list.slice(offset, offset + limit);
      return { total: list.length, offset, limit, sort, since, summary: deltaSummary, items };
    }

    const items = list.slice(offset, offset + limit);
    return { total, offset, limit, sort, summary, items };
  }

  function _isVisible(el) {
    try {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return false;
      const style = g.getComputedStyle ? g.getComputedStyle(el) : null;
      if (!style) return true;
      if (style.display === "none" || style.visibility === "hidden") return false;
      if (Number(style.opacity || "1") === 0) return false;
      return true;
    } catch (_e) {
      return false;
    }
  }

  // Convert element bounds to top-level viewport coordinates.
  // Critical for same-origin iframes: element.getBoundingClientRect() is relative to
  // the iframe viewport, but tool clicks expect top-level viewport coords.
  function _rectToTop(el) {
    try {
      if (!el || !el.getBoundingClientRect) return null;
      const r = el.getBoundingClientRect();
      let x = r.x;
      let y = r.y;
      const w = r.width;
      const h = r.height;

      let win = el.ownerDocument && el.ownerDocument.defaultView ? el.ownerDocument.defaultView : null;
      let guard = 0;
      while (win && win.frameElement && guard < 12) {
        const fe = win.frameElement;
        const fr = fe.getBoundingClientRect();
        x += fr.x + (fe.clientLeft || 0);
        y += fr.y + (fe.clientTop || 0);
        try {
          win = win.parent;
        } catch (_e2) {
          break;
        }
        guard += 1;
      }

      return { x, y, width: w, height: h };
    } catch (_e) {
      return null;
    }
  }

  function _cssEscape(value) {
    try {
      if (g.CSS && typeof g.CSS.escape === "function") return g.CSS.escape(String(value));
      return String(value).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${c}`);
    } catch (_e) {
      return String(value);
    }
  }

  function _isUnique(selector) {
    try {
      return document.querySelectorAll(selector).length === 1;
    } catch (_e) {
      return false;
    }
  }

  function _bestSelector(el) {
    const tag = (el.tagName || "").toLowerCase();
    const candidates = [];

    const testAttrs = ["data-testid", "data-test", "data-qa", "data-cy", "data-e2e", "data-test-id"];
    for (const a of testAttrs) {
      const v = el.getAttribute && el.getAttribute(a);
      if (!v) continue;
      const sel = `[${a}="${_cssEscape(v)}"]`;
      candidates.push({ selector: sel, reason: a });
      if (_isUnique(sel)) return { best: sel, candidates };
    }

    if (el.id) {
      const sel = `#${_cssEscape(el.id)}`;
      candidates.push({ selector: sel, reason: "id" });
      if (_isUnique(sel)) return { best: sel, candidates };
    }

    const name = el.getAttribute && el.getAttribute("name");
    if (name) {
      const sel = `${tag}[name="${_cssEscape(name)}"]`;
      candidates.push({ selector: sel, reason: "name" });
      if (_isUnique(sel)) return { best: sel, candidates };
    }

    const aria = el.getAttribute && el.getAttribute("aria-label");
    if (aria) {
      const sel = `${tag}[aria-label="${_cssEscape(aria)}"]`;
      candidates.push({ selector: sel, reason: "aria-label" });
      if (_isUnique(sel)) return { best: sel, candidates };
    }

    const placeholder = el.getAttribute && el.getAttribute("placeholder");
    if (placeholder) {
      const sel = `${tag}[placeholder="${_cssEscape(placeholder)}"]`;
      candidates.push({ selector: sel, reason: "placeholder" });
      if (_isUnique(sel)) return { best: sel, candidates };
    }

    // Fallback: short CSS path with :nth-of-type
    try {
      const parts = [];
      let node = el;
      for (let depth = 0; depth < 6 && node && node.nodeType === 1 && node !== document.documentElement; depth++) {
        const t = node.tagName.toLowerCase();
        let part = t;
        if (node.id) {
          part = `${t}#${_cssEscape(node.id)}`;
          parts.unshift(part);
          const sel = parts.join(" > ");
          candidates.push({ selector: sel, reason: "path" });
          if (_isUnique(sel)) return { best: sel, candidates };
          break;
        }

        const parent = node.parentElement;
        if (!parent) break;
        const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        const idx = siblings.indexOf(node) + 1;
        if (siblings.length > 1) part = `${t}:nth-of-type(${idx})`;
        parts.unshift(part);

        const sel = parts.join(" > ");
        candidates.push({ selector: sel, reason: "path" });
        if (_isUnique(sel)) return { best: sel, candidates };

        node = parent;
      }
    } catch (_e) {
      // ignore
    }

    const fallback = candidates.length ? candidates[candidates.length - 1].selector : tag;
    return { best: fallback, candidates };
  }

  function locators(opts) {
    opts = opts || {};
    const kind = opts.kind ? String(opts.kind) : "all";
    const limit = Math.max(0, Math.min(200, opts.limit || 50));
    const offset = Math.max(0, opts.offset || 0);

    // Collect document + open shadow roots + same-origin iframes (best-effort).
    const ROOTS = (() => {
      const roots = [];
      const queue = [{ root: document, depth: 0 }];
      const MAX_ROOTS = 60;
      const MAX_DEPTH = 6;
      const MAX_SCAN = 4000;

      while (queue.length && roots.length < MAX_ROOTS) {
        const item = queue.shift();
        const root = item && item.root;
        const depth = item && typeof item.depth === "number" ? item.depth : 0;
        if (!root) continue;
        if (roots.includes(root)) continue;
        roots.push(root);
        if (depth >= MAX_DEPTH) continue;
        if (!root.querySelectorAll) continue;

        let scanned = 0;
        for (const el of root.querySelectorAll("*")) {
          scanned += 1;
          if (scanned > MAX_SCAN) break;
          if (el && el.shadowRoot) {
            queue.push({ root: el.shadowRoot, depth: depth + 1 });
            if (roots.length + queue.length >= MAX_ROOTS) break;
          }
          if (el && (el.tagName === "IFRAME" || el.tagName === "FRAME")) {
            try {
              const doc = el.contentDocument || (el.contentWindow && el.contentWindow.document);
              if (doc) {
                queue.push({ root: doc, depth: depth + 1 });
                if (roots.length + queue.length >= MAX_ROOTS) break;
              }
            } catch (_e3) {
              // Cross-origin frame; ignore.
            }
          }
        }
      }
      return roots;
    })();

    const queryAll = (selector, maxTotal) => {
      const out = [];
      for (const r of ROOTS) {
        try {
          out.push(...Array.from(r.querySelectorAll(selector)));
          if (maxTotal && out.length >= maxTotal) break;
        } catch (_e) {
          // ignore
        }
      }
      return maxTotal ? out.slice(0, maxTotal) : out;
    };

    const forms = queryAll("form", 200);
    const formIndexByEl = new Map();
    for (let i = 0; i < forms.length; i++) formIndexByEl.set(forms[i], i);

    function formIndexFor(el) {
      try {
        const form = el && (el.form || (el.closest ? el.closest("form") : null));
        if (form && formIndexByEl.has(form)) return formIndexByEl.get(form);
      } catch (_e) {
        // ignore
      }
      return null;
    }

    function inputLabel(el) {
      if (!el) return "";

      try {
        if (el.labels && el.labels[0]) {
          const t = String(el.labels[0].textContent || "").replace(/\s+/g, " ").trim();
          if (t) return t;
        }
      } catch (_e) {
        // ignore
      }

      try {
        const parentLabel = el.closest ? el.closest("label") : null;
        if (parentLabel) {
          const t = String(parentLabel.textContent || "").replace(/\s+/g, " ").trim();
          if (t) return t;
        }
      } catch (_e) {
        // ignore
      }

      try {
        const id = el.id ? String(el.id) : "";
        if (id) {
          const idEsc = _cssEscape(id);
          for (const r of ROOTS) {
            try {
              const lbl = r.querySelector(`label[for="${idEsc}"]`);
              if (!lbl) continue;
              const t = String(lbl.textContent || "").replace(/\s+/g, " ").trim();
              if (t) return t;
            } catch (_e2) {
              // ignore
            }
          }
        }
      } catch (_e) {
        // ignore
      }

      const aria = el.getAttribute && el.getAttribute("aria-label");
      if (aria) return String(aria);
      const placeholder = el.getAttribute && el.getAttribute("placeholder");
      if (placeholder) return String(placeholder);
      const name = el.getAttribute && el.getAttribute("name");
      if (name) return String(name);
      if (el.id) return String(el.id);
      return "";
    }

    const items = [];
    const counters = new Map();

    function nextIndex(kindName, text) {
      const key = `${kindName}:${text}`;
      const idx = counters.get(key) || 0;
      counters.set(key, idx + 1);
      return idx;
    }

    function add(kindName, el, extra) {
      if (!el || !_isVisible(el)) return;
      const sel = _bestSelector(el);
      let bounds = null;
      try {
        bounds = _rectToTop(el);
        if (!bounds) {
          const r = el.getBoundingClientRect();
          bounds = { x: r.x, y: r.y, width: r.width, height: r.height };
        }
      } catch (_e) {
        bounds = null;
      }

      let inShadow = false;
      try {
        inShadow = !!(el.getRootNode && el.getRootNode() !== document);
      } catch (_e) {
        inShadow = false;
      }

      const out = {
        kind: kindName,
        selector: sel.best,
        selectorCandidates: sel.candidates.slice(0, 5),
        tagName: el.tagName,
        ...(bounds && {
          bounds,
          center: { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 },
        }),
        ...(inShadow && { inShadowDOM: true }),
        ...(extra || {}),
      };

      if (kindName === "input" && !out.actionHint) {
        const t = String(out.inputType || "").toLowerCase();
        const fi = typeof out.formIndex === "number" ? out.formIndex : null;
        const key = clampStr(String(out.fillKey || out.label || out.name || out.id || "").trim());

        if (key) {
          const keyJson = JSON.stringify(key);
          const value = t === "checkbox" || t === "radio" ? "true" : t === "password" ? '"<secret>"' : '"..."';
          out.actionHint = fi != null ? `form(fill={${keyJson}: ${value}}, form_index=${fi})` : `form(fill={${keyJson}: ${value}})`;
        } else if (t === "checkbox" || t === "radio") {
          out.actionHint = `click(selector=${JSON.stringify(sel.best)})`;
        } else {
          out.actionHint = `type(selector=${JSON.stringify(sel.best)}, text="...")`;
        }
      }

      items.push(out);
    }

    if (kind === "all" || kind === "button") {
      const btns = queryAll('button, input[type="button"], input[type="submit"], [role="button"]', 500);
      for (const b of btns) {
        const text = (b.textContent || b.value || b.getAttribute("aria-label") || "").trim();
        if (!text) continue;
        const t = clampStr(text);
        const idx = nextIndex("button", t);
        add("button", b, {
          text: t,
          index: idx,
          actionHint: `click(text=${JSON.stringify(t)}, role="button", index=${idx})`,
        });
      }
    }

    if (kind === "all" || kind === "link") {
      const links = queryAll('a[href], [role="link"]', 800);
      for (const a of links) {
        const text = (a.textContent || a.getAttribute("aria-label") || "").trim();
        if (!text) continue;
        const href = a.getAttribute("href") || "";
        const t = clampStr(text);
        const idx = nextIndex("link", t);
        add("link", a, {
          text: t,
          index: idx,
          href: sanitizeUrl(href),
          actionHint: `click(text=${JSON.stringify(t)}, role="link", index=${idx})`,
        });
      }
    }

    if (kind === "all" || kind === "input") {
      const inputs = queryAll('input, textarea, select', 800);
      for (const el of inputs) {
        const type = (el.getAttribute("type") || el.tagName).toLowerCase();
        if (type === "hidden") continue;
        const label = inputLabel(el).trim();
        const name = el.getAttribute && el.getAttribute("name") ? String(el.getAttribute("name")) : "";
        const id = el.id ? String(el.id) : "";
        const placeholder = el.getAttribute && el.getAttribute("placeholder") ? String(el.getAttribute("placeholder")) : "";
        const fillKey = (label || name || id || placeholder || "").trim();
        const formIndex = formIndexFor(el);
        add("input", el, {
          inputType: type,
          label: clampStr(label),
          fillKey: clampStr(fillKey),
          ...(formIndex != null && { formIndex }),
          ...(name && { name: clampStr(name) }),
          ...(id && { id: clampStr(id) }),
          ...(placeholder && { placeholder: clampStr(placeholder) }),
        });
      }
    }

    const total = items.length;
    return { total, offset, limit, kind, items: items.slice(offset, offset + limit) };
  }

  const installedAt = prev && prev.installedAt ? prev.installedAt : now();

  function snapshot(opts) {
    opts = opts || {};
    const since = typeof opts.since === "number" && Number.isFinite(opts.since) ? opts.since : 0;
    const cursor = now();
    const base = baseSnapshot(opts) || {};

    const consoleOut = filterSince(base.console, since);
    const errorsOut = filterSince(base.errors, since);
    const rejectionsOut = filterSince(base.unhandledRejections, since);
    const networkOut = filterSince(base.network, since);

    const out = {
      ...base,
      version: VERSION,
      installedAt,
      cursor,
      ...(since > 0 && {
        since,
        delta: {
          console: consoleOut.length,
          errors: errorsOut.length,
          unhandledRejections: rejectionsOut.length,
          network: networkOut.length,
        },
      }),
      url: g.location ? String(g.location.href) : base.url || "",
      title: (g.document && g.document.title) || base.title || "",
      readyState: (g.document && g.document.readyState) || base.readyState || "",
      userAgent: (g.navigator && g.navigator.userAgent) || base.userAgent || "",
      framework: detectFramework(),
      devOverlay: detectDevOverlay(),
      timing: timing(),
      summary: baseSummary(),
      console: consoleOut,
      errors: errorsOut,
      unhandledRejections: rejectionsOut,
      network: networkOut,
      vitals: vitals(),
      resources: resources({
        offset: opts.offset || 0,
        limit: opts.limit || 50,
        sort: opts.sort || "start",
        ...(since > 0 && { since }),
      }),
    };
    return out;
  }

  function clear() {
    try {
      if (prev && typeof prev.clear === "function") prev.clear();
    } catch (_e) {
      // ignore
    }
    if (buf) {
      buf.console.length = 0;
      buf.errors.length = 0;
      buf.rejections.length = 0;
      buf.network.length = 0;
    }
    try {
      perf.cls = 0;
      perf.lcp = null;
      perf.longtasks.length = 0;
    } catch (_e) {
      // ignore
    }
  }

  g.__mcpDiag = {
    __version: VERSION,
    installedAt,
    summary: baseSummary,
    snapshot,
    resources,
    vitals,
    locators,
    clear,
  };

  return { ok: true, installed: true, version: VERSION, upgraded: !!prev };
})()
"""
