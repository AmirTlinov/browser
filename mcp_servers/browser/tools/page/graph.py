"""Navigation graph for the current tab (visited pages + discovered link edges).

This is a *memory* feature:
- It persists across tool calls within the same MCP server process.
- It is best-effort and bounded (pruned in SessionManager).
- URLs are redacted (query/fragment dropped) to avoid leaking secrets.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError
from .info import get_page_info


def get_page_graph(
    config: BrowserConfig,
    *,
    limit: int = 30,
) -> dict[str, Any]:
    """Return a bounded navigation graph view for the current session tab."""

    limit = max(0, min(int(limit), 60))
    tab_id = session_manager.tab_id
    if not (isinstance(tab_id, str) and tab_id):
        raise SmartToolError(
            tool="page",
            action="graph",
            reason="No active session tab",
            suggestion="Navigate to a page first, then retry",
        )

    # Fast path: return stored graph if present.
    graph = session_manager.get_nav_graph_view(tab_id, node_limit=max(10, limit), edge_limit=max(20, limit * 2))
    if isinstance(graph, dict):
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []

        node_url: dict[str, str] = {}
        for n in nodes:
            if not isinstance(n, dict):
                continue
            nid = n.get("id")
            url = n.get("url")
            if isinstance(nid, str) and nid and isinstance(url, str) and url:
                node_url[nid] = url

        def _jump_hint(url: str) -> str:
            return f'run(actions=[{{navigate:{{url:{json.dumps(url)}}}}}], report="map")'

        jump: list[dict[str, Any]] = []
        for n in nodes[:10]:
            if not isinstance(n, dict):
                continue
            url = n.get("url")
            if not (isinstance(url, str) and url):
                continue
            label = n.get("title") if isinstance(n.get("title"), str) and n.get("title") else url
            jump.append(
                {
                    **({"id": n.get("id")} if isinstance(n.get("id"), str) else {}),
                    "label": label,
                    "url": url,
                    "actionHint": _jump_hint(url),
                }
            )

        edges_out: list[dict[str, Any]] = []
        for e in edges:
            if not isinstance(e, dict):
                continue
            e2 = dict(e)
            frm = e.get("from")
            to = e.get("to")
            if isinstance(frm, str) and frm in node_url:
                e2["fromUrl"] = node_url[frm]
            if isinstance(to, str) and to in node_url:
                e2["toUrl"] = node_url[to]
                e2["actionHint"] = _jump_hint(node_url[to])
            edges_out.append(e2)

        return {
            "graph": {
                **({"summary": graph.get("summary")} if isinstance(graph.get("summary"), dict) else {}),
                **({"current": graph.get("current")} if isinstance(graph.get("current"), str) else {}),
                "nodes": nodes,
                "edges": edges_out,
                **({"jump": jump} if jump else {}),
                **({"updatedAt": graph.get("updatedAt")} if graph.get("updatedAt") is not None else {}),
                "note": "Graph is best-effort: nodes are visited pages; edges include observed transitions and discovered link affordances.",
                "next": [
                    "page(detail='map') for current page actions",
                    'run(actions=[{page:{detail:"map"}}]) to refresh actions + update graph',
                ],
            },
            "sessionTabId": tab_id,
        }

    # If graph is empty, seed it from current page info.
    info = get_page_info(config)
    page = info.get("pageInfo") if isinstance(info, dict) else None
    if isinstance(page, dict) and isinstance(page.get("url"), str) and page.get("url"):
        session_manager.note_nav_graph_observation(tab_id, url=str(page.get("url")), title=page.get("title"))
        graph2 = session_manager.get_nav_graph_view(tab_id, node_limit=max(10, limit), edge_limit=max(20, limit * 2))
        if isinstance(graph2, dict):
            nodes = graph2.get("nodes") if isinstance(graph2.get("nodes"), list) else []
            edges = graph2.get("edges") if isinstance(graph2.get("edges"), list) else []
            return {
                "graph": {
                    **({"summary": graph2.get("summary")} if isinstance(graph2.get("summary"), dict) else {}),
                    **({"current": graph2.get("current")} if isinstance(graph2.get("current"), str) else {}),
                    "nodes": nodes,
                    "edges": [dict(e) for e in edges if isinstance(e, dict)],
                    **({"updatedAt": graph2.get("updatedAt")} if graph2.get("updatedAt") is not None else {}),
                    "note": "Graph seeded from current page info.",
                },
                "sessionTabId": tab_id,
                "target": info.get("target") if isinstance(info, dict) else None,
            }

    raise SmartToolError(
        tool="page",
        action="graph",
        reason="Navigation graph not available",
        suggestion="Navigate to a page first, then retry",
    )
