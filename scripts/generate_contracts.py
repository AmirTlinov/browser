#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_servers.browser.server.contract import contract_snapshot  # noqa: E402
from mcp_servers.browser.server.contract_docs import render_unified_tools_markdown  # noqa: E402


def main() -> int:
    snapshot = contract_snapshot()

    out_dir = ROOT / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_json = out_dir / "unified_tools.json"
    out_md = out_dir / "unified_tools.md"

    out_json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_unified_tools_markdown(snapshot), encoding="utf-8")

    print(f"Wrote: {out_json}")
    print(f"Wrote: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
