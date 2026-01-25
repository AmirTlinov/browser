 [LEGEND]
PLAYBOOK = A small set of high-leverage usage patterns for agents.
OVERVIEW_FIRST = The habit: request a compact overview before drilldowns.
COMPLEX_FLOW = A 1–3 call pattern for multi-step scenarios: map → run (assert/when/macro/act) → artifacts.
ACTION_MAP = The actions-first map returned by `page(detail="map")`.
V3_INTERNAL_ACTIONS = The v3+ `run(...)` internal action keys: `assert`, `when`, `repeat`, `macro`.
ASSERT = A run-internal check that fails fast when a condition is unmet.
WHEN = A run-internal conditional that gates nested actions.
REPEAT = A run-internal bounded loop that repeats nested actions (`repeat`) without external MCP calls.
MACRO = A run-internal action that expands into regular steps (see `docs/MACROS.md`).
MACRO_SPEC = The macro input shape: `{macro:{name:"...", args:{...}, dry_run:true}}`.
TOOL_COUNTS = A per-tool histogram returned by `flow.flow.toolCounts` / `run.run.toolCounts`.
RUN_GUIDE = A minimal-call run/macro/runbook quickref (`docs/RUN_GUIDE.md`).
AUTO_TAB = Auto-switch to a newly opened tab after click-like actions.
AUTO_AFFORDANCES = Auto-refresh affordances when `act(ref/label)` looks stale.
ONE_CALL_EXTRACT = A single `run(...)` pipeline that expands → scrolls → extracts in one call.
EXTRACT_VARIANTS = Pre-tuned one-call extract variants for articles, tables, and listings.

 [CONTENT]
This is the [PLAYBOOK] for using the MCP browser server with minimal [NOISE|LEGEND.md].

## [OVERVIEW_FIRST] (default)
1) `browser(action="launch")` (only if needed)
2) `navigate(url="...")`
3) `page()` for a compact structure overview (in MCP_TOOLSET=v2 it returns the actions-first map)

Then choose exactly one drilldown ([DRILLDOWN|LEGEND.md]) based on the task:
- Interact (fastest, actions-first): `page(detail="map")` → `run(actions=[{act:{ref:"aff:..."}}])`
- Cross-page memory: `page(detail="graph")` (visited nodes + discovered links)

## [ONE_CALL_EXTRACT]
Use this when the goal is **content extraction** with minimal calls.

Base pattern:
```
run(actions=[
  {"navigate": {"url": "https://example.com/article"}},
  {"macro": {"name": "auto_expand_scroll_extract", "args": {
    "expand": true,
    "scroll": {"max_iters": 6},
    "extract": {"content_type": "overview"}
  }}}
], report="map")
```

## [EXTRACT_VARIANTS]
- Article: set `extract.content_type="main"` (optionally `limit=12`).
- Tables: set `extract.content_type="table"`; follow up with `table_index=N` using the hint.
- Listings: set `extract.content_type="links"`; raise `limit` or `scroll.max_iters` for infinite feeds.
- Interact: `page(detail="locators")` → `click(...)` / `type(...)` / `form(...)`
- Iframes/SSO/CAPTCHA layout: `page(detail="frames")` (CDP frame tree) → `page(detail="frames", with_screenshot=true)` (visual boxes)

Tips:
- Use `auto_tab=true` when a click is expected to open a new tab ([AUTO_TAB]).
- Keep `auto_affordances=true` (default) to make `act(ref/label)` resilient across navigation ([AUTO_AFFORDANCES]).

