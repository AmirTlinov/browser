[LEGEND]
APP_TOOL = The `app(...)` tool: a high-level entrypoint for app adapters.
OP = An adapter operation name (e.g. `diagram`).
PARAMS = Operation parameters (adapter-specific), passed as `params={...}`.
DIAGRAM_SPEC = A minimal graph spec: `{title?, nodes:[{id,label}], edges:[{from,to,label?}]}`.
DRY_RUN = Mode where the adapter returns a plan without executing it.
IMPORT_HINTS = Heuristics payload passed as `params.hints` for universal import (keywords, shortcuts, paths).
STRATEGY = Diagram insertion mode: `"auto"` (paste-first + import fallback), `"paste"` (paste only), `"import"` (file chooser only).
PNG_SCALE = Scale factor used when rendering SVG → PNG for clipboard paste (default: `2.0`).

[CONTENT]
# App adapters (canvas apps)

Some sites are [CANVAS_APP|LEGEND.md]s: the meaningful UI state lives in canvas/WebGL, not the DOM.
For these sites, low-level automation (`click`/`mouse`/`type`) becomes slow and chatty.

Browser MCP solves this by supporting [ADAPTER|LEGEND.md]-driven [APP_MACRO|LEGEND.md]s via the [APP_TOOL].

## Tool: `app(...)`

Use `app(...)` when you want one call to perform a whole “user intent” (import a diagram, lay out nodes, etc.).

Inputs:
- `app`: adapter name (`"auto"` to detect from current URL)
- `op`: [OP]
- `params`: [PARAMS]
- `dry_run`: [DRY_RUN]

## Adapter: `miro`

### `op="diagram"`

Goal: insert a diagram into Miro in a single call by generating SVG and either:
- paste-first via [CLIPBOARD_BRIDGE|LEGEND.md] + [PASTE_FLOW|LEGEND.md] (extension mode, writes both `image/png` and `image/svg+xml`), then
- fallback to `drag&drop` file (CDP `Input.dispatchDragEvent`), then
- fallback to [FILE_CHOOSER_INTERCEPT|LEGEND.md] (deterministic, works even when there is no `<input type="file">` in the DOM).

Control this with `params.strategy` ([STRATEGY]).
Use `params.png_scale` ([PNG_SCALE]) to control the PNG resolution used for paste.

`params` accepts a [DIAGRAM_SPEC]. If omitted, the adapter uses a default “Browser MCP architecture” diagram.

Example (direct call):
```
app(app="miro", op="diagram", params={
  "title": "Browser MCP — architecture",
  "nodes": [{"id":"a","label":"A"}, {"id":"b","label":"B"}],
  "edges": [{"from":"a","to":"b","label":"RPC"}],
  "strategy": "auto",
  "png_scale": 2.0
})
```

Example (inside `run()`):
```
run(actions=[
  {"tool":"app","args":{"app":"miro","op":"diagram","params":{"title":"...", "nodes":[...], "edges":[...]}}}
])
```

Debugging (plan only):
```
app(app="miro", op="diagram", params={...}, dry_run=true)
```

### `op="import"`
Goal: import an arbitrary file into Miro with a fast path:
- try `drag&drop` file (CDP `Input.dispatchDragEvent`), then
- fallback to the universal [FILE_CHOOSER_INTERCEPT|LEGEND.md] flow.
```
app(app="miro", op="import", params={
  "file_paths": ["/abs/path/to/asset.svg"]
})
```

### `op="paste"`
Goal: paste a text payload into the current app via [CLIPBOARD_BRIDGE|LEGEND.md] + [PASTE_FLOW|LEGEND.md] (extension mode only).

```
app(app="miro", op="paste", params={
  "text": "Browser MCP — quick note",
  "prefer": "ctrl",
  "verify": false
})
```

### Notes (reliability)
- The adapter uses universal heuristics plus a small set of Miro‑specific keyword paths (still best-effort).
- Extension mode must forward `Page.fileChooserOpened` events for [FILE_CHOOSER_INTERCEPT|LEGEND.md] to work.

## Adapter: `universal` (works on any site, best-effort)

Use this when you want the macro to work on *any* canvas‑like app without per-site code.
This adapter is also the fallback when `app="auto"` can’t match a specific site.

### `op="import"`
```
app(op="import", params={
  "file_paths": ["/abs/path/to/asset.svg"],
  "hints": {
    "paths": [["Tools", "Upload", "My device"]],
    "openCandidates": ["upload", "import", "insert"],
    "chooseCandidates": ["my device", "browse"],
    "shortcuts": [{"key":"o","ctrl":true}]
  }
})
```

Notes:
- By default it tries: shortcuts → explicit `paths` → keyword clicks.
- Provide [IMPORT_HINTS] when the app uses unusual menu labels or nested flows.

### `op="diagram"`
Generates an SVG from [DIAGRAM_SPEC] and then inserts it using `strategy` ([STRATEGY]).
In extension mode, `"auto"` will try paste-first (fast, no menu hunting) and fall back to import.

### `op="paste"`
Writes clipboard text via [CLIPBOARD_BRIDGE|LEGEND.md] and pastes into the current site (best-effort).
This is useful for canvas apps where pasting text creates a text box/sticky.

```
app(op="paste", params={"text":"hello from Browser MCP"})
```
