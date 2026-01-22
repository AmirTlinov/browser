from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any


def _xml_escape(value: str) -> str:
    s = str(value)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


@dataclass(frozen=True)
class DiagramLayout:
    direction: str = "LR"  # LR | TB (future)
    margin: int = 60
    node_w: int = 360
    node_h: int = 86
    gap_x: int = 140
    gap_y: int = 70
    title_h: int = 60


def default_browser_mcp_architecture_spec() -> dict[str, Any]:
    """A good default demo spec that matches the Browser MCP architecture."""
    return {
        "title": "Browser MCP (extension-mode) — architecture",
        "nodes": [
            {"id": "agent", "label": "Codex CLI (AI agent)"},
            {
                "id": "mcp",
                "label": "Browser MCP server (Python)\n• tools: page/run/click/type/...\n• session + telemetry\n• bounded context",
            },
            {"id": "gw", "label": "ExtensionGateway (WS localhost)\nws://127.0.0.1:8765"},
            {"id": "ext", "label": "Browser Extension (MV3)\n• chrome.debugger\n• event allowlist\n• kill-switch"},
            {"id": "tab", "label": "User Chrome Tab (any site/app)\n(Miro/Figma/etc.)"},
        ],
        "edges": [
            {"from": "agent", "to": "mcp", "label": "MCP stdio JSON-RPC"},
            {"from": "mcp", "to": "gw", "label": "WS RPC"},
            {"from": "gw", "to": "ext", "label": "WS client"},
            {"from": "ext", "to": "tab", "label": "CDP via chrome.debugger"},
        ],
    }


