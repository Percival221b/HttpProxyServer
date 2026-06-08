from __future__ import annotations

from proxy.header_modifier import HeaderModifier


def test_header_modifier_adds_profile_headers_and_removes_filtered_headers(tmp_path):
    rules_path = tmp_path / "header_rules.json"
    modifier = HeaderModifier(rules_path)
    modifier.set_active_profile("landlord")

    headers = {
        "host": "127.0.0.1:5000",
        "x-remove-me": "secret",
        "user-agent": "pytest",
    }

    rewritten = modifier.apply(headers)

    assert rewritten["x-proxy-demo"] == "HouseRent-Cache-Proxy"
    assert rewritten["x-demo-role"] == "landlord"
    assert rewritten["x-client-type"] == "landlord-dashboard"
    assert "x-remove-me" not in rewritten
    assert rewritten["user-agent"] == "pytest"


def test_header_modifier_can_be_disabled(tmp_path):
    rules_path = tmp_path / "header_rules.json"
    modifier = HeaderModifier(rules_path)
    rules = modifier.get_rules()
    rules["enabled"] = False
    modifier.save(rules)

    headers = {"x-remove-me": "kept"}

    assert modifier.apply(headers) == headers
