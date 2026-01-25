"""Overlay helpers for page locators screenshots."""

from __future__ import annotations

import json
from typing import Any


def build_locators_overlay_js(
    overlay_id: str,
    boxes: list[dict[str, Any]],
    *,
    border: str = "rgba(0, 160, 255, 0.95)",
    fill: str = "rgba(0, 160, 255, 0.08)",
) -> tuple[str, str]:
    overlay_id_json = json.dumps(overlay_id)
    boxes_json = json.dumps(boxes)
    remove_js = (
        "(() => {"
        f"  const el = document.getElementById({overlay_id_json});"
        "  if (el) el.remove();"
        "  return true;"
        "})()"
    )
    inject_js = (
        "(() => {"
        f"  const id = {overlay_id_json};"
        "  const old = document.getElementById(id);"
        "  if (old) old.remove();"
        "  const root = document.createElement('div');"
        "  root.id = id;"
        "  root.style.position = 'fixed';"
        "  root.style.left = '0';"
        "  root.style.top = '0';"
        "  root.style.width = '100%';"
        "  root.style.height = '100%';"
        "  root.style.pointerEvents = 'none';"
        "  root.style.zIndex = '2147483647';"
        "  root.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';"
        f"  const boxes = {boxes_json};"
        "  for (const b of boxes) {"
        "    if (!b) continue;"
        "    const box = document.createElement('div');"
        "    box.style.position = 'fixed';"
        "    box.style.left = `${Math.max(0, b.x)}px`;"
        "    box.style.top = `${Math.max(0, b.y)}px`;"
        "    box.style.width = `${Math.max(0, b.width)}px`;"
        "    box.style.height = `${Math.max(0, b.height)}px`;"
        f"    box.style.border = '2px solid {border}';"
        f"    box.style.background = '{fill}';"
        "    box.style.boxSizing = 'border-box';"
        "    const badge = document.createElement('div');"
        "    badge.textContent = String(b.n);"
        "    badge.style.position = 'absolute';"
        "    badge.style.left = '-2px';"
        "    badge.style.top = '-18px';"
        "    badge.style.padding = '1px 6px';"
        "    badge.style.fontSize = '12px';"
        "    badge.style.lineHeight = '14px';"
        "    badge.style.borderRadius = '10px';"
        "    badge.style.color = 'white';"
        f"    badge.style.background = '{border}';"
        "    box.appendChild(badge);"
        "    root.appendChild(box);"
        "  }"
        "  document.documentElement.appendChild(root);"
        "  return { ok: true, count: boxes.length };"
        "})()"
    )
    return remove_js, inject_js
