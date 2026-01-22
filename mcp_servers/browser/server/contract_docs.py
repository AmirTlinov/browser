"""Render user-facing contract docs.

Single responsibility: deterministic rendering of the unified tool contract markdown.

Kept as a real module (not an ad-hoc script helper) so CI/tests can verify that
`contracts/unified_tools.md` is always in sync with the live `tools/list` output.
"""

from __future__ import annotations

from typing import Any


def render_unified_tools_markdown(snapshot: dict[str, Any]) -> str:
    tools = snapshot.get("tools") or []
    lines: list[str] = []
    lines.append("[LEGEND]")
    lines.append("")
    lines.append("[CONTENT]")
    lines.append("# MCP Tool Contract (Unified)")
    lines.append("")
    lines.append(f"- protocolVersion: `{snapshot.get('protocolVersion')}`")

    server_info = snapshot.get("serverInfo") or {}
    lines.append(f"- server: `{server_info.get('name')}` v`{server_info.get('version')}`")
    lines.append(f"- tools: `{len(tools)}`")
    lines.append("")

    lines.append("## Tools")
    lines.append("")
    lines.append("| name | description |")
    lines.append("|---|---|")
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name", ""))
        desc = str(tool.get("description", "")).strip().splitlines()[0] if tool.get("description") else ""
        desc = desc.replace("|", "\\|")
        lines.append(f"| `{name}` | {desc} |")

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `tools/list` is the source of truth for the tool list and input schemas.")
    lines.append("- Tool outputs are returned as MCP `content[]` items (`text` or `image`).")
    lines.append(
        "- On tool failure, the server sets `isError=true` and returns AI-first context-format text in `content[0].text`."
    )

    return "\n".join(lines) + "\n"