## Minimal-call decision (fast)
- If a [CANVAS_APP|LEGEND.md]: prefer `app(...)` (or `run(actions=[{"tool":"app",...}])`) over chatty click/drag loops.
- If the workflow repeats across sessions: record a runbook via `run(..., record_memory_key="...")` and execute via `runbook(action="run", ...)` (see `docs/RUNBOOKS.md`).
- If you need reuse *inside* a larger `run`: use `macro: include_memory_steps` (see `docs/MACROS.md`).
- If a task can fit in 1–2 calls: use `run(...)` directly or `page(detail="map")` → `run(...)`.
- For branching/retries: use internal `assert/when/repeat` instead of external loops.
- Interact (visual disambiguation): `page(detail="locators", with_screenshot=true)` → pick `n` → `click(x=..., y=...)`
- Interact (complex UI): `page(detail="ax", role="button", name="...")` → `click(text="...", role="button", strategy="ax")`
- Interact (complex UI, disambiguation): `page(detail="ax", role="button", name="...", with_screenshot=true)` → pick `n` → `click(ref="dom:...")`
- Stable handle: `page(detail="ax", ...)` → `click(ref="dom:123")` (or `backendDOMNodeId=...`) (no re-search)
- Iframe-safe input focus: `form(focus_key="Email", form_index=0)` (works across same-origin iframes + open shadow DOM)
- Stable handle typing: `page(detail="ax", ...)` → `type(ref="dom:123", text="...")` (or `backendDOMNodeId=...`)
- Stable handle hover/drag: `mouse(action="hover", ref="dom:123")` / `mouse(action="drag", from_ref="dom:123", to_ref="dom:456")`

## [COMPLEX_FLOW]
1) `page(detail="map")` to capture the [ACTION_MAP] and stable `aff:` refs.
2) `run(...)` with short, deterministic [V3_INTERNAL_ACTIONS]:
   - [ASSERT] early to guard preconditions (cheap checks first).
   - [WHEN] to skip optional branches without extra [NOISE|LEGEND.md].
   - [REPEAT] to do bounded retries/scroll-until patterns without external loops.
   - [MACRO] to expand into bounded step sequences (not app adapters).
   - `act` to execute stable actions from the map.
   - Macro input follows [MACRO_SPEC].
3) Use returned [ARTIFACT|LEGEND.md] ids for drilldowns via the `artifact` tool.

Example (shape only, keep actions short):
```
page(detail="map")
run(actions=[
  {"assert": {"...": "..."}},
  {"when": {"...": "..."}},
  {"macro": {"name": "dismiss_overlays", "args": {}, "dry_run": true}},
  {"act": {"ref": "aff:..."}}
])
```
- Drag to coordinates: `mouse(action="drag", from_ref="dom:123", to_x=300, to_y=300)`
- Stable handle scroll: `scroll(ref="dom:123")`
- Element screenshot (stable handle): `screenshot(ref="dom:123")`
- Debug UI: `page(detail="diagnostics")` → `page(detail="resources")` / `page(detail="performance")`
- Full DOM (rare, use [ARTIFACT|LEGEND.md] drilldown): `browser(action="dom", store=true)` → `browser(action="artifact", artifact_action="get", id="...", offset=0, max_chars=4000)`

## One-call workflows (super leverage)
Use `run(...)` when you would otherwise do 3–15 tool calls.
It runs multiple actions and returns one compact report (optionally with a screenshot):
- Example: `run(actions=[{navigate:{url:"..."}},{click:{text:"Sign in"}},{type:{selector:"#email", text:"..."}},{type:{key:"Enter"}}])`
- Stable UI actions: `page(detail="map")` (or `page(detail="locators")`) → `run(actions=[{act:{ref:"aff:..."}}])`
- Even fewer calls: `run(actions=[{navigate:{url:"..."}},{act:{label:"Save", kind:"button"}}], report="map")`
- Cross-page memory in one call: `run(actions=[...], report="graph")`
- Runbook recorder: `run(..., record_memory_key="runbook_login")` to store a reusable step list.
- Runbook execution: `runbook(action="run", key="runbook_login", params={...})` (see `docs/RUNBOOKS.md`).
- Low-noise observability: [TOOL_COUNTS] tells you how “chatty” a run was.
- Full quickref: [RUN_GUIDE].
- Safe agent memory KV:
  - Set: `browser(action="memory", memory_action="set", key="token", value="...")`
  - Persist (non-sensitive): `browser(action="memory", memory_action="save")`
  - Load (after restart): `browser(action="memory", memory_action="load")`
  - Use without revealing: `run(actions=[{type:{selector:"#pwd", text:"{{mem:token}}"}}], report="map")`