def diagram_spec_to_svg(spec: dict[str, Any], *, layout: DiagramLayout | None = None) -> tuple[str, dict[str, Any]]:
    """Render a simple DAG-style diagram as SVG (import-friendly for Miro/Figma).

    Spec format:
    - title: str (optional)
    - nodes: [{id:str, label:str}]
    - edges: [{from:str, to:str, label:str?}]
    """
    if not isinstance(spec, dict):
        spec = default_browser_mcp_architecture_spec()
    title = str(spec.get("title") or "").strip()
    nodes_raw = spec.get("nodes")
    edges_raw = spec.get("edges")

    nodes = nodes_raw if isinstance(nodes_raw, list) else []
    edges = edges_raw if isinstance(edges_raw, list) else []
    if not nodes:
        spec = default_browser_mcp_architecture_spec()
        title = str(spec.get("title") or "").strip()
        nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
        edges = spec.get("edges") if isinstance(spec.get("edges"), list) else []

    layout = layout or DiagramLayout()

    # Normalize node map
    node_ids: list[str] = []
    labels: dict[str, str] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "").strip()
        if not nid or nid in labels:
            continue
        node_ids.append(nid)
        labels[nid] = str(n.get("label") or nid)

    # Build edges (directed)
    norm_edges: list[tuple[str, str, str]] = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = str(e.get("from") or "").strip()
        dst = str(e.get("to") or "").strip()
        if not src or not dst:
            continue
        if src not in labels or dst not in labels:
            continue
        lbl = str(e.get("label") or "").strip()
        norm_edges.append((src, dst, lbl))

    # Layering: longest-path style (works best for DAG, degrades for cycles).
    indeg: dict[str, int] = dict.fromkeys(node_ids, 0)
    out_edges: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for src, dst, _lbl in norm_edges:
        indeg[dst] = indeg.get(dst, 0) + 1
        out_edges.setdefault(src, []).append(dst)

    # Kahn-ish ordering to compute layers.
    queue = [nid for nid in node_ids if indeg.get(nid, 0) == 0]
    layer: dict[str, int] = dict.fromkeys(node_ids, 0)
    visited = 0
    while queue:
        cur = queue.pop(0)
        visited += 1
        cur_layer = layer.get(cur, 0)
        for nxt in out_edges.get(cur, []):
            layer[nxt] = max(layer.get(nxt, 0), cur_layer + 1)
            indeg[nxt] = max(0, indeg.get(nxt, 0) - 1)
            if indeg[nxt] == 0:
                queue.append(nxt)

    # Cycles: keep remaining nodes at layer 0..N in stable order.
    if visited < len(node_ids):
        for nid in node_ids:
            layer.setdefault(nid, 0)

    # Column order: stable by layer, then by original node order.
    max_layer = max(layer.values()) if layer else 0
    cols: list[list[str]] = [[] for _ in range(max_layer + 1)]
    for nid in node_ids:
        cols[min(max_layer, max(0, int(layer.get(nid, 0))))].append(nid)

    # Canvas size
    max_rows = max((len(c) for c in cols), default=1)
    width = layout.margin * 2 + (max_layer + 1) * layout.node_w + max(0, max_layer) * layout.gap_x
    height = layout.margin * 2 + layout.title_h + max_rows * layout.node_h + max(0, max_rows - 1) * layout.gap_y

    # Position nodes
    pos: dict[str, tuple[int, int]] = {}
    for col_i, col in enumerate(cols):
        for row_i, nid in enumerate(col):
            x = layout.margin + col_i * (layout.node_w + layout.gap_x)
            y = layout.margin + layout.title_h + row_i * (layout.node_h + layout.gap_y)
            pos[nid] = (x, y)

    # SVG helpers
    def node_box(nid: str) -> tuple[int, int, int, int]:
        x, y = pos[nid]
        return x, y, layout.node_w, layout.node_h

    def node_mid_right(nid: str) -> tuple[int, int]:
        x, y, w, h = node_box(nid)
        return x + w, y + h // 2

    def node_mid_left(nid: str) -> tuple[int, int]:
        x, y, _w, h = node_box(nid)
        return x, y + h // 2

    # Render
    title_svg = ""
    if title:
        title_svg = f"""
  <text x="{layout.margin}" y="{layout.margin + 34}" font-family="Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
        font-size="24" font-weight="700" fill="#0f172a">{_xml_escape(title)}</text>""".rstrip()

    # Node rendering: basic wrapping (by line breaks, plus naive chunking).
    def render_label(nid: str, *, x: int, y: int) -> str:
        raw = labels.get(nid, nid)
        parts = [p.strip() for p in str(raw).split("\n") if p.strip()]
        if not parts:
            parts = [nid]
        max_lines = 5
        parts = parts[:max_lines]
        line_h = 18
        start_y = y + 28
        lines = []
        for i, line in enumerate(parts):
            lines.append(
                f'<text x="{x + 18}" y="{start_y + i * line_h}" font-family="Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif" '
                f'font-size="14" font-weight="{600 if i == 0 else 500}" fill="#0f172a">{_xml_escape(line)}</text>'
            )
        return "\n    ".join(lines)

    nodes_svg = []
    for nid in node_ids:
        x, y, w, h = node_box(nid)
        nodes_svg.append(
            f"""
  <g id="node-{_xml_escape(nid)}">
    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" ry="14" fill="#ffffff" stroke="#1e293b" stroke-width="2"/>
    {render_label(nid, x=x, y=y)}
  </g>""".rstrip()
        )

    # Edge rendering: simple polyline with arrow.
    edges_svg = []
    for src, dst, lbl in norm_edges:
        if src not in pos or dst not in pos:
            continue
        x1, y1 = node_mid_right(src)
        x2, y2 = node_mid_left(dst)
        mid_x = int(ceil((x1 + x2) / 2))
        # Orthogonal-ish path: right → mid_x → vertical → left
        path = f"M {x1} {y1} L {mid_x} {y1} L {mid_x} {y2} L {x2} {y2}"
        edges_svg.append(
            f"""
  <path d="{path}" fill="none" stroke="#334155" stroke-width="2.2" marker-end="url(#arrow)"/>""".rstrip()
        )
        if lbl:
            edges_svg.append(
                f"""
  <text x="{mid_x + 8}" y="{min(y1, y2) + abs(y2 - y1) // 2 - 6}" font-family="Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
        font-size="12" font-weight="500" fill="#475569">{_xml_escape(lbl)}</text>""".rstrip()
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="9" refY="6" orient="auto">
      <path d="M 0 0 L 12 6 L 0 12 z" fill="#334155"/>
    </marker>
  </defs>
  <rect x="0" y="0" width="{width}" height="{height}" fill="#f8fafc"/>
{title_svg}
{"".join(edges_svg)}
{"".join(nodes_svg)}
</svg>
"""

    meta: dict[str, Any] = {
        "width": width,
        "height": height,
        "nodes": len(node_ids),
        "edges": len(norm_edges),
        "layout": {
            "direction": layout.direction,
            "node_w": layout.node_w,
            "node_h": layout.node_h,
            "gap_x": layout.gap_x,
            "gap_y": layout.gap_y,
            "margin": layout.margin,
        },
    }
    return svg, meta
