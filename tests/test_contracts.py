from __future__ import annotations

import json
from pathlib import Path

from mcp_servers.browser.server.contract import contract_snapshot
from mcp_servers.browser.server.contract_docs import render_unified_tools_markdown


def test_unified_contract_json_is_in_sync() -> None:
    root = Path(__file__).resolve().parent.parent
    path = root / "contracts" / "unified_tools.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == contract_snapshot(), "Contract drift: run `python3 scripts/generate_contracts.py`"


def test_unified_contract_markdown_is_in_sync() -> None:
    root = Path(__file__).resolve().parent.parent
    path = root / "contracts" / "unified_tools.md"
    on_disk = path.read_text(encoding="utf-8")
    assert on_disk == render_unified_tools_markdown(contract_snapshot()), (
        "Doc drift: run `python3 scripts/generate_contracts.py`"
    )
