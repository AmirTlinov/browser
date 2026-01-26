from __future__ import annotations

from mcp_servers.browser.telemetry import Tier0Telemetry


def test_tier0_telemetry_ingest_console_error() -> None:
    t = Tier0Telemetry(max_events=50)
    t.ingest(
        {
            "method": "Runtime.consoleAPICalled",
            "params": {
                "type": "error",
                "args": [{"type": "string", "value": "boom"}],
            },
        }
    )
    snap = t.snapshot()
    assert snap["tier"] == "tier0"
    assert snap["summary"]["consoleErrors"] == 1
    assert snap["summary"]["jsErrors"] == 0
    assert isinstance(snap["console"], list) and snap["console"]


def test_tier0_telemetry_ingest_exception_thrown() -> None:
    t = Tier0Telemetry(max_events=50)
    t.ingest(
        {
            "method": "Runtime.exceptionThrown",
            "params": {
                "exceptionDetails": {
                    "text": "Uncaught",
                    "url": "https://example.com/app.js?token=secret#hash",
                    "lineNumber": 10,
                    "columnNumber": 2,
                }
            },
        }
    )
    snap = t.snapshot()
    assert snap["summary"]["jsErrors"] == 1
    assert isinstance(snap["errors"], list) and snap["errors"]
    # URL should be redacted (no query/hash)
    assert snap["errors"][0]["filename"] == "https://example.com/app.js"


def test_tier0_telemetry_ingest_network_failure_and_delta() -> None:
    t = Tier0Telemetry(max_events=50)

    # request start
    t.ingest(
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "r1",
                "request": {"url": "https://api.example.com/v1/user?token=secret", "method": "GET"},
                "type": "XHR",
            },
        }
    )
    # request failed
    t.ingest(
        {
            "method": "Network.loadingFailed",
            "params": {"requestId": "r1", "errorText": "net::ERR_FAILED"},
        }
    )

    snap_full = t.snapshot()
    assert snap_full["summary"]["failedRequests"] == 1
    assert isinstance(snap_full["network"], list) and snap_full["network"]
    assert snap_full["network"][0]["url"] == "https://api.example.com/v1/user"

    # delta: since cursor should yield 0 new items
    since = snap_full["cursor"]
    snap_delta = t.snapshot(since=since)
    assert snap_delta["since"] == since
    assert snap_delta["summary"]["failedRequests"] == 0
    assert snap_delta["network"] == []


def test_tier0_telemetry_dialog_open_closed_state() -> None:
    t = Tier0Telemetry(max_events=50)

    t.ingest(
        {
            "method": "Page.javascriptDialogOpening",
            "params": {"type": "alert", "message": "hi", "url": "https://example.com/#x"},
        }
    )
    snap_open = t.snapshot()
    assert snap_open["dialogOpen"] is True
    assert isinstance(snap_open.get("dialog"), dict)
    assert snap_open["dialog"]["type"] == "alert"
    assert snap_open["dialog"]["message"] == "hi"
    # URL should be redacted (no hash)
    assert snap_open["dialog"]["url"] == "https://example.com/"

    t.ingest({"method": "Page.javascriptDialogClosed", "params": {"result": True}})
    snap_closed = t.snapshot()
    assert snap_closed["dialogOpen"] is False


def test_tier0_telemetry_trace_buffer_completed_request() -> None:
    t = Tier0Telemetry(max_events=50)

    t.ingest(
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "r1",
                "request": {"url": "https://api.example.com/v1/user?q=1&token=secret", "method": "GET"},
                "type": "XHR",
            },
        }
    )
    t.ingest(
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "r1",
                "type": "XHR",
                "response": {
                    "url": "https://api.example.com/v1/user?q=1&token=secret",
                    "status": 200,
                    "mimeType": "application/json",
                    "headers": {"Content-Type": "application/json"},
                },
            },
        }
    )
    t.ingest({"method": "Network.loadingFinished", "params": {"requestId": "r1", "encodedDataLength": 123}})

    # Should be removed from inflight map and added to the completed trace buffer.
    assert "r1" not in t._req
    assert "r1" in t._req_done

    done = t._req_done["r1"]
    assert done.get("ok") is True
    assert done.get("url") == "https://api.example.com/v1/user"
    assert isinstance(done.get("urlFull"), str) and "token=secret" in done.get("urlFull")
    assert done.get("contentType") == "application/json"


def test_tier0_recent_downloads() -> None:
    t = Tier0Telemetry(max_events=50)

    t.ingest(
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "r2",
                "request": {"url": "https://files.example.com/report.csv?token=secret", "method": "GET"},
                "type": "Document",
            },
        }
    )
    t.ingest(
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "r2",
                "type": "Document",
                "response": {
                    "url": "https://files.example.com/report.csv?token=secret",
                    "status": 200,
                    "mimeType": "text/csv",
                    "headers": {"Content-Disposition": "attachment; filename=\"report.csv\""},
                },
            },
        }
    )
    t.ingest({"method": "Network.loadingFinished", "params": {"requestId": "r2", "encodedDataLength": 42}})

    recent = t.recent_downloads(max_age_ms=10_000, limit=1)
    assert isinstance(recent, list) and recent
    item = recent[0]
    assert "report.csv" in str(item.get("fileName") or "")
    assert "report.csv" in str(item.get("url") or "")
