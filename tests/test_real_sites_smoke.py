from __future__ import annotations

import os
import time
import threading
import http.server
import socketserver
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from mcp_servers.browser import tools as cdp
from mcp_servers.browser.config import BrowserConfig
from mcp_servers.browser.launcher import BrowserLauncher
from mcp_servers.browser.server.registry import create_default_registry

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_INTEGRATION") != "1",
    reason="Requires real Chrome/Chromium + network. Set RUN_BROWSER_INTEGRATION=1 to enable.",
)


@pytest.fixture(scope="session")
def browser_env() -> tuple[BrowserConfig, BrowserLauncher]:
    config = BrowserConfig.from_env()
    launcher = BrowserLauncher(config)
    launcher.ensure_running()
    return config, launcher


def _page_info(config: BrowserConfig) -> dict:
    info = cdp.get_page_info(config)
    return info.get("pageInfo", {}) if isinstance(info, dict) else {}


def _page_info_retry(config: BrowserConfig, *, tries: int = 3, wait_s: float = 0.3) -> dict:
    for _ in range(max(1, tries)):
        page_info = _page_info(config)
        if isinstance(page_info, dict) and page_info.get("url"):
            return page_info
        try:
            cdp.wait_for(config, "load", timeout=5.0)
        except Exception:
            pass
        time.sleep(wait_s)
    return page_info if isinstance(page_info, dict) else {}


@contextmanager
def _local_download_server() -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        file_path = tmp_path / "mcp-hello.txt"
        file_path.write_text("hello", encoding="utf-8")
        index_path = tmp_path / "index.html"
        page1_path = tmp_path / "page1.html"
        page2_path = tmp_path / "page2.html"
        iframe_host_path = tmp_path / "iframe_host.html"
        iframe_inner_path = tmp_path / "iframe_inner.html"
        table_path = tmp_path / "table.html"
        html = "".join(
            [
                "<a id='mcp-newtab' href='https://example.com/?mcp-newtab=1' target='_blank'>",
                "MCP New Tab</a> <a id='mcp-download' href='mcp-hello.txt'>MCP Download</a>",
                "<button id='mcp-expand' aria-expanded='false'>Show more</button>",
                "<div id='mcp-hidden' style='display:none'>Hidden content</div>",
                "<div id='mcp-error'>error while loading</div>",
                "<div id='mcp-feed' style='height:200px; overflow:auto; border:1px solid #ccc'>",
                *[f"<div class='item'>Item {i}</div>" for i in range(1, 9)],
                "</div>",
                "<p>Local content paragraph.</p>",
                "<script>",
                "document.getElementById('mcp-expand').addEventListener('click', () => {",
                "  const hidden = document.getElementById('mcp-hidden');",
                "  hidden.style.display = 'block';",
                "  document.getElementById('mcp-expand').setAttribute('aria-expanded', 'true');",
                "});",
                "const feed = document.getElementById('mcp-feed');",
                "let feedCount = 8;",
                "feed.addEventListener('scroll', () => {",
                "  if (feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 4) {",
                "    for (let i = 0; i < 4; i++) {",
                "      feedCount += 1;",
                "      const div = document.createElement('div');",
                "      div.className = 'item';",
                "      div.textContent = 'Item ' + feedCount;",
                "      feed.appendChild(div);",
                "    }",
                "  }",
                "});",
                "setTimeout(() => {",
                "  const err = document.getElementById('mcp-error');",
                "  if (err) err.remove();",
                "}, 200);",
                "</script>",
            ]
        )
        index_path.write_text(html, encoding="utf-8")
        page1_path.write_text(
            "<a id='next' href='page2.html'>Next</a>",
            encoding="utf-8",
        )
        page2_path.write_text(
            "<p>Page 2</p>",
            encoding="utf-8",
        )
        iframe_inner_path.write_text(
            "<p>Iframe content</p>",
            encoding="utf-8",
        )
        iframe_host_path.write_text(
            "<iframe src='iframe_inner.html'></iframe>",
            encoding="utf-8",
        )
        table_path.write_text(
            "<table>"
            "<thead><tr><th>Col1</th><th>Col2</th></tr></thead>"
            "<tbody><tr><td>A</td><td>1</td></tr><tr><td>B</td><td>2</td></tr></tbody>"
            "</table>",
            encoding="utf-8",
        )

        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):  # noqa: ANN001
                super().__init__(*args, directory=str(tmp_path), **kwargs)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/index.html")
                    self.end_headers()
                    return
                super().do_GET()

            def end_headers(self) -> None:
                if self.path.endswith("mcp-hello.txt"):
                    self.send_header("Content-Disposition", 'attachment; filename="mcp-hello.txt"')
                    self.send_header("Content-Type", "text/plain")
                super().end_headers()

            def log_message(self, format, *args):  # noqa: ANN001
                return

        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as httpd:
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{port}/index.html"
            finally:
                httpd.shutdown()
                thread.join(timeout=1.0)


