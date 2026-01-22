from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest


def test_diagram_spec_to_svg_smoke() -> None:
    from mcp_servers.browser.apps.diagram import default_browser_mcp_architecture_spec, diagram_spec_to_svg

    svg, meta = diagram_spec_to_svg(default_browser_mcp_architecture_spec())
    assert svg.startswith("<svg")
    assert "marker" in svg
    assert meta["nodes"] >= 3
    assert meta["edges"] >= 1
    assert meta["width"] > 100
    assert meta["height"] > 100


def test_app_registry_selects_miro_by_url() -> None:
    from mcp_servers.browser.apps import app_registry

    sel = app_registry.select(app="auto", url="https://miro.com/app/board/abc123/")
    assert sel is not None
    assert sel.adapter.name == "miro"
    assert sel.matched_by == "url"


def test_app_registry_falls_back_to_universal_when_url_missing() -> None:
    from mcp_servers.browser.apps import app_registry

    sel = app_registry.select(app="auto", url="")
    assert sel is not None
    assert sel.adapter.name == "universal"


def test_file_chooser_accept_sets_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps.file_chooser import set_files_via_file_chooser
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    f = tmp_path / "hello.svg"
    f.write_text("<svg/>", encoding="utf-8")

    calls: list[tuple[str, object]] = []

    class DummyConn:
        def wait_for_event(self, name: str, timeout: float = 10.0):  # noqa: ANN001, ARG002
            assert name == "Page.fileChooserOpened"
            return {"backendNodeId": 55, "mode": "selectSingle", "frameId": "frame1"}

    class DummySession:
        tab_id = "tab1"
        conn = DummyConn()

        def send(self, method: str, params=None):  # noqa: ANN001
            calls.append((method, params))
            if method in {"Page.enable", "DOM.enable"}:
                return {}
            if method == "DOM.setFileInputFiles":
                return {}
            raise AssertionError(f"Unexpected CDP call: {method}")

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, *args, **kwargs):  # noqa: ANN001, ARG001
        yield DummySession(), {"id": "tab1"}

    import mcp_servers.browser.apps.file_chooser as fc

    monkeypatch.setattr(fc, "get_session", fake_get_session)

    out = set_files_via_file_chooser(cfg, file_paths=[str(f)], timeout=0.5)
    assert out.get("ok") is True
    assert out.get("target") == "tab1"

    set_calls = [c for c in calls if c[0] == "DOM.setFileInputFiles"]
    assert set_calls, "expected DOM.setFileInputFiles"
    _method, params = set_calls[-1]
    assert isinstance(params, dict)
    assert params.get("backendNodeId") == 55
    assert params.get("files") == [str(f)]


def test_miro_adapter_dry_run_writes_svg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps.miro import MiroAdapter
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    import mcp_servers.browser.apps.miro as miro_mod

    monkeypatch.setattr(miro_mod, "_repo_root", lambda: tmp_path)

    ad = MiroAdapter()
    out = ad.invoke(config=cfg, op="diagram", params={"title": "Hello"}, dry_run=True)
    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("strategy") == "auto"
    artifact = out.get("artifact")
    assert isinstance(artifact, dict)
    svg_path = Path(str(artifact.get("file")))
    assert svg_path.exists()
    assert svg_path.suffix == ".svg"


def test_miro_adapter_insert_svg_dry_run_writes_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps.miro import MiroAdapter
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    import mcp_servers.browser.apps.miro as miro_mod

    monkeypatch.setattr(miro_mod, "_repo_root", lambda: tmp_path)

    ad = MiroAdapter()
    out = ad.invoke(config=cfg, op="insert", params={"svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"}, dry_run=True)
    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("kind") == "svg"
    artifact = out.get("artifact")
    assert isinstance(artifact, dict)
    svg_path = Path(str(artifact.get("file")))
    assert svg_path.exists()
    assert svg_path.suffix == ".svg"
