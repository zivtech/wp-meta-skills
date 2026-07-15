#!/usr/bin/env python3
"""Provider policy, exact-model preflight, and receipt regressions."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import provider_preflight as provider  # noqa: E402
import safe_curl  # noqa: E402


FAKE_KEY = "AIza-PROVIDER-FAKE-KEY-DO-NOT-USE"
SECONDARY_KEY = "AIza-SECONDARY-FAKE-KEY-DO-NOT-USE"
PROMPT = "PROMPT-MUST-NEVER-ENTER-PREFLIGHT-RECEIPT"
MODEL = "gemini-test-model"


def _transport(body, status=200, error_code=""):
    payload = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def execute(request):
        return safe_curl.CurlResult(
            ok=not error_code and 200 <= status < 300,
            status_code=status,
            body=payload,
            error_code=error_code,
            diagnostic="request failed" if error_code else "",
            blocked=error_code in {"trusted_curl_unavailable", "transport_unavailable"},
        )

    return execute


def _serialized(result):
    return json.dumps(result.receipt.as_dict(), sort_keys=True)


def test_gemini_preflight_uses_header_auth_and_exact_fixed_path():
    captured = {}

    def transport(request):
        captured["request"] = request
        return _transport({
            "name": f"models/{MODEL}",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        })(request)

    result = provider.preflight(
        "gemini", MODEL, transport=transport, environ={"GOOGLE_API_KEY": FAKE_KEY},
        timestamp="2026-07-15T00:00:00Z",
    )
    request = captured["request"]
    assert request.method == "GET"
    assert request.url == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}"
    assert "?" not in request.url and FAKE_KEY not in request.url
    assert ("x-goog-api-key", FAKE_KEY) in request.headers
    assert result.receipt.status == "pass"
    assert result.receipt.error_code == "none"
    assert FAKE_KEY not in _serialized(result)
    assert PROMPT not in _serialized(result)


@pytest.mark.parametrize(
    ("model", "error_code"),
    [
        ("models/gemini-test", "invalid_model"),
        ("gemini%2ftest", "invalid_model"),
        ("gemini?key=x", "invalid_model"),
        ("user@gemini", "invalid_model"),
        ("gemini test", "invalid_model"),
    ],
)
def test_gemini_model_is_one_canonical_path_segment(model, error_code):
    result = provider.preflight(
        "gemini", model, transport=lambda _request: pytest.fail("must not call transport"),
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert result.receipt.error_code == error_code


def test_gemini_requires_exact_metadata_name_and_advertised_method():
    wrong = provider.preflight(
        "gemini", MODEL,
        transport=_transport({"name": "models/other", "supportedGenerationMethods": ["generateContent"]}),
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    unsupported = provider.preflight(
        "gemini", MODEL,
        transport=_transport({"name": f"models/{MODEL}", "supportedGenerationMethods": ["countTokens"]}),
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert wrong.receipt.error_code == "model_identity_mismatch"
    assert unsupported.receipt.error_code == "generation_not_advertised"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "authentication_failed"), (403, "authentication_failed"),
     (404, "model_not_found"), (429, "rate_limited"), (500, "provider_error")],
)
def test_http_errors_are_distinct_and_sanitized(status, expected):
    result = provider.preflight(
        "gemini", MODEL,
        transport=_transport({"error": {"message": FAKE_KEY}}, status=status),
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert result.receipt.error_code == expected
    assert FAKE_KEY not in _serialized(result)
    assert FAKE_KEY not in result.diagnostic


def test_missing_or_unsafe_gemini_key_stops_before_transport():
    called = False

    def transport(_request):
        nonlocal called
        called = True
        raise AssertionError("must not call")

    missing = provider.preflight("gemini", MODEL, transport=transport, environ={})
    unsafe = provider.preflight(
        "gemini", MODEL, transport=transport, environ={"GOOGLE_API_KEY": "bad\nkey"},
    )
    assert missing.receipt.error_code == "credential_missing"
    assert unsafe.receipt.error_code == "credential_invalid"
    assert called is False


def test_credential_misused_as_model_is_redacted_and_never_dispatched():
    called = False

    def transport(_request):
        nonlocal called
        called = True
        raise AssertionError("must not call")

    result = provider.preflight(
        "gemini", FAKE_KEY, transport=transport, environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    generation = provider.generate(
        "gemini", "hello", FAKE_KEY, 5, transport=transport,
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert result.receipt.error_code == "model_matches_credential"
    assert result.receipt.model == "[redacted]"
    assert FAKE_KEY not in _serialized(result)
    assert generation == (1, "", "model_matches_credential")
    assert called is False


def test_secondary_credential_alias_cannot_enter_url_receipt_or_stdout(
    monkeypatch, capsys,
):
    called = False
    environ = {"GOOGLE_API_KEY": FAKE_KEY, "GEMINI_API_KEY": SECONDARY_KEY}

    def transport(_request):
        nonlocal called
        called = True
        raise AssertionError("must not call")

    result = provider.preflight(
        "gemini", SECONDARY_KEY, transport=transport, environ=environ,
    )
    generation = provider.generate(
        "gemini", "hello", SECONDARY_KEY, 5, transport=transport, environ=environ,
    )
    assert result.receipt.model == "[redacted]"
    assert result.receipt.error_code == "model_matches_credential"
    assert SECONDARY_KEY not in _serialized(result)
    assert SECONDARY_KEY not in result.diagnostic
    assert generation == (1, "", "model_matches_credential")
    assert called is False

    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", SECONDARY_KEY)
    assert provider.main(["--provider", "gemini", "--model", SECONDARY_KEY]) == 2
    assert SECONDARY_KEY not in capsys.readouterr().out


def test_malformed_json_and_transport_block_are_distinct():
    malformed = provider.preflight(
        "gemini", MODEL, transport=_transport(b"{"), environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    blocked = provider.preflight(
        "gemini", MODEL,
        transport=_transport(b"", status=0, error_code="trusted_curl_unavailable"),
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert malformed.receipt.error_code == "malformed_response"
    assert blocked.receipt.status == "blocked"
    assert blocked.receipt.error_code == "trusted_curl_unavailable"


def test_ollama_show_uses_exact_tag_and_loopback_endpoint():
    captured = {}

    def transport(request):
        captured["request"] = request
        return _transport({"details": {"family": "test"}})(request)

    result = provider.preflight(
        "ollama", "qwen:test", transport=transport, environ={},
        timestamp="2026-07-15T00:00:00Z",
    )
    request = captured["request"]
    assert request.url == "http://127.0.0.1:11434/api/show"
    assert json.loads(request.body) == {"model": "qwen:test"}
    assert not any(name.lower() == "authorization" for name, _value in request.headers)
    assert result.receipt.status == "pass"


def test_ollama_404_is_model_not_found_without_provider_body():
    result = provider.preflight(
        "ollama", "missing:model",
        transport=_transport({"error": f"model missing {PROMPT}"}, status=404), environ={},
    )
    assert result.receipt.error_code == "model_not_found"
    assert PROMPT not in _serialized(result)
    assert PROMPT not in result.diagnostic


def test_ollama_structured_missing_model_is_model_not_found_without_body():
    result = provider.preflight(
        "ollama", "missing:model",
        transport=_transport({"error": f"model not found: {PROMPT}"}), environ={},
    )
    assert result.receipt.error_code == "model_not_found"
    assert PROMPT not in _serialized(result)
    assert PROMPT not in result.diagnostic


@pytest.mark.parametrize(
    "payload",
    [
        {"candidates": {}},
        {"candidates": [1]},
        {"candidates": [{"content": []}]},
        {"candidates": [{"content": {"parts": {}}}]},
        {"candidates": [{"content": {"parts": [1]}}]},
        {"candidates": [{"content": {"parts": [{"text": 123}]}}]},
    ],
)
def test_gemini_wrong_response_types_are_malformed_not_exceptions(payload):
    result = provider.generate(
        "gemini", "hello", MODEL, 5, transport=_transport(payload),
        environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert result == (1, "", "malformed_response")


def test_generation_parsers_return_safe_error_codes():
    ollama = provider.generate(
        "ollama", "hello", "qwen:test", 5,
        transport=_transport({"error": FAKE_KEY}, status=500), environ={},
    )
    gemini = provider.generate(
        "gemini", "hello", MODEL, 5,
        transport=_transport({"candidates": []}), environ={"GOOGLE_API_KEY": FAKE_KEY},
    )
    assert ollama == (1, "", "provider_error")
    assert gemini == (1, "", "empty_response")
    assert FAKE_KEY not in repr((ollama, gemini))


def _authorized_live_preflight(environ, transport=None):
    if environ.get("WP_META_SKILLS_LIVE_PROVIDER_AUTHORIZED") != "1":
        raise ValueError("explicit live-provider authorization is required")
    model = environ.get("GEMINI_LIVE_MODEL")
    key = environ.get("GOOGLE_API_KEY") or environ.get("GEMINI_API_KEY")
    if not model or not key:
        raise ValueError("GEMINI_LIVE_MODEL and Gemini credential are required")
    return provider.preflight("gemini", model, transport=transport, environ=environ)


def test_live_preflight_without_authorization_performs_zero_transport():
    called = False

    def transport(_request):
        nonlocal called
        called = True
        raise AssertionError("must not call")

    with pytest.raises(ValueError, match="authorization"):
        _authorized_live_preflight({
            "GEMINI_LIVE_MODEL": MODEL,
            "GOOGLE_API_KEY": FAKE_KEY,
        }, transport)
    assert called is False


@pytest.mark.live_provider
def test_live_gemini_metadata_preflight_is_sanitized():
    if os.environ.get("WP_META_SKILLS_LIVE_PROVIDER_AUTHORIZED") != "1":
        pytest.fail("explicit live-provider authorization is required")
    model = os.environ.get("GEMINI_LIVE_MODEL")
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not model or not key:
        pytest.fail("GEMINI_LIVE_MODEL and Gemini credential are required")
    result = provider.preflight("gemini", model)
    serialized = _serialized(result)
    assert result.receipt.status == "pass", result.receipt.error_code
    assert key not in serialized
    assert result.diagnostic == ""
