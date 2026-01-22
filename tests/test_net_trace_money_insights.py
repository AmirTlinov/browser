import math


def test_extract_money_insights_detects_payment_vs_cart_mismatch() -> None:
    from mcp_servers.browser.net_trace import _extract_money_insights

    full_items = [
        {
            "url": "https://r.directpayment.nexway.com/rest/v1/checkout/session",
            "method": "PUT",
            "requestPostData": (
                '{"sessionId":"abc","datas":{"options":{"amount":607410,"currency":"RUB"},"customer":{"email":"x@example.test"}}}'
            ),
        },
        {
            "url": "https://api.r.nexway.store/carts/public/xyz",
            "method": "GET",
            "responseBody": '{"products":[{"price":{"grossPrice":13498.0,"currency":"RUB"}}]}',
        },
    ]

    money = _extract_money_insights(full_items=full_items, max_values=20, max_mismatches=5)
    assert isinstance(money, dict)
    assert isinstance(money.get("values"), list) and money["values"]

    values = money["values"]

    # Payment amount (minor units → major units).
    payment = [
        v
        for v in values
        if isinstance(v, dict) and v.get("currency") == "RUB" and v.get("unit") == "minor" and v.get("minor") == 607410
    ]
    assert payment, "Expected to extract payment amount in minor units"
    assert math.isclose(float(payment[0].get("major")), 6074.1, rel_tol=0.0, abs_tol=1e-6)

    # Cart price (major units).
    cart = [
        v
        for v in values
        if isinstance(v, dict)
        and v.get("currency") == "RUB"
        and v.get("unit") == "major"
        and math.isclose(float(v.get("major")), 13498.0, rel_tol=0.0, abs_tol=1e-6)
    ]
    assert cart, "Expected to extract cart grossPrice in major units"

    mismatches = money.get("mismatches")
    assert isinstance(mismatches, list) and mismatches, "Expected mismatch detection to trigger"
    m0 = mismatches[0]
    assert m0.get("currency") == "RUB"
    assert float(m0.get("ratio") or 0.0) > 2.0


def test_extract_money_insights_none_when_no_json() -> None:
    from mcp_servers.browser.net_trace import _extract_money_insights

    full_items = [
        {"url": "https://example.test/a", "responseBody": "<html>nope</html>"},
        {"url": "https://example.test/b", "requestPostData": "x=1&y=2"},
    ]

    assert _extract_money_insights(full_items=full_items) is None
