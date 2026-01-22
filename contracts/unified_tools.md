[LEGEND]

[CONTENT]
# MCP Tool Contract (Unified)

- protocolVersion: `2025-06-18`
- server: `browser` v`0.1.0`
- tools: `25`

## Tools

| name | description |
|---|---|
| `page` | Analyze current page structure and content. |
| `run` | Run an AI-native scenario using OAVR: Observe → Act → Verify → Report. |
| `flow` | DEPRECATED: use `run(...)` instead. |
| `app` | High-level app macros/adapters for complex web apps (Miro/Figma/etc.). |
| `navigate` | Navigate to URL or perform navigation action. |
| `click` | Universal click tool - by text, selector, or coordinates. |
| `type` | Type text into element or press keys. |
| `scroll` | Scroll the page in any direction or to specific element. |
| `form` | Work with forms: fill fields, select options, submit. |
| `screenshot` | Take a screenshot of the current page. |
| `tabs` | Manage browser tabs: list, switch, open, close. |
| `cookies` | Manage browser cookies: get, set, delete. |
| `captcha` | Detect and interact with CAPTCHAs. |
| `mouse` | Low-level mouse operations: move, hover, drag. |
| `resize` | Resize browser viewport or window. |
| `js` | Execute JavaScript in browser context. |
| `http` | Make HTTP request (not through browser). |
| `fetch` | Make fetch request from browser context (with cookies/session). |
| `upload` | Upload file to file input. |
| `download` | Wait for a download to complete and optionally store it as an artifact. |
| `dialog` | Handle JavaScript alert/confirm/prompt dialogs. |
| `totp` | Generate TOTP code for 2FA. |
| `wait` | Wait for condition. |
| `browser` | Browser control: lifecycle + policy + DOM. |
| `artifact` | Artifact store for high-fidelity payloads (keeps context window small). |

## Notes

- `tools/list` is the source of truth for the tool list and input schemas.
- Tool outputs are returned as MCP `content[]` items (`text` or `image`).
- On tool failure, the server sets `isError=true` and returns AI-first context-format text in `content[0].text`.