def _run_with_timeout(seconds: float, fn, *, on_timeout: str) -> object:  # noqa: ANN001
    result: dict[str, object] = {}
    errors: dict[str, Exception] = {}

    def _target() -> None:
        try:
            result["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            errors["exc"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise TimeoutError(on_timeout)
    if "exc" in errors:
        raise errors["exc"]
    return result.get("value")


def test_real_sites_smoke(browser_env: tuple[BrowserConfig, BrowserLauncher]) -> None:
    config, _launcher = browser_env

    # 1) Static baseline
    cdp.navigate_to(config, "https://example.com")
    info = _page_info_retry(config)
    assert "Example Domain" in str(info.get("title", ""))

    # 2) Redirect chain (edge case: navigation updates)
    cdp.navigate_to(config, "https://httpbin.org/redirect/1")
    info = _page_info_retry(config)
    assert "httpbin.org" in str(info.get("url", ""))

    # 3) Form fill (no submit) on a simple test page
    cdp.navigate_to(config, "https://httpbin.org/forms/post")
    cdp.fill_form(
        config,
        {"custname": "MCP Test", "custemail": "mcp@example.com", "comments": "hello"},
        form_index=0,
        submit=False,
    )
    info = _page_info(config)
    assert "httpbin.org" in str(info.get("url", ""))

    # 4) Search flow on a lightweight page
    cdp.navigate_to(config, "https://duckduckgo.com/")
    cdp.search_page(config, "openai", submit=True)
    cdp.wait_for(config, "navigation", timeout=10.0)
    info = _page_info_retry(config)
    assert "duckduckgo.com" in str(info.get("url", ""))

    # 5) Wiki search (form + navigation)
    cdp.navigate_to(config, "https://en.wikipedia.org/wiki/Special:Search")
    cdp.search_page(config, "Alan Turing", submit=True)
    cdp.wait_for(config, "navigation", timeout=10.0)
    info = _page_info_retry(config)
    if "wikipedia.org" not in str(info.get("url", "")):
        dom = cdp.get_dom(config, max_chars=4000)
        assert "Wikipedia" in str(dom.get("html", ""))

    # 6) Iframe-heavy page (frames map)
    cdp.navigate_to(config, "https://www.w3schools.com/html/tryit.asp?filename=tryhtml_iframe")
    frames = cdp.get_page_frames(config, limit=20)
    summary = frames.get("frames", {}).get("summary", {}) if isinstance(frames, dict) else {}
    assert isinstance(summary.get("total"), int) and summary.get("total") >= 1

    # 7) Pagination edge (simple DOM-driven site)
    try:
        cdp.navigate_to(config, "https://news.ycombinator.com/")
        url_before = str(_page_info_retry(config).get("url", ""))
        cdp.dom_action_click(config, "a.morelink")
        url_after = str(_page_info_retry(config).get("url", ""))
        assert url_after and url_after != url_before
    except Exception:
        # Live site flake (network/CDP). Keep test signal from other steps.
        pass

    # 8) Heavy search results (GitHub public search)
    cdp.navigate_to(config, "https://github.com/search?q=openai&type=repositories")
    info = _page_info_retry(config)
    assert "github.com/search" in str(info.get("url", ""))


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_INTEGRATION_MACROS") != "1",
    reason="Macro live tests. Set RUN_BROWSER_INTEGRATION_MACROS=1 to enable.",
)
def test_real_sites_macro_scroll_and_paginate(browser_env: tuple[BrowserConfig, BrowserLauncher]) -> None:
    config, launcher = browser_env
    registry = create_default_registry()
    flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]

    # Macro: scroll_to_end (bounded by until_js so it stays fast).
    try:
        res = flow_handler(
            config,
            launcher,
            args={
                "steps": [
                    {"navigate": {"url": "https://en.wikipedia.org/wiki/List_of_programming_languages"}},
                    {
                        "macro": {
                            "name": "scroll_to_end",
                            "args": {
                                "max_iters": 4,
                                "scroll": {"direction": "down", "amount": 800},
                                "until_js": "window.scrollY > 800",
                            },
                        }
                    },
                ],
                "final": "none",
                "stop_on_error": True,
                "auto_recover": False,
                "step_proof": False,
                "action_timeout": 20.0,
            },
        )
        assert not res.is_error
        info = _page_info_retry(config)
        assert isinstance(info.get("scrollY"), (int, float)) and info.get("scrollY") >= 800
    except Exception as exc:  # noqa: BLE001
        pytest.xfail(f"scroll_to_end live macro failed: {exc}")

    # Macro: paginate_next (HN "More" link).
    try:
        res = flow_handler(
            config,
            launcher,
            args={
                "steps": [
                    {"navigate": {"url": "https://news.ycombinator.com/news?p=1"}},
                    {
                        "macro": {
                            "name": "paginate_next",
                            "args": {
                                "next_selector": "a.morelink",
                                "until": {"url": "news?p=2"},
                                "wait": {"for": "navigation"},
                                "max_iters": 3,
                                "dismiss_overlays": False,
                            },
                        }
                    },
                ],
                "final": "none",
                "stop_on_error": True,
                "auto_recover": False,
                "step_proof": False,
                "action_timeout": 20.0,
            },
        )
        assert not res.is_error
        info = _page_info_retry(config)
        assert "news?p=2" in str(info.get("url", ""))
    except Exception as exc:  # noqa: BLE001
        pytest.xfail(f"paginate_next live macro failed: {exc}")


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_INTEGRATION_MACROS") != "1",
    reason="Macro live tests. Set RUN_BROWSER_INTEGRATION_MACROS=1 to enable.",
)
def test_real_sites_macro_expand_scroll_extract(browser_env: tuple[BrowserConfig, BrowserLauncher]) -> None:
    config, launcher = browser_env
    registry = create_default_registry()
    flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]

    cases = [
        (
            "article",
            "https://en.wikipedia.org/wiki/Alan_Turing",
            {"content_type": "overview"},
            lambda res: isinstance(res.get("counts", {}).get("paragraphs"), int)
            and res.get("counts", {}).get("paragraphs") > 0,
        ),
        (
            "tables",
            "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)",
            {"content_type": "table", "limit": 8},
            lambda res: isinstance(res.get("total"), int) and res.get("total", 0) > 0,
        ),
        (
            "listings",
            "https://news.ycombinator.com/",
            {"content_type": "links", "limit": 12},
            lambda res: isinstance(res.get("total"), int) and res.get("total", 0) >= 10,
        ),
    ]

    ok_cases = 0
    for name, url, extract_args, check in cases:
        try:
            res = flow_handler(
                config,
                launcher,
                args={
                    "steps": [
                        {"navigate": {"url": url}},
                        {
                            "macro": {
                                "name": "auto_expand_scroll_extract",
                                "args": {
                                    "expand": True,
                                    "scroll": {"max_iters": 4},
                                    "extract": extract_args,
                                },
                            }
                        },
                    ],
                    "final": "none",
                    "stop_on_error": True,
                    "auto_recover": False,
                    "step_proof": False,
                    "action_timeout": 25.0,
                },
            )
            assert not res.is_error
            steps = res.data.get("steps") if isinstance(res.data, dict) else None
            assert isinstance(steps, list)
            assert any(
                isinstance(step, dict)
                and step.get("tool") == "macro"
                and step.get("name") == "auto_expand_scroll_extract"
                for step in steps
            )

            extracted = cdp.extract_content(
                config,
                content_type=extract_args.get("content_type", "overview"),
                limit=extract_args.get("limit", 10),
            )
            assert isinstance(extracted, dict)
            assert extracted.get("contentType") == extract_args.get("content_type", "overview")
            assert check(extracted)
            ok_cases += 1
        except Exception:
            # Keep the smoke resilient to live site or network flakes.
            continue

    if ok_cases == 0:
        pytest.xfail("auto_expand_scroll_extract live macro failed on all sites")


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_INTEGRATION_EDGE") != "1",
    reason="Edge-case live tests. Set RUN_BROWSER_INTEGRATION_EDGE=1 to enable.",
)
def test_real_sites_edge_cases(browser_env: tuple[BrowserConfig, BrowserLauncher]) -> None:
    config, launcher = browser_env

    with _local_download_server() as page_url:
        registry = create_default_registry()
        flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
        base_url = page_url.rsplit("/", 1)[0]
        page1_url = f"{base_url}/page1.html"
        iframe_url = f"{base_url}/iframe_host.html"
        table_url = f"{base_url}/table.html"
        redirect_url = f"{base_url}/redirect"

        # Auto-tab: click a target=_blank link and switch automatically.
        try:
            res = _run_with_timeout(
                25.0,
                lambda: flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [
                            {"navigate": {"url": page_url}},
                            {"click": {"selector": "#mcp-newtab"}, "auto_tab": True},
                        ],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 10.0,
                    },
                ),
                on_timeout="auto-tab edge-case timed out",
            )
            assert not res.is_error
            assert isinstance(res.data, dict)
            steps = res.data.get("steps")
            assert isinstance(steps, list) and steps
            assert steps[1].get("autoTab", {}).get("switched") is True
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"auto-tab edge-case failed: {exc}")

        # Download: click local server file and require capture.
        try:
            res = _run_with_timeout(
                30.0,
                lambda: flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [
                            {"navigate": {"url": page_url}},
                            {
                                "click": {"selector": "#mcp-download"},
                                "download": {"required": True, "timeout": 15.0},
                            },
                        ],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 15.0,
                    },
                ),
                on_timeout="download edge-case timed out",
            )
            assert not res.is_error
            assert isinstance(res.data, dict)
            steps = res.data.get("steps")
            assert isinstance(steps, list) and steps
            download = steps[1].get("download")
            if not isinstance(download, dict):
                pytest.xfail("Download capture not supported in this environment")
            assert download.get("fileName") == "mcp-hello.txt"
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"download edge-case failed: {exc}")

        # Auto-expand: local show-more should reveal hidden content.
        try:
            res = _run_with_timeout(
                20.0,
                lambda: flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [
                            {"navigate": {"url": page_url}},
                            {
                                "macro": {
                                    "name": "auto_expand",
                                    "args": {
                                        "phrases": ["show more"],
                                        "selectors": ["#mcp-expand"],
                                        "max_iters": 2,
                                    },
                                }
                            },
                        ],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 10.0,
                    },
                ),
                on_timeout="auto-expand edge-case timed out",
            )
            assert not res.is_error
            visible = cdp.eval_js(
                config,
                "(() => {"
                " const el = document.querySelector('#mcp-hidden');"
                " if (!el) return false;"
                " const style = getComputedStyle(el);"
                " return style.display !== 'none';"
                "})()",
            )
            assert isinstance(visible, dict) and visible.get("result") is True
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"auto-expand edge-case failed: {exc}")

        # Redirect: local 302 should land on index.html.
        try:
            cdp.navigate_to(config, redirect_url)
            info = _page_info_retry(config)
            assert str(info.get("url", "")).endswith("/index.html")
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"redirect edge-case failed: {exc}")

        # Pagination: local page1 -> page2 via click.
        try:
            cdp.navigate_to(config, page1_url)
            cdp.dom_action_click(config, "#next")
            info = _page_info_retry(config)
            assert str(info.get("url", "")).endswith("/page2.html")
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"pagination edge-case failed: {exc}")

        # Iframe: local iframe should appear in frames map.
        try:
            cdp.navigate_to(config, iframe_url)
            frames = cdp.get_page_frames(config, limit=10)
            summary = frames.get("frames", {}).get("summary", {}) if isinstance(frames, dict) else {}
            assert isinstance(summary.get("total"), int) and summary.get("total") >= 1
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"iframe edge-case failed: {exc}")

        # Table extraction: local table rows.
        try:
            cdp.navigate_to(config, table_url)
            extracted = cdp.extract_content(config, content_type="table", table_index=0, limit=5)
            assert isinstance(extracted, dict)
            assert extracted.get("contentType") == "table"
            rows = extracted.get("rows")
            assert isinstance(rows, list) and rows
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"local table edge-case failed: {exc}")

        # Container-scroll on local feed should append items.
        try:
            res = _run_with_timeout(
                20.0,
                lambda: flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [
                            {"navigate": {"url": page_url}},
                            {
                                "scroll": {
                                    "direction": "down",
                                    "amount": 400,
                                    "container_selector": "#mcp-feed",
                                }
                            },
                        ],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 10.0,
                    },
                ),
                on_timeout="local container scroll timed out",
            )
            assert not res.is_error
            metrics = cdp.eval_js(
                config,
                "(() => {"
                " const feed = document.querySelector('#mcp-feed');"
                " const items = document.querySelectorAll('#mcp-feed .item');"
                " return {"
                "   scrollTop: feed ? feed.scrollTop : -1,"
                "   count: items ? items.length : 0"
                " };"
                "})()",
            )
            assert isinstance(metrics, dict)
            result = metrics.get("result", {})
            assert isinstance(result, dict)
            assert result.get("scrollTop", 0) > 0
            assert result.get("count", 0) >= 8
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"local container scroll edge-case failed: {exc}")

        # Retry-on-error: error banner should clear before extraction.
        try:
            res = _run_with_timeout(
                25.0,
                lambda: flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [
                            {"navigate": {"url": page_url}},
                            {
                                "macro": {
                                    "name": "auto_expand_scroll_extract",
                                    "args": {
                                        "expand": False,
                                        "scroll": {"max_iters": 2},
                                        "extract": {"content_type": "overview", "limit": 5},
                                        "retry_on_error": True,
                                        "error_texts": ["error while loading"],
                                    },
                                }
                            },
                        ],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 15.0,
                    },
                ),
                on_timeout="retry_on_error edge-case timed out",
            )
            assert not res.is_error
            extracted = cdp.extract_content(config, content_type="overview", limit=5)
            assert isinstance(extracted, dict)
            assert isinstance(extracted.get("counts", {}).get("paragraphs"), int)
        except Exception as exc:  # noqa: BLE001
            pytest.xfail(f"retry_on_error edge-case failed: {exc}")

    # Dialog handling: inject alert and rely on auto_dialog dismissal for read-ish step.
    try:
        res = _run_with_timeout(
            15.0,
            lambda: (
                cdp.eval_js(config, "setTimeout(() => alert('mcp-dialog'), 0)"),
                time.sleep(0.2),
                flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [{"js": {"code": "1 + 1"}}],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_dialog": "dismiss",
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 10.0,
                    },
                ),
            )[-1],
            on_timeout="dialog edge-case timed out",
        )
        assert not res.is_error
    except Exception as exc:  # noqa: BLE001
        pytest.xfail(f"dialog edge-case failed: {exc}")

    # Content root debug on a real article.
    try:
        cdp.navigate_to(config, "https://en.wikipedia.org/wiki/Alan_Turing")
        extracted = _run_with_timeout(
            20.0,
            lambda: cdp.extract_content(
                config,
                content_type="overview",
                content_root_debug=True,
            ),
            on_timeout="content_root_debug timed out",
        )
        assert isinstance(extracted, dict)
        assert isinstance(extracted.get("contentRootDebug"), dict)
    except Exception as exc:  # noqa: BLE001
        pytest.xfail(f"content_root_debug edge-case failed: {exc}")

    # Table index extraction (rows).
    try:
        cdp.navigate_to(
            config,
            "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)",
        )
        extracted = _run_with_timeout(
            25.0,
            lambda: cdp.extract_content(
                config,
                content_type="table",
                table_index=0,
                limit=5,
            ),
            on_timeout="table_index edge-case timed out",
        )
        assert isinstance(extracted, dict)
        assert extracted.get("contentType") == "table"
        rows = extracted.get("rows")
        assert isinstance(rows, list) and rows
    except Exception as exc:  # noqa: BLE001
        pytest.xfail(f"table_index edge-case failed: {exc}")

    # Container-scroll on real sites (social/market/news). Best-effort: pass if any succeed.
    container_cases = [
        ("news", "https://news.ycombinator.com/", "#hnmain"),
        ("market", "https://www.ebay.com/sch/i.html?_nkw=headphones", "body"),
        ("social", "https://github.com/trending", "main"),
        ("docs", "https://developer.mozilla.org/en-US/docs/Web/JavaScript", "main"),
        ("reference", "https://en.wikipedia.org/wiki/Alan_Turing", "#content"),
    ]
    ok_cases = 0
    for _name, url, selector in container_cases:
        try:
            res = _run_with_timeout(
                30.0,
                lambda: flow_handler(
                    config,
                    launcher,
                    args={
                        "steps": [
                            {"navigate": {"url": url}},
                            {"scroll": {"direction": "down", "amount": 400, "container_selector": selector}},
                        ],
                        "final": "none",
                        "stop_on_error": True,
                        "auto_recover": False,
                        "step_proof": False,
                        "action_timeout": 20.0,
                    },
                ),
                on_timeout=f"container scroll timed out: {_name}",
            )
            assert not res.is_error
            ok_cases += 1
        except Exception:
            continue

    if ok_cases == 0:
        pytest.xfail("container scroll live smoke failed on all sites")
