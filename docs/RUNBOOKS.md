[LEGEND]
RUNBOOK = A reusable sequence of actions stored in agent memory and executed later.
RUNBOOK_RECORDER = The `run(...)` recorder mode that writes steps to agent memory.
RUNBOOK_TOOL = The `runbook(...)` MCP tool that executes a stored runbook.
RECORD_MEMORY_KEY = The `record_memory_key` argument on `run(...)`.
RUNBOOK_RUN = The `runbook(action="run", ...)` call shape.
MEM_PLACEHOLDER = A placeholder that resolves from agent memory: `{{mem:key}}`.
PARAM_PLACEHOLDER = A placeholder that resolves from runbook params: `{{param:key}}`.
BOUNDED_REPEAT = A `repeat` action with explicit limits (`max_iters` / `max_time_s`).
EXTRACT_RUNBOOK = A one-call extraction runbook template using `auto_expand_scroll_extract`.

[CONTENT]
# Runbooks

A [RUNBOOK] is a reusable step list you record once and execute later with parameters.
Use the [RUNBOOK_RECORDER] to capture a sequence, then run it with the [RUNBOOK_TOOL].

## Record a runbook (recorder)
Example:
```
run(actions=[
  {"navigate": {"url": "https://example.com/login"}},
  {"macro": {"name": "login_basic", "args": {"username": "{{param:username}}", "password": "{{mem:pwd}}"}}}
], record_memory_key="runbook_login", report="none")
```
The recorder key is provided via [RECORD_MEMORY_KEY].

## Run a runbook (tool)
Example:
```
runbook(action="run", key="runbook_login", params={"username": "user@example.com"})
```
This call follows the [RUNBOOK_RUN] shape.

## Save a runbook (tool)
Use this when you already have a step list and don’t need to record it.
Example:
```
runbook(action="save", key="runbook_login", steps=[
  {"navigate": {"url": "https://example.com/login"}},
  {"macro": {"name": "login_basic", "args": {"username": "{{param:username}}", "password": "{{mem:pwd}}"}}}
])
```

## [EXTRACT_RUNBOOK] (one-call template)
Save a reusable extractor that navigates to a URL and runs the auto-expand → auto-scroll → extract pipeline.

Template:
```
runbook(action="save", key="runbook_extract_one_call", steps=[
  {"navigate": {"url": "{{param:url}}"}},
  {"macro": {"name": "auto_expand_scroll_extract", "args": {
    "expand": true,
    "scroll": {"max_iters": 6},
    "extract": {"content_type": "overview"}
  }}}
])
```

Run it:
```
runbook(action="run", key="runbook_extract_one_call", params={"url": "https://example.com/article"})
```

## Inspect or delete runbooks
Examples:
```
runbook(action="list", limit=20)
runbook(action="get", key="runbook_login")
runbook(action="delete", key="runbook_login")
```

## Run with `run_args` (noise control)
You can pass most `run(...)` options via `run_args` (report, actions_output, auto_dialog, etc.).
Example:
```
runbook(action="run", key="runbook_login", params={"username": "user@example.com"}, run_args={
  "report": "none",
  "actions_output": "errors",
  "auto_dialog": "auto"
})
```

## Recorder options (from `run(...)`)
- `record_mode`: `sanitized` (default) or `raw` (use only when you explicitly need literals).
- `record_on_failure`: when `true`, record even if the run fails (useful for debugging).

## Best practices
- Keep secrets in [MEM_PLACEHOLDER] values (set via `browser(action="memory", ...)`).
- Pass dynamic inputs as [PARAM_PLACEHOLDER] values.
- Prefer [BOUNDED_REPEAT] for retries and polling (avoid unbounded loops).
- If you need to embed a runbook inside a larger `run(...)`, use `macro: include_memory_steps` (see `docs/MACROS.md`).
