from __future__ import annotations

from pathlib import Path

import pytest


def test_universal_adapter_dry_run_includes_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps.universal import UniversalAdapter
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    import mcp_servers.browser.apps.universal as uni_mod

    monkeypatch.setattr(uni_mod, "_repo_root", lambda: tmp_path)

    ad = UniversalAdapter()
    out = ad.invoke(config=cfg, op="diagram", params={"title": "Hello"}, dry_run=True)
    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("strategy") == "auto"


def test_universal_adapter_invalid_strategy_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps.universal import AppAdapterError, UniversalAdapter
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    import mcp_servers.browser.apps.universal as uni_mod

    monkeypatch.setattr(uni_mod, "_repo_root", lambda: tmp_path)

    ad = UniversalAdapter()
    with pytest.raises(AppAdapterError):
        ad.invoke(config=cfg, op="diagram", params={"title": "Hello", "strategy": "nope"}, dry_run=True)


def test_svg_clipboard_items_is_conservative() -> None:
    from mcp_servers.browser.apps.clipboard import svg_clipboard_items

    items = svg_clipboard_items("<svg/>")
    assert len(items) == 1
    assert items[0].mime == "image/svg+xml"
    assert items[0].data.startswith(b"<svg")


def test_universal_adapter_insert_svg_dry_run_writes_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps.universal import UniversalAdapter
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    import mcp_servers.browser.apps.universal as uni_mod

    monkeypatch.setattr(uni_mod, "_repo_root", lambda: tmp_path)

    ad = UniversalAdapter()
    out = ad.invoke(config=cfg, op="insert", params={"svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"}, dry_run=True)
    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("kind") == "svg"
    artifact = out.get("artifact")
    assert isinstance(artifact, dict)
    svg_path = Path(str(artifact.get("file")))
    assert svg_path.exists()
    assert svg_path.suffix == ".svg"
