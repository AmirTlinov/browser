[LEGEND]
MACRO = A run-internal expansion unit executed inside `run(actions=[...])`.
MACRO_SPEC = The macro input shape: `{macro:{name:"...", args:{...}, dry_run:true}}`.
MACRO_NAME = A stable macro id (string).
MACRO_ARGS = Macro-specific arguments (object).
MACRO_DRY_RUN = When true, return a plan/steps without executing them.
TRACE_KIND = `harLite` or `trace`.
MEM_PLACEHOLDER = Macro-time placeholder syntax: `{{mem:key}}` or `${mem:key}`.
PARAM_PLACEHOLDER = Macro-time placeholder syntax: `{{param:key}}` or `${param:key}`.
JS_COND = A JS expression evaluated in-page that must return a truthy value.
AUTO_EXPAND_SCROLL_EXTRACT = One-call expand → scroll → extract pipeline macro.
NAVIGATE_SPEC = Optional navigation args (`navigate:{...}` or `url:\"...\"`) before expansion.
EXPAND_SPEC = Expand args (`expand:true|false|{...}`) for the auto-expand pass.
SCROLL_SPEC = Scroll args (`scroll:true|false|{...}`) for the auto-scroll pass.
EXTRACT_SPEC = Extract args (`extract:{...}`) forwarded to `extract_content`.
RETRY_ON_ERROR = A bounded retry pass when error text is detected.
ERROR_TEXTS = A list of strings that signal partial failure (lazy load errors).
RETRY_STEPS = Steps to execute between retry checks (defaults: wait → scroll → wait).

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
- `scroll_to_end`: bounded auto-scroll until the page is at the end.
- `retry_click`: bounded retry clicking until a condition holds.
- `paginate_next`: bounded click-next loop (stops when Next is missing/disabled).
- `auto_expand`: bounded “Show more/Read more” expander before extraction.
- `auto_expand_scroll_extract`: one-call expand → scroll → extract pipeline (see below).

## [AUTO_EXPAND_SCROLL_EXTRACT]
Use this when you want a single `run(...)` call to expand collapsed content, scroll for lazy loads,
and then extract structured data.

### Arguments (high level)
- [NAVIGATE_SPEC]: `navigate:{...}` or `url:"..."` (optional).
- [EXPAND_SPEC]: `expand:true|false|{...}` (optional; defaults to `true`).
- [SCROLL_SPEC]: `scroll:true|false|{...}` (optional; defaults to `true`, with `stop_on_url_change=true`).
- [EXTRACT_SPEC]: `extract:{...}` (required object; defaults to `{}` if omitted).
- [RETRY_ON_ERROR]: `retry_on_error:true|false` (optional, default `true`).
- [ERROR_TEXTS]: `error_texts:["There was an error", "Try again"]` (optional).
- [RETRY_STEPS]: `retry_steps:[{wait:{...}}, {scroll:{...}}, ...]` (optional).

### Example (one call)
```
run(actions=[
  {macro:{name:"auto_expand_scroll_extract", args:{
    url:"https://example.com/articles",
    expand:true,
    scroll:{max_iters:6, stop_on_url_change:true},
    extract:{content_type:"main", limit:40},
    retry_on_error:true,
    error_texts:["There was an error", "Try again"]
  }}}
], report="map")
```
- `auto_expand_scroll_extract`: pipeline macro: auto-expand → auto-scroll → extract_content.
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

### scroll_to_end
Purpose: bounded auto-scroll until the page reaches the end (uses internal `repeat` + [JS_COND]).

Args:
- `max_iters` (optional, default: 8)
- `timeout_s` (optional, default: 0.4) — per-condition wait timeout (selector/text).
- `scroll` (optional object) — scroll args (default: `{direction:"down", amount:700}`).
- `until_js` (optional) — [JS_COND] override (default checks for page bottom).
- `settle_ms` (optional) — convert to a small backoff between iterations.
- Pass-through `repeat` tuning (optional): `max_time_s`, `backoff_s`, `backoff_factor`, `backoff_max_s`, `backoff_jitter`.

Example:
```
run(actions=[
  {"macro": {"name": "scroll_to_end", "args": {"max_iters": 12}}}
])
```

### retry_click
Purpose: bounded retry loop that keeps clicking until an `until` condition is met.

Args:
- `click` (required object) — click args (e.g., `{text:"Continue"}` or `{selector:"#btn"}`).
- `until` (required object) — condition (`{url/title/selector/text/js}`).
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

### paginate_next
Purpose: bounded click-next loop that stops when the Next control is missing/disabled (uses [JS_COND]).

Args:
- `next_selector` (required) — CSS selector for the Next control.
- `click` (optional object) — click args; defaults to `{selector: next_selector}`.
- `until` (optional object) — condition (`{url/title/selector/text/js}`); defaults to Next missing/disabled.
- `wait` (optional object) — wait args after each click (e.g., `{for:"networkidle"}`).
- `max_iters` (optional, default: 10)
- `timeout_s` (optional, default: 0.8) — per-condition wait timeout for selector/text.
- `dismiss_overlays` (optional bool, default: true)
- `settle_ms` (optional) — convert to a small backoff between iterations.
- Pass-through `repeat` tuning (optional): `max_time_s`, `backoff_s`, `backoff_factor`, `backoff_max_s`, `backoff_jitter`.

Example:
```
run(actions=[
  {"macro": {"name": "paginate_next", "args": {"next_selector": "button.next", "max_iters": 8}}}
])
```

### auto_expand
Purpose: bounded “show more/read more” expander pass before extraction (uses [JS_COND]).

Args:
- `phrases` (optional list) — phrases to match (default: show/read/see more, expand, show all, load more).
- `selectors` (optional string or list) — CSS selectors to scan (default: `button, [role=button], summary, details, [aria-expanded], [aria-controls], [data-expand], [data-expanded], [data-showmore], [data-show-more], [data-toggle], [data-collapse], [data-collapsed], [data-more], [data-open]`).
- `include_links` (optional bool, default: false) — allow anchor tags (only `#`/`javascript:` or role=button).
- `click_limit` (optional, default: 6) — max clicks per iteration.
- `max_iters` (optional, default: 6)
- `timeout_s` (optional, default: 0.4) — per-condition wait timeout.
- `wait` (optional object) — wait args after each click batch (e.g., `{for:"networkidle"}`).
- `settle_ms` (optional) — convert to a small backoff between iterations.
- Pass-through `repeat` tuning (optional): `max_time_s`, `backoff_s`, `backoff_factor`, `backoff_max_s`, `backoff_jitter`.

Example:
```
run(actions=[
  {"macro": {"name": "auto_expand", "args": {"phrases": ["show more", "read more"]}}}
])
```

### auto_expand_scroll_extract
Purpose: pipeline macro that expands collapsed content, scrolls to load lazy sections, and then runs
`extract_content` (structured extraction).

Args:
- `expand` (optional boolean/object) — auto-expand config (`true`/`false` or args for `auto_expand`).
- `scroll` (optional boolean/object) — auto-scroll config (`true`/`false` or args for `scroll_to_end`).
- `extract` (optional object) — arguments for `extract_content` (e.g., `content_type`, `selector`, `limit`).

Example:
```
run(actions=[
  {"macro": {"name": "auto_expand_scroll_extract", "args": {
    "expand": true,
    "scroll": {"max_iters": 6},
    "extract": {"content_type": "main", "limit": 12}
  }}}
], report="map")
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
