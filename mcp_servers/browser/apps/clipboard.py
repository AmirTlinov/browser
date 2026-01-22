from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from ..tools.base import SmartToolError


@dataclass(frozen=True)
class ClipboardItem:
    mime: str
    data: bytes


def svg_clipboard_items(svg: str) -> list[ClipboardItem]:
    """Return a conservative clipboard payload for SVG pasting.

    We intentionally provide only `image/svg+xml` to avoid accidentally pasting
    huge SVG markup into apps that treat clipboard as plain text.
    """

    s = str(svg or "")
    return [ClipboardItem(mime="image/svg+xml", data=s.encode("utf-8"))]


def _require_extension_gateway(config: BrowserConfig):
    if getattr(config, "mode", "launch") != "extension":
        raise SmartToolError(
            tool="clipboard",
            action="write",
            reason="Clipboard bridge is only available in extension mode",
            suggestion="Set MCP_BROWSER_MODE=extension and enable Agent control in the extension popup",
            details={"mode": getattr(config, "mode", "launch")},
        )

    gw = session_manager.get_extension_gateway()
    if gw is not None and not gw.is_connected():
        try:
            connect_timeout = float(os.environ.get("MCP_EXTENSION_CONNECT_TIMEOUT") or 2.0)
        except Exception:
            connect_timeout = 2.0
        connect_timeout = max(0.0, min(connect_timeout, 15.0))
        if connect_timeout > 0:
            gw.wait_for_connection(timeout=connect_timeout)

    if gw is None or not gw.is_connected():
        raise SmartToolError(
            tool="clipboard",
            action="write",
            reason="Extension is not connected",
            suggestion="Open the Browser MCP extension popup and enable Agent control; ensure the gateway is running",
        )
    return gw


def _encode_items(items: list[ClipboardItem], *, max_total_bytes: int = 8_000_000) -> list[dict[str, str]]:
    total = 0
    out: list[dict[str, str]] = []
    for it in items:
        mime = str(it.mime or "").strip()
        if not mime:
            continue
        data = bytes(it.data or b"")
        total += len(data)
        if total > max_total_bytes:
            raise SmartToolError(
                tool="clipboard",
                action="write",
                reason="Clipboard payload too large",
                suggestion="Use a smaller payload (e.g., PNG instead of huge SVG) or import via file chooser",
                details={"maxTotalBytes": max_total_bytes, "approxBytes": total},
            )
        out.append({"mime": mime, "dataBase64": base64.b64encode(data).decode("ascii")})
    return out


def clipboard_write_text(config: BrowserConfig, *, text: str, timeout_s: float = 6.0) -> dict[str, Any]:
    gw = _require_extension_gateway(config)
    res = gw.rpc_call("clipboard.writeText", {"text": str(text)}, timeout=float(timeout_s))
    return res if isinstance(res, dict) else {"ok": True}


def clipboard_write(config: BrowserConfig, *, items: list[ClipboardItem], timeout_s: float = 8.0) -> dict[str, Any]:
    gw = _require_extension_gateway(config)
    payload = {"items": _encode_items(items)}
    res = gw.rpc_call("clipboard.write", payload, timeout=float(timeout_s))
    return res if isinstance(res, dict) else {"ok": True}


def clipboard_write_svg(
    config: BrowserConfig,
    *,
    svg: str,
    include_png: bool = True,
    width: int | None = None,
    height: int | None = None,
    scale: float | None = None,
    timeout_s: float = 12.0,
) -> dict[str, Any]:
    """Write an SVG to the system clipboard (extension mode).

    The extension will additionally render `image/png` via an offscreen document when `include_png=true`.
    This dramatically improves paste compatibility across canvas apps.
    """

    gw = _require_extension_gateway(config)
    payload: dict[str, Any] = {"svg": str(svg or ""), "includePng": bool(include_png)}
    if width is not None:
        payload["width"] = int(width)
    if height is not None:
        payload["height"] = int(height)
    if scale is not None:
        payload["scale"] = float(scale)

    res = gw.rpc_call("clipboard.writeSvg", payload, timeout=float(timeout_s))
    return res if isinstance(res, dict) else {"ok": True}