- Exporting state (no output dumps): `run(actions=[{"tool":"page","args":{"detail":"triage"},"export":{"cursor":"cursor","url":"triage.url"}}], report="none")`
- Debug-first: `run(..., actions_output="errors", screenshot_on_error=true)`
Robustness defaults (cognitive-cheap):
- `auto_dialog="auto"` (default): strict→off, permissive→dismiss blocking JS dialogs when safe.
- `auto_recover=true` (default): if CDP bricks (timeouts/unreachable), attempt recovery and stop with a clear re-run hint.
- Resume lever: if a run stops after recovery at step `i`, re-run with `start_at=i` to continue from that action index.
Legacy: `flow(...)` exists for v1/back-compat; in v2 prefer `run(...)`.

## Canvas apps (Miro/Figma): avoid chatty loops
Some sites are [CANVAS_APP|LEGEND.md]s: meaningful UI state is not DOM-driven.
For these, avoid hundreds of `click/mouse/type` steps and prefer [APP_MACRO|LEGEND.md]s:
- Universal (auto-detect + fallback): `app(op="diagram", params={...})` (default: paste-first in extension mode, then import fallback)
- Force paste-only (fastest, but may fail silently on some apps): `app(op="diagram", params={..., "strategy":"paste"})`
- Force import-only (most deterministic): `app(op="diagram", params={..., "strategy":"import"})`
- Import any asset (SVG/PNG/PDF/etc): `app(op="import", params={"file_paths":[...], "hints":{...}})`
- Paste text (extension mode): `app(op="paste", params={"text":"..."} )`
- Inside `run`: `run(actions=[{"tool":"app","args":{"op":"diagram","params":{...}}}])`
- Planning: `app(op="diagram", params={...}, dry_run=true)`

## Frontend debugging: fast loop
- Start: `page(detail="triage")` (fast counts + top issues + returns `cursor`)
- If visual ambiguity blocks progress: `page(detail="triage", with_screenshot=true)`
- Delta after an action: `page(detail="triage", since=<cursor>)` (new errors/fails/resources only)
- Delta resources after an action: `page(detail="resources", since=<cursor>, sort="duration")` (new/slow assets only)
- Drilldown: `page(detail="diagnostics")` (full snapshot: errors/network/hydration hints; returns `cursor`)
- Drilldown (full fidelity, off-context): `page(detail="diagnostics", store=true)` → `browser(action="artifact", artifact_action="get", ...)`
- Validate: `page(detail="resources", sort="duration")` (slow assets)
- Confirm: `page(detail="performance")` (CLS/LCP/long-tasks)
- Tier-0 network (HAR-lite, delta-friendly): `run(actions=[{net:{action:"harLite", since:<cursor>, limit:20, store:true}}])` (then use `run.next` artifact hint)
- If tools time out / hang symptoms: likely a blocking JS dialog. Either rely on `auto_dialog="auto"` or handle explicitly via `run(actions=[{dialog:{accept:true}}])` (or `accept:false`, `text:"..."`).
- If CDP bricks (e.g., "CDP response timed out"): `run` will attempt auto-recovery. If still stuck: `browser(action="recover", hard=true)`.
- CAPTCHA flows: `run(actions=[{captcha:{action:"analyze"}}])` → `run(actions=[{captcha:{action:"screenshot"}}])` → `run(actions=[{captcha:{action:"click_blocks", blocks:[...]}}])` → `run(actions=[{captcha:{action:"submit"}}])`
- Auth/debug (storage keys): `run(actions=[{storage:{action:"list", storage:"local"}}])`
- Auth/debug (read value safely): `run(actions=[{storage:{action:"get", storage:"local", key:"token"}}])` (redacted by default; use `reveal:true` only if explicitly approved)

## Cognitive budget rules
- Prefer summaries; avoid dumping full DOM unless you *must*.
- Use pagination (`offset`/`limit`) for lists.
- Take screenshots only when visual ambiguity blocks progress.
- If you must read large text (DOM/HTML), store it and drill down in slices: `browser(action="dom", store=true)` → `browser(action="artifact", artifact_action="get", ...)`.
- If you must preserve full fidelity (without [NOISE|LEGEND.md]), store the full payload and drill down: `page(..., store=true)` → `browser(action="artifact", artifact_action="get", ...)`.
