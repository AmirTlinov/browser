"""
File upload tools for browser automation.

Provides:
- upload_file: Upload files to file input elements
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError, get_session
from .shadow_dom import DEEP_QUERY_JS


def upload_file(config: BrowserConfig, file_paths: list[str], selector: str | None = None) -> dict[str, Any]:
    """Upload file(s) to file input elements.

    Uses CDP for reliable file upload, works with hidden inputs too.

    Args:
        config: Browser configuration
        file_paths: Absolute paths to files to upload
        selector: CSS selector for file input (auto-detected if omitted)

    Returns:
        Dict with uploaded files info and target ID
    """
    # Safety-as-mode: strict policy forbids uploading local files (data exfil risk).
    try:
        if session_manager.get_policy().get("mode") == "strict":
            raise SmartToolError(
                tool="upload_file",
                action="validate",
                reason="Blocked by strict policy",
                suggestion='Switch to permissive via browser(action="policy", mode="permissive") if you have explicit user approval to upload local files',
            )
    except SmartToolError:
        raise
    except Exception:
        pass

    # Validate files exist
    validated_paths: list[str] = []
    for path in file_paths:
        p = Path(path)
        if not p.exists():
            raise SmartToolError(
                tool="upload_file",
                action="validate",
                reason=f"File not found: {path}",
                suggestion="Provide absolute paths to existing files",
            )
        validated_paths.append(str(p.absolute()))

    with get_session(config) as (session, target):
        try:
            # If a JS dialog is open, Runtime.evaluate can hang indefinitely.
            try:
                tab_id = session.tab_id
                t0 = session_manager.get_telemetry(tab_id) if isinstance(tab_id, str) and tab_id else None
                if t0 is not None and bool(getattr(t0, "dialog_open", False)):
                    raise SmartToolError(
                        tool="upload_file",
                        action="blocked",
                        reason="Blocking JS dialog is open",
                        suggestion="Handle the dialog first via dialog(accept=true|false, text='...') then retry upload",
                    )
            except SmartToolError:
                raise
            except Exception:
                pass

            # Get DOM node for the input
            enable_dom = getattr(session, "enable_dom", None)
            if callable(enable_dom):
                enable_dom()
            else:
                session.send("DOM.enable", {})
            # Ensure Runtime is available for deep element selection (shadow roots / iframes).
            with suppress(Exception):
                enable_runtime = getattr(session, "enable_runtime", None)
                if callable(enable_runtime):
                    enable_runtime()
                else:
                    session.send("Runtime.enable", {})

            if selector:
                doc = session.send("DOM.getDocument", {})
                root_id = doc["root"]["nodeId"]

                node_result = session.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
                node_id = node_result.get("nodeId", 0)
            else:
                # Deep-find a file input across *open* shadow DOM and same-origin iframes.
                expr = (
                    "(() => {"
                    f"{DEEP_QUERY_JS}\n"
                    "  const nodes = __mcpQueryAllDeep('input[type=\"file\"]', 50);\n"
                    "  if (!nodes || nodes.length === 0) return null;\n"
                    "  const visible = nodes.filter((n) => __mcpIsVisible(n));\n"
                    "  const pick = (visible && visible.length) ? visible[0] : nodes[0];\n"
                    "  return pick || null;\n"
                    "})()"
                )
                ev = session.send(
                    "Runtime.evaluate",
                    {
                        "expression": expr,
                        "returnByValue": False,
                        "awaitPromise": True,
                    },
                )

                obj = ev.get("result") if isinstance(ev, dict) else None
                if not isinstance(obj, dict):
                    raise SmartToolError(
                        tool="upload_file",
                        action="find_input",
                        reason="No file input found on page",
                        suggestion="Provide selector='...' for the file input or ensure the page has <input type=file>",
                    )

                # Null/undefined → no element
                if obj.get("subtype") == "null" or obj.get("type") == "undefined":
                    raise SmartToolError(
                        tool="upload_file",
                        action="find_input",
                        reason="No file input found on page",
                        suggestion="Provide selector='...' for the file input or ensure the page has <input type=file>",
                    )

                object_id = obj.get("objectId")
                if not isinstance(object_id, str) or not object_id:
                    raise SmartToolError(
                        tool="upload_file",
                        action="find_input",
                        reason="Failed to resolve file input element",
                        suggestion="Provide selector='...' for the file input",
                    )

                try:
                    node = session.send("DOM.requestNode", {"objectId": object_id})
                finally:
                    with suppress(Exception):
                        session.send("Runtime.releaseObject", {"objectId": object_id})

                node_id = node.get("nodeId", 0) if isinstance(node, dict) else 0

            if not node_id:
                raise SmartToolError(
                    tool="upload_file",
                    action="find_input",
                    reason="File input element not found",
                    suggestion="Check the selector or ensure file input exists",
                )

            # Set files via CDP
            session.send("DOM.setFileInputFiles", {"nodeId": node_id, "files": validated_paths})

            return {
                "uploaded": validated_paths,
                "count": len(validated_paths),
                **({"selector": selector} if isinstance(selector, str) and selector else {"selector": None}),
                "target": target["id"],
            }

        except SmartToolError:
            raise
        except Exception as e:
            raise SmartToolError(
                tool="upload_file",
                action="upload",
                reason=str(e),
                suggestion="Ensure file input is accessible and files are valid",
            ) from e
