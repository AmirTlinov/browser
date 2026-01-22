from __future__ import annotations

from pathlib import Path

import pytest


def test_parse_import_hints_paths() -> None:
    from mcp_servers.browser.apps.import_flow import parse_import_hints

    hints = parse_import_hints(
        {
            "paths": [["A", "B", "C"], ["  ", "X"]],
            "openCandidates": ["Upload"],
            "chooseCandidates": ["My device"],
            "shortcuts": [{"key": "o", "ctrl": True}],
        }
    )
    assert hints.paths and list(hints.paths[0]) == ["A", "B", "C"]
    assert "Upload" in hints.open_candidates
    assert "My device" in hints.choose_candidates
    assert hints.shortcuts and hints.shortcuts[0].key == "o"


def test_import_flow_uses_shortcut_then_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps import import_flow
    from mcp_servers.browser.apps.import_flow import ImportHints, KeyChord, import_via_file_chooser
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.base import SmartToolError

    cfg = BrowserConfig.from_env()

    f = tmp_path / "a.svg"
    f.write_text("<svg/>", encoding="utf-8")

    calls: list[tuple[str, object]] = []

    def fake_intercept(_cfg: BrowserConfig, *, enabled: bool):  # noqa: ANN001
        calls.append(("intercept", enabled))
        return {"ok": True}

    def fake_press_key(_cfg: BrowserConfig, key: str, modifiers: int = 0):  # noqa: ANN001
        calls.append(("press_key", (key, modifiers)))
        return {"ok": True}

    # First chooser attempt fails (no event), second succeeds.
    attempts = {"n": 0}

    def fake_set_files(_cfg: BrowserConfig, *, file_paths: list[str], timeout: float = 10.0):  # noqa: ANN001
        attempts["n"] += 1
        calls.append(("set_files", (list(file_paths), timeout)))
        if attempts["n"] == 1:
            raise SmartToolError(tool="file_chooser", action="wait", reason="timeout", suggestion="retry")
        return {"ok": True, "files": file_paths}

    monkeypatch.setattr(import_flow, "enable_file_chooser_intercept", fake_intercept)
    monkeypatch.setattr(import_flow.tools, "press_key", fake_press_key)
    monkeypatch.setattr(import_flow, "set_files_via_file_chooser", fake_set_files)

    hints = ImportHints(shortcuts=(KeyChord(key="o", ctrl=True), KeyChord(key="o", meta=True)))
    out = import_via_file_chooser(cfg, file_paths=[str(f)], hints=hints, timeout_s=2.0)
    assert out.get("ok") is True
    assert out.get("strategy") == "shortcut"
    assert attempts["n"] == 2
    assert ("intercept", True) in calls
    assert ("intercept", False) in calls


def test_import_flow_uses_path_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp_servers.browser.apps import import_flow
    from mcp_servers.browser.apps.import_flow import ImportHints, import_via_file_chooser
    from mcp_servers.browser.config import BrowserConfig

    cfg = BrowserConfig.from_env()

    f = tmp_path / "b.svg"
    f.write_text("<svg/>", encoding="utf-8")

    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        import_flow,
        "enable_file_chooser_intercept",
        lambda _cfg, enabled=True: calls.append(("intercept", enabled)) or {"ok": True},
    )
    monkeypatch.setattr(
        import_flow, "_click_keyword", lambda _cfg, keyword="": calls.append(("click", keyword)) or True
    )
    monkeypatch.setattr(
        import_flow,
        "set_files_via_file_chooser",
        lambda _cfg, file_paths=None, timeout=10.0: {"ok": True, "files": file_paths},
    )  # noqa: E501

    hints = ImportHints(paths=(("Tools", "Upload", "My device"),))
    out = import_via_file_chooser(cfg, file_paths=[str(f)], hints=hints, timeout_s=2.0)
    assert out.get("ok") is True
    assert out.get("strategy") == "path"
    assert out.get("path") == ["Tools", "Upload", "My device"]
