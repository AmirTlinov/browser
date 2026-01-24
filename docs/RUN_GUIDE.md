 [LEGEND]
ONE_CALL_FLOW = A single `run(...)` call that completes the task without a prior `page(...)`.
TWO_CALL_FLOW = A two-call pattern: `page(detail="map")` → `run(...)`.
RUN_ARGS = A small, high-leverage subset of `run(...)` options for low [NOISE|LEGEND.md].
EXPORTS = The `export` field on a step that captures outputs for later steps within the same `run(...)`.
STEP_REUSE = Reusing a stored step list (runbook) via `runbook(...)` or `include_memory_steps`.
AUTO_TAB = Auto-switch to a newly opened tab after click-like actions.
AUTO_AFFORDANCES = Auto-refresh affordances when `act(ref/label)` looks stale.

 [CONTENT]
# run() minimal-call guide

Use this when you want the fewest MCP calls per scenario. Start here, then drill down to
`docs/AGENT_PLAYBOOK.md`, `docs/MACROS.md`, and `docs/RUNBOOKS.md`.

## Decision tree (fast)
- Canvas app? Use `app(...)` or `run(actions=[{"tool":"app",...}])`.
- Repeated workflow across sessions? Use [STEP_REUSE] (record/run runbooks).
- Single page, multi-step? Use [ONE_CALL_FLOW].
- Complex UI with stable affordances? Use [TWO_CALL_FLOW].
- Need retries or branching? Use internal `assert/when/repeat` inside `run(...)`.
- Need lazy-loaded content? Use `page(detail="content", auto_scroll=true)` first.
- Need collapsed content expanded? Use `page(detail="content", auto_expand=true)` or `run(actions=[{"macro":{"name":"auto_expand"}}])` before extraction.

## [ONE_CALL_FLOW] patterns
Basic form:
```
run(actions=[
  {navigate:{url:"https://example.com/login"}},
  {type:{selector:"#email", text:"user@example.com"}},
  {type:{selector:"#pwd", text:"{{mem:pwd}}"}},
  {type:{key:"Enter"}}
], report="map")
```

Branching + bounded retries (no external loops):
```
run(actions=[
  {"assert": {"url": "/login"}},
  {"when": {"if": {"text": "Remember me"}, "then": [{"click": {"text": "Remember me"}}]}},
  {"repeat": {"max_iters": 5, "until": {"selector": "#dashboard"}, "steps": [{"click": {"text": "Continue"}}]}}
], actions_output="errors")
```

App macro inside a run:
```
run(actions=[
  {"tool":"app", "args":{"op":"diagram", "params":{"title":"...", "nodes":[...], "edges":[...]}}}
])
```

## [TWO_CALL_FLOW] patterns
```
page(detail="map")
run(actions=[
  {"act": {"ref": "aff:..."}},
  {"assert": {"url": "/settings"}}
], report="map")
```

## [EXPORTS] + interpolation (same run call)
```
run(actions=[
  {"tool":"page", "args":{"detail":"triage"}, "export":{"cursor":"cursor","url":"triage.url"}},
  {"navigate": {"url": "{{url}}"}}
], report="none")
```

## [RUN_ARGS] quick set (low-noise defaults)
- `report="none"` (or `report="map"` when you need affordances)
- `actions_output="errors"` (only emit errors)
- `screenshot_on_error=true`
- `auto_dialog="auto"` (default)
- `auto_tab=true` when a click is expected to open a new tab ([AUTO_TAB])
- `auto_affordances=true` (default) to keep `act(ref/label)` fresh ([AUTO_AFFORDANCES])
- `start_at=<index>` to resume after a partial run
- `record_memory_key="runbook_login"` to capture a reusable runbook (see `docs/RUNBOOKS.md`)
- `record_mode="sanitized"` (default) or `"raw"` when you explicitly need literals
- `record_on_failure=true` to capture steps even if the run fails

## [STEP_REUSE] (runbooks inside minimal calls)
- Record once: `run(..., record_memory_key="runbook_login", report="none")`
- Run later: `runbook(action="run", key="runbook_login", params={...}, run_args={...})`
- Embed inside a larger run: `{"macro": {"name": "include_memory_steps", "args": {"memory_key": "runbook_login", "params": {...}}}}`

## Macro leverage
Prefer macros like `scroll_until_visible` and `retry_click` to avoid external loops.
For a catalog and usage, see `docs/MACROS.md`.
