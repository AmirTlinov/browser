[LEGEND]
DOC_FORMAT = The canonical doc shape: a `[LEGEND]` block then a `[CONTENT]` block.
LEGEND_BLOCK = The `[LEGEND]` block containing definitions.
CONTENT_BLOCK = The `[CONTENT]` block containing the document body.
TOKEN = A named meaning reused across docs.
GLOBAL_TOKEN = A token defined in `LEGEND.md`; available repo-wide.
LOCAL_TOKEN = A token defined in a specific doc; scoped to that doc.
TOKEN_REF = A reference in content like `[TOKEN]` (optionally `[TOKEN|LEGEND.md]`).
NO_SHADOWING = Rule: a doc must not redefine a global token locally.
GATE = A deterministic checker that fails closed on drift.
DOCTOR = A diagnostic checker for environment + repo foundation.
CONTRACT = A versioned interface spec with examples.
CHANGE_PROTOCOL = The sequence: contracts → implementation → tests → docs.
MCP = Model Context Protocol (stdio JSON-RPC transport).
TOOL = A callable unit exposed via MCP `tools/list`.
TOOL_RESULT = A tool execution output returned as MCP `content[]` items.
CTX_FORMAT = Context-format Markdown (`[LEGEND]` + `[CONTENT]`) used for AI-facing text output.
COGNITIVE_BUDGET = A hard cap on output size and noise; prefer summaries + drilldown.
DRILLDOWN = A follow-up call that asks for more detail (offset/limit/detail).
ARTIFACT = A stored payload pointer (id + metadata) enabling drilldown without dumping large text.
TRIAGE = Minimal high-signal snapshot of frontend issues (errors/network/vitals).
NOISE = Low-signal output that consumes context without improving decisions.
CANVAS_APP = A web app whose main UI is canvas/WebGL (not DOM-driven), e.g. Miro/Figma.
APP_MACRO = A high-level app-specific operation executed server-side to reduce chatty click/drag loops.
ADAPTER = A pluggable module that matches a URL and implements [APP_MACRO] operations.
FILE_CHOOSER_INTERCEPT = CDP technique: intercept native file dialogs to automate uploads/imports (Page.setInterceptFileChooserDialog + Page.fileChooserOpened + DOM.setFileInputFiles).
OFFSCREEN_DOC = A Chrome MV3 offscreen document used to run privileged browser APIs that service workers can’t (e.g., Clipboard API).
CLIPBOARD_BRIDGE = The extension RPC path that writes clipboard data via [OFFSCREEN_DOC] so the agent can paste into web apps.
PASTE_FLOW = A best-effort macro that focuses the app canvas/work area and dispatches paste shortcuts (Ctrl+V/Cmd+V).
DROP_FLOW = A best-effort macro that drops local files into a web app via CDP drag events (Input.dispatchDragEvent).

[CONTENT]
This file is the global vocabulary for the repo.

Use it when:
- A meaning repeats across multiple documents.
- You want agents to reuse the same mental model without re-parsing prose.

Avoid it when:
- The concept is unique to one document (keep it as a local token in that doc).
