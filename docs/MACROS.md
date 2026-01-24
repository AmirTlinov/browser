[LEGEND]
MACRO = A run-internal expansion unit executed inside `run(actions=[...])`.
MACRO_SPEC = The macro input shape: `{macro:{name:"...", args:{...}, dry_run:true}}`.
MACRO_NAME = A stable macro id (string).
MACRO_ARGS = Macro-specific arguments (object).
MACRO_DRY_RUN = When true, return a plan/steps without executing them.
TRACE_KIND = `harLite` or `trace`.
MEM_PLACEHOLDER = Macro-time placeholder syntax: `{{mem:key}}` or `${mem:key}`.
PARAM_PLACEHOLDER = Macro-time placeholder syntax: `{{param:key}}` or `${param:key}`.

 [CONTENT]
# Run macros

[MACRO]s are run-internal helpers that expand into regular steps. They are **not** app adapters.
For canvas-app automation, use `app(...)` (see `docs/APPS.md`).

## When to use macros
- Use [MACRO]s to keep a multi-step flow inside a single `run(...)` call (lower [NOISE|LEGEND.md], fewer tool calls).
- Prefer [MACRO]s + internal `assert/when/repeat` over external loops.
- For cross-session reuse, record/run a runbook (see `docs/RUNBOOKS.md`); for canvas apps, use `app(...)`.

## Macro selection quickref
- `trace_then_screenshot`: capture a Tier-0 trace + screenshot (debug/triage).
- `dismiss_overlays`: clear blocking dialogs before clicks.
- `login_basic`: fill a basic login form with `form(fill=..., submit=true)`.
- `scroll_until_visible`: bounded scroll-until (uses internal `repeat`).
- `retry_click`: bounded retry clicking until a condition holds.
- `goto_if_needed`: avoid a navigation if already on the target page.
- `assert_then`: guard + execute a bounded follow-up step list.
- `include_memory_steps`: pull a stored runbook into a larger `run(...)` call.

Tip: use [MACRO_DRY_RUN] to preview the expansion without executing it.

## Spec
- Use inside `run(actions=[...])`.
- [MACRO_SPEC] with [MACRO_NAME], [MACRO_ARGS], [MACRO_DRY_RUN].

Example (shape only):
```
run(actions=[
  {"macro": {"name": "trace_then_screenshot", "args": {"trace": "harLite"}, "dry_run": true}}
])
```

## Available macros

### trace_then_screenshot
Purpose: capture a Tier-0 net trace then take a screenshot.

Args:
- `trace`: [TRACE_KIND] (default: `harLite`).

Example:
```
run(actions=[
  {"macro": {"name": "trace_then_screenshot", "args": {"trace": "trace"}}}
])
```

### dismiss_overlays
Purpose: best-effort dismissal of blocking overlays/dialogs.

Args:
- none

Example:
```
run(actions=[
  {"macro": {"name": "dismiss_overlays"}}
])
```

### login_basic
Purpose: fill and submit a basic login form via `form(fill=..., submit=true)`.

Args:
- `username` (required)
- `password` (required; prefer `{{mem:...}}` placeholders)
- `username_key_candidates` (optional list of field keys)
- `password_key_candidates` (optional list of field keys)

Example:
```
run(actions=[
  {"macro": {"name": "login_basic", "args": {"username": "user@example.com", "password": "{{mem:pwd}}"}}}
])
```

### scroll_until_visible
Purpose: bounded scroll-until pattern using the internal `repeat` action (no external loops).

Args:
- `selector` (required unless `text` provided) — element selector to wait for.
- `text` (required unless `selector` provided) — text to wait for.
- `max_iters` (optional, default: 10)
- `timeout_s` (optional, default: 0.6) — per-condition wait timeout.
- `scroll` (optional object) — scroll args (default: `{direction:"down", amount:600}`).
- Pass-through `repeat` tuning (optional): `max_time_s`, `backoff_s`, `backoff_factor`, `backoff_max_s`.

Example:
```
run(actions=[
  {"macro": {"name": "scroll_until_visible", "args": {"selector": "#pricing", "max_iters": 12}}}
])
```

### retry_click
Purpose: bounded retry loop that keeps clicking until an `until` condition is met.

Args:
- `click` (required object) — click args (e.g., `{text:"Continue"}` or `{selector:"#btn"}`).
- `until` (required object) — condition (`{url/title/selector/text}`).
- `max_iters` (optional, default: 5)
- `timeout_s` (optional, default: 0.8) — per-condition wait timeout for selector/text.
- `dismiss_overlays` (optional bool, default: true)
- Pass-through `repeat` tuning (optional): `max_time_s`, `backoff_s`, `backoff_factor`, `backoff_max_s`.

Example:
```
run(actions=[
  {"macro": {"name": "retry_click", "args": {"click": {"text": "Continue"}, "until": {"url": "/done"}}}}
])
```

### goto_if_needed
Purpose: avoid unnecessary navigation calls by only navigating when the current URL does **not** match a substring.

Args:
- `url_contains` (required) — substring match against current URL.
- `url` (required) — navigation target.
- `wait` (optional) — `auto|navigation|none` (passed to `navigate`).

Example:
```
run(actions=[
  {"macro": {"name": "goto_if_needed", "args": {"url_contains": "example.com/dashboard", "url": "https://example.com/dashboard"}}}
])
```

### assert_then
Purpose: fail-closed guard + run a bounded set of follow-up steps.

Args:
- `assert` (required object) — condition: `{url/title/selector/text,...}` (same keys as internal `assert`).
- `then` (required array) — step list to execute after the assertion passes.

Example:
```
run(actions=[
  {"macro": {"name": "assert_then", "args": {"assert": {"url": "/checkout"}, "then": [{"click": {"text": "Pay"}}]}}}
])
```

### include_memory_steps
Purpose: include a reusable step list stored in Browser MCP agent memory (a “runbook”), with optional parameter substitution.

This is the fastest way to avoid re-sending large step arrays from the agent on every call.
Recorder option: `run(..., record_memory_key="runbook_login")`; execute via `runbook(action="run", ...)` (see `docs/RUNBOOKS.md`).

Args:
- `memory_key` (required) — the memory key that contains a JSON array of step objects.
- `params` (optional object) — values for [PARAM_PLACEHOLDER]s inside the stored steps.
- `allow_sensitive` (optional bool, default: false) — by default, the macro refuses to include step lists stored under sensitive keys **or** containing sensitive literals (prefer [MEM_PLACEHOLDER]/[PARAM_PLACEHOLDER]).

Example (store a reusable runbook):
```
browser(action="memory", memory_action="set", key="runbook_login", value=[
  {"navigate": {"url": "https://example.com/login"}},
  {"macro": {"name": "login_basic", "args": {"username": "{{param:username}}", "password": "{{mem:pwd}}"}}}
])
```

Example (use it with params):
```
run(actions=[
  {"macro": {"name": "include_memory_steps", "args": {"memory_key": "runbook_login", "params": {"username": "user@example.com"}}}}
])
```
