from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest


def test_upload_auto_finds_file_input_deep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import session_manager
    from mcp_servers.browser.tools.upload import upload_file

    cfg = BrowserConfig.from_env()

    # Create a real temp file so upload_file validation passes.
    f = tmp_path / "hello.txt"
    f.write_text("hi", encoding="utf-8")

    class DummyTelemetry:
        dialog_open = False

    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: DummyTelemetry())

    calls: list[tuple[str, object]] = []

    class DummySession:
        tab_id = "tab1"

        def send(self, method: str, params=None):  # noqa: ANN001
            calls.append((method, params))
            if method in {"DOM.enable", "Runtime.enable"}:
                return {}
            if method == "Runtime.evaluate":
                # Return a live element reference via objectId.
                return {"result": {"type": "object", "objectId": "obj-1"}}
            if method == "DOM.requestNode":
                return {"nodeId": 123}
            if method == "Runtime.releaseObject":
                return {}
            if method == "DOM.setFileInputFiles":
                return {}
            raise AssertionError(f"Unexpected CDP call: {method}")

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, *args, **kwargs):  # noqa: ANN001, ARG001
        yield DummySession(), {"id": "tab1"}

    import mcp_servers.browser.tools.upload as upload_module

    monkeypatch.setattr(upload_module, "get_session", fake_get_session)

    out = upload_file(cfg, file_paths=[str(f)], selector=None)
    assert out.get("count") == 1
    assert out.get("target") == "tab1"

    # Ensure we set files on the resolved nodeId.
    set_calls = [c for c in calls if c[0] == "DOM.setFileInputFiles"]
    assert set_calls, "expected DOM.setFileInputFiles call"
    _method, params = set_calls[-1]
    assert isinstance(params, dict)
    assert params.get("nodeId") == 123
    assert isinstance(params.get("files"), list)
    assert params["files"][0] == str(f.absolute())
