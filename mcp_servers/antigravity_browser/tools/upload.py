"""
File upload tools for browser automation.

Provides:
- upload_file: Upload files to file input elements
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, get_session


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
            # Get DOM node for the input
            session.send("DOM.enable", {})
            doc = session.send("DOM.getDocument", {})
            root_id = doc["root"]["nodeId"]

            if selector:
                node_result = session.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
                node_id = node_result.get("nodeId", 0)
            else:
                # Evaluate JS to find input, then query by generated ID
                result = session.eval_js("""
                    (() => {
                        const inputs = document.querySelectorAll('input[type="file"]');
                        if (inputs.length === 0) return null;
                        const inp = inputs[0];
                        if (!inp.id) inp.id = '__upload_target_' + Date.now();
                        return inp.id;
                    })()
                """)
                if not result:
                    raise SmartToolError(
                        tool="upload_file",
                        action="find_input",
                        reason="No file input found on page",
                        suggestion="Provide a CSS selector for the file input",
                    )
                node_result = session.send("DOM.querySelector", {"nodeId": root_id, "selector": f"#{result}"})
                node_id = node_result.get("nodeId", 0)

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
