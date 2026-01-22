from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest


def test_drop_flow_sends_drag_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps import drop_flow
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    f = tmp_path / "asset.svg"
    f.write_text("<svg/>", encoding="utf-8")

    # Avoid strict-policy blocks in unit tests.
    monkeypatch.setattr(drop_flow.session_manager, "get_policy", lambda: {"mode": "permissive"})

    # Deterministic focus point.
    monkeypatch.setattr(drop_flow, "focus_canvas_best_effort", lambda _cfg: {"x": 111.0, "y": 222.0, "source": "test"})

    # Deterministic screenshot hashes (before/after).
    calls = {"n": 0}

    def fake_hash(_cfg: BrowserConfig, *, backend_dom_node_id: int | None = None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            return None, "ahash:" + ("0" * 64)
        return None, "ahash:" + ("f" * 64)

    monkeypatch.setattr(drop_flow, "_screenshot_hash", fake_hash)

    sent: list[tuple[str, dict]] = []

    class DummySession:
        def send(self, method: str, params=None):  # noqa: ANN001
            sent.append((method, params or {}))
            return {}

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, *args, **kwargs):  # noqa: ANN001, ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(drop_flow, "get_session", fake_get_session)

    out = drop_flow.drop_files_best_effort(cfg, file_paths=[str(f)], verify_screenshot=True, settle_ms=10, threshold=1)
    assert out.get("ok") is True
    assert out.get("strategy") == "drop"

    drag_calls = [c for c in sent if c[0] == "Input.dispatchDragEvent"]
    assert len(drag_calls) == 3
    assert [c[1].get("type") for c in drag_calls] == ["dragEnter", "dragOver", "drop"]
    for _method, params in drag_calls:
        assert params.get("x") == 111.0
        assert params.get("y") == 222.0
        data = params.get("data")
        assert isinstance(data, dict)
        assert data.get("files") == [str(f.absolute())]
        assert data.get("dragOperationsMask") == 1

    verify = out.get("verify")
    assert isinstance(verify, dict)
    assert verify.get("changed") is True
