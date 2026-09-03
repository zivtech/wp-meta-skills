"""Unit tests for the deterministic half of the parity check (design §2.5).

No MCP server anywhere — StepRecord values are hand-built to look like what
`tools/list` / `read_error_log` / `read_wp_config` etc. would actually
return, and only the normalization + comparison logic is under test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import tool_value_parity as parity  # noqa: E402


def test_normalize_site_root_both_shapes():
    h = "wp-config.php not found at: /srv/sites/acme/app/public/wp-config.php"
    l = "wp-config.php not found at: /Users/alex/Local Sites/acme/app/public/wp-config.php"
    assert parity.normalize(h) == parity.normalize(l)
    assert "<SITE>" in parity.normalize(h)


def test_normalize_run_dir_both_shapes():
    h = "socket at /srv/run/acme-site/mysql/mysqld.sock"
    l = "socket at /Users/alex/Library/Application Support/Local/run/acme-site/mysql/mysqld.sock"
    assert parity.normalize(h) == parity.normalize(l)


def test_normalize_binary_prefix():
    h = "using /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar"
    l = "using /Applications/Local.app/Contents/Resources/extraResources/bin/wp-cli/wp-cli.phar"
    assert parity.normalize(h) == parity.normalize(l)


def test_normalize_log_timestamp():
    text = "[03-Sep-2026 11:22:33 UTC] PHP Fatal error: ..."
    assert parity.normalize(text) == "[TS] PHP Fatal error: ..."


def test_normalize_size_fields_only_named_keys():
    text = '{"sizeKb": 512, "totalLines": 42, "otherNumber": 7}'
    normalized = parity.normalize(text)
    assert '"sizeKb": <N>' in normalized
    assert '"totalLines": <N>' in normalized
    assert '"otherNumber": 7' in normalized  # not a size/count field; untouched


def test_normalize_hostname():
    assert parity.normalize("Host: acme.local") == "Host: <HOST>"


def test_normalize_json_value_recurses_into_nested_structures():
    value = {"file": "/srv/sites/acme/wp-config.php", "constants": {"WP_HOME": "http://acme.local"}}
    normalized = parity.normalize_json_value(value)
    assert normalized == {"file": "<SITE>/wp-config.php", "constants": {"WP_HOME": "http://<HOST>"}}


def _record(step: str, tool: str, response, args=None) -> parity.StepRecord:
    return parity.StepRecord(step=step, tool=tool, args=args or {}, response=response)


def test_compare_records_equivalent_after_normalization():
    h = {"read_wp_config_before": _record(
        "read_wp_config_before", "read_wp_config",
        {"file": "/srv/sites/acme/wp-config.php", "tablePrefix": "wp_", "constants": {"WP_DEBUG": "false"}},
    )}
    l = {"read_wp_config_before": _record(
        "read_wp_config_before", "read_wp_config",
        {"file": "/Users/alex/Local Sites/acme/wp-config.php", "tablePrefix": "wp_", "constants": {"WP_DEBUG": "false"}},
    )}
    report = parity.compare_records(h, l, fork_commit="78c87ea")
    assert report.status == "equivalent"
    assert report.fork_commit == "78c87ea"


def test_compare_records_divergent_on_real_difference():
    h = {"wp_cli_plugin_list": _record("wp_cli_plugin_list", "wp_cli", [{"name": "acme-events", "status": "active"}])}
    l = {"wp_cli_plugin_list": _record("wp_cli_plugin_list", "wp_cli", [{"name": "acme-events", "status": "inactive"}])}
    report = parity.compare_records(h, l)
    assert report.status == "divergent"
    assert report.divergent_tools == ["wp_cli"]
    assert report.results[0].diff is not None


def test_compare_records_missing_step_on_one_side_is_divergent():
    h = {"tools_list": _record("tools_list", "tools/list", {"tools": list(range(13))})}
    l: dict[str, parity.StepRecord] = {}
    report = parity.compare_records(h, l)
    tools_list_result = next(r for r in report.results if r.step == "tools_list")
    assert tools_list_result.equal is False
    assert report.status == "divergent"


def test_to_dict_shape_matches_design_schema():
    h = {"tools_list": _record("tools_list", "tools/list", {"tools": list(range(13))})}
    report = parity.compare_records(h, h, fork_commit="78c87ea", local_version="9.0.0", stack_image_digest="sha256:abc", date="2026-09-03")
    payload = report.to_dict()
    assert payload["status"] == "equivalent"
    assert payload["fork_commit"] == "78c87ea"
    assert payload["results"][0]["step"] == "tools_list"
    assert set(payload["results"][0]) == {"step", "tool", "args", "lane_H", "lane_L", "equal", "diff"}


def test_assert_tools_list_count_pinned_to_thirteen():
    records = {"tools_list": _record("tools_list", "tools/list", {"tools": [f"tool_{i}" for i in range(13)]})}
    assert parity.assert_tools_list_count(records) is True

    records_wrong = {"tools_list": _record("tools_list", "tools/list", {"tools": [f"tool_{i}" for i in range(12)]})}
    assert parity.assert_tools_list_count(records_wrong) is False


def test_assert_tools_list_count_missing_step():
    assert parity.assert_tools_list_count({}) is False


def test_self_parity_report_uses_the_same_comparison_logic():
    a = {"get_site_info": _record("get_site_info", "get_site_info", {"phpVersion": "8.3"})}
    b = {"get_site_info": _record("get_site_info", "get_site_info", {"phpVersion": "8.3"})}
    report = parity.self_parity_report(a, b)
    assert report.status == "equivalent"

    c = {"get_site_info": _record("get_site_info", "get_site_info", {"phpVersion": "8.2"})}
    divergent_report = parity.self_parity_report(a, c)
    assert divergent_report.status == "divergent"


def test_missing_canonical_steps_detects_gaps():
    partial = {"tools_list": _record("tools_list", "tools/list", {"tools": []})}
    missing = parity.missing_canonical_steps(partial)
    assert "tools_list" not in missing
    assert "get_site_info" in missing
    assert len(missing) == len(parity.PARITY_STEPS) - 1


def test_missing_canonical_steps_empty_when_complete():
    full = {step: _record(step, "x", {}) for step in parity.PARITY_STEPS}
    assert parity.missing_canonical_steps(full) == []


def test_lane_l_fetcher_is_still_an_explicit_seam():
    """Lane L needs a real Local install (design §2.1: not present on this
    machine) — genuinely blocked, unlike Lane H (see the tests below, and
    this session's 2026-09-03 report: `fetch_lane_h_records` was proven for
    real against a live headless server and is no longer a seam)."""
    import pytest
    with pytest.raises(NotImplementedError, match="SEAM"):
        parity.fetch_lane_l_records("/tmp/port", "/tmp/token", "site")


def test_parity_calls_table_matches_canonical_step_order():
    """`_PARITY_CALLS` is what `fetch_lane_h_records` actually iterates;
    this pins it to the exact, order-sensitive design §2.5 step-3 sequence
    (redundant with the module-level `assert` next to the table, which
    would fail every test in this file if it ever drifted — this test names
    the invariant explicitly for anyone reading the test file alone)."""
    assert tuple(parity._PARITY_CALLS) == parity.PARITY_STEPS
    assert parity._PARITY_CALLS["wp_debug_toggle_on"] == ("wp_debug_toggle", {"enable": True})
    assert parity._PARITY_CALLS["wp_debug_toggle_off"] == ("wp_debug_toggle", {"enable": False})
    assert parity._PARITY_CALLS["edit_wp_config"] == ("edit_wp_config", {"name": "ACME_PARITY", "value": "'1'"})


class _FakeHttpResponse:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_mcp_jsonrpc_session_unwraps_plain_json_and_tracks_session_id(monkeypatch):
    """No real network: `urllib.request.urlopen` is replaced with a fake
    that returns a plain-JSON body (matching what this session's live
    headless server actually sent — see test below for the SSE-framed
    variant) and asserts the session-id header is captured and resent."""
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.headers.get("Mcp-session-id"))
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": [1, 2, 3]}}).encode("utf-8")
        return _FakeHttpResponse(body, {"mcp-session-id": "sess-123"})

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    session = parity._McpJsonRpcSession("http://127.0.0.1:1/sites/x/mcp", "tok")
    result = session.tools_list()
    assert result == {"tools": [1, 2, 3]}
    assert session.session_id == "sess-123"
    # First call carries no session header (none established yet); a second
    # call must carry the one captured from the first response.
    session.tools_list()
    assert calls == [None, "sess-123"]


def test_mcp_jsonrpc_session_unwraps_sse_framed_body(monkeypatch):
    def fake_urlopen(request, timeout=None):
        sse = 'event: message\ndata: {"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n\n'
        return _FakeHttpResponse(sse.encode("utf-8"), {})

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    session = parity._McpJsonRpcSession("http://127.0.0.1:1/sites/x/mcp", "tok")
    assert session.tools_list() == {"ok": True}


def test_mcp_jsonrpc_session_tools_call_unwraps_text_content_as_json(monkeypatch):
    def fake_urlopen(request, timeout=None):
        result = {"content": [{"type": "text", "text": '{"a": 1}'}]}
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode("utf-8")
        return _FakeHttpResponse(body, {})

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    session = parity._McpJsonRpcSession("http://127.0.0.1:1/sites/x/mcp", "tok")
    assert session.tools_call("get_site_info", {}) == {"a": 1}


def test_mcp_jsonrpc_session_tools_call_keeps_non_json_text_as_string(monkeypatch):
    def fake_urlopen(request, timeout=None):
        result = {"content": [{"type": "text", "text": "plain refusal text"}]}
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode("utf-8")
        return _FakeHttpResponse(body, {})

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    session = parity._McpJsonRpcSession("http://127.0.0.1:1/sites/x/mcp", "tok")
    assert session.tools_call("wp_cli", {"args": "eval 'echo 1;'"}) == "plain refusal text"


def test_mcp_jsonrpc_session_raises_on_jsonrpc_error(monkeypatch):
    import pytest

    def fake_urlopen(request, timeout=None):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}}).encode("utf-8")
        return _FakeHttpResponse(body, {})

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    session = parity._McpJsonRpcSession("http://127.0.0.1:1/sites/x/mcp", "tok")
    with pytest.raises(RuntimeError, match="boom"):
        session.tools_list()


def test_fetch_lane_h_records_real_client_against_a_fake_transport(monkeypatch):
    """Exercises the actual `fetch_lane_h_records` function (not just the
    session class it uses) end to end at the Python level, with the only
    fake being the network transport — everything else (the call sequence,
    the StepRecord assembly) is the real code path this session proved
    against a live container."""
    seen_methods = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        seen_methods.append(payload["method"])
        if payload["method"] == "initialize":
            result: object = {"protocolVersion": "2024-11-05"}
        elif payload["method"] == "tools/list":
            result = {"tools": list(range(13))}
        else:
            result = {"content": [{"type": "text", "text": "ok"}]}
        body = json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}).encode("utf-8")
        return _FakeHttpResponse(body, {"mcp-session-id": "sess-abc"})

    monkeypatch.setattr(parity.urllib.request, "urlopen", fake_urlopen)
    records = parity.fetch_lane_h_records("http://127.0.0.1:1/sites/acme-site/mcp", "tok", "acme-site")
    assert parity.missing_canonical_steps(records) == []
    assert parity.assert_tools_list_count(records) is True
    assert seen_methods[0] == "initialize"
    assert seen_methods[1] == "tools/list"
