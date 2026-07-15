#!/usr/bin/env python3
"""Exact provider policy, preflight parsing, and sanitized receipt construction."""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

import safe_curl


Transport = Callable[[safe_curl.CurlRequest], safe_curl.CurlResult]
GEMINI_ORIGIN = "https://generativelanguage.googleapis.com"
OLLAMA_ORIGIN = "http://127.0.0.1:11434"
_GEMINI_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OLLAMA_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_BLOCKED_ERRORS = {
    "trusted_curl_unavailable", "curl_capability_unavailable",
    "unsupported_platform", "timeout",
    "transport_unavailable", "tls_verification_failed", "transport_error",
}


@dataclass(frozen=True)
class PreflightReceipt:
    schema_version: int
    provider: str
    model: str
    timestamp: str
    status: str
    endpoint_class: str
    error_code: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "model": self.model,
            "timestamp": self.timestamp,
            "status": self.status,
            "endpoint_class": self.endpoint_class,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class PreflightResult:
    receipt: PreflightReceipt
    diagnostic: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _endpoint_class(provider_name: str) -> str:
    return "google_models_api" if provider_name == "gemini" else "local_ollama"


def _receipt(
    provider_name: str, model: str, error_code: str, timestamp: str | None,
) -> PreflightResult:
    status = "pass" if error_code == "none" else (
        "blocked" if error_code in _BLOCKED_ERRORS else "fail"
    )
    receipt = PreflightReceipt(
        1, provider_name, model, timestamp or _utc_now(), status,
        _endpoint_class(provider_name), error_code,
    )
    diagnostic = "" if status == "pass" else f"provider preflight {status}: {error_code}"
    return PreflightResult(receipt, diagnostic)


def _validate_model(provider_name: str, model: str) -> bool:
    if not isinstance(model, str):
        return False
    if provider_name == "gemini":
        return _GEMINI_MODEL.fullmatch(model) is not None
    if provider_name == "ollama":
        return _OLLAMA_MODEL.fullmatch(model) is not None and ".." not in model
    return False


def _gemini_credentials(environ: Mapping[str, str]) -> tuple[str, ...]:
    values = (environ.get("GOOGLE_API_KEY"), environ.get("GEMINI_API_KEY"))
    return tuple(value for value in values if isinstance(value, str) and value)


def _gemini_key(environ: Mapping[str, str]) -> str | None:
    credentials = _gemini_credentials(environ)
    return credentials[0] if credentials else None


def _valid_key(key: str) -> bool:
    return 1 <= len(key) <= 512 and all(0x21 <= ord(char) <= 0x7E for char in key)


def _model_contains_credential(model: str, environ: Mapping[str, str]) -> bool:
    return isinstance(model, str) and any(
        credential in model for credential in _gemini_credentials(environ)
    )


def _json_object(body: bytes) -> dict | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _http_error(result: safe_curl.CurlResult) -> str | None:
    if result.error_code:
        return result.error_code
    if result.status_code in {401, 403}:
        return "authentication_failed"
    if result.status_code == 404:
        return "model_not_found"
    if result.status_code == 429:
        return "rate_limited"
    if not 200 <= result.status_code < 300:
        return "provider_error"
    return None


def _gemini_metadata_request(model: str, key: str, timeout: int) -> safe_curl.CurlRequest:
    path = f"/v1beta/models/{model}"
    policy = safe_curl.CurlPolicy((GEMINI_ORIGIN,), (path,), 256 * 1024)
    return safe_curl.CurlRequest(
        "GET", f"{GEMINI_ORIGIN}{path}", policy,
        headers=(("Accept", "application/json"), ("x-goog-api-key", key)),
        timeout_seconds=timeout,
    )


def _gemini_preflight(
    model: str, key: str, transport: Transport, timeout: int, timestamp: str | None,
) -> PreflightResult:
    response = transport(_gemini_metadata_request(model, key, timeout))
    error = _http_error(response)
    if error:
        return _receipt("gemini", model, error, timestamp)
    payload = _json_object(response.body)
    if payload is None:
        return _receipt("gemini", model, "malformed_response", timestamp)
    if payload.get("name") != f"models/{model}":
        return _receipt("gemini", model, "model_identity_mismatch", timestamp)
    methods = payload.get("supportedGenerationMethods")
    if not isinstance(methods, list) or "generateContent" not in methods:
        return _receipt("gemini", model, "generation_not_advertised", timestamp)
    return _receipt("gemini", model, "none", timestamp)


def _ollama_show_request(model: str, timeout: int) -> safe_curl.CurlRequest:
    path = "/api/show"
    policy = safe_curl.CurlPolicy((OLLAMA_ORIGIN,), (path,), 512 * 1024)
    body = json.dumps({"model": model}, separators=(",", ":")).encode()
    return safe_curl.CurlRequest(
        "POST", f"{OLLAMA_ORIGIN}{path}", policy, body,
        (("Content-Type", "application/json"),), timeout,
    )


def _ollama_preflight(
    model: str, transport: Transport, timeout: int, timestamp: str | None,
) -> PreflightResult:
    response = transport(_ollama_show_request(model, timeout))
    error = _http_error(response)
    if error:
        return _receipt("ollama", model, error, timestamp)
    payload = _json_object(response.body)
    if payload is None:
        return _receipt("ollama", model, "malformed_response", timestamp)
    if "error" in payload:
        message = payload.get("error")
        if not isinstance(message, str):
            return _receipt("ollama", model, "malformed_response", timestamp)
        normalized = message.lower()
        code = "model_not_found" if any(
            phrase in normalized for phrase in ("not found", "does not exist", "missing model")
        ) else "provider_error"
        return _receipt("ollama", model, code, timestamp)
    return _receipt("ollama", model, "none", timestamp)


def preflight(
    provider_name: str,
    model: str,
    *,
    transport: Transport | None = None,
    environ: Mapping[str, str] | None = None,
    timestamp: str | None = None,
    timeout: int = 30,
) -> PreflightResult:
    """Check exact model metadata without generation or unsafe diagnostics."""
    if provider_name not in {"ollama", "gemini"}:
        return _receipt(provider_name, str(model), "invalid_provider", timestamp)
    selected_environ = environ if environ is not None else os.environ
    if provider_name == "gemini" and _model_contains_credential(model, selected_environ):
        return _receipt("gemini", "[redacted]", "model_matches_credential", timestamp)
    if not _validate_model(provider_name, model):
        return _receipt(provider_name, str(model), "invalid_model", timestamp)
    selected_transport = transport or safe_curl.execute
    if provider_name == "ollama":
        return _ollama_preflight(model, selected_transport, timeout, timestamp)
    key = _gemini_key(selected_environ)
    if key is None:
        return _receipt("gemini", model, "credential_missing", timestamp)
    if not _valid_key(key):
        return _receipt("gemini", model, "credential_invalid", timestamp)
    return _gemini_preflight(model, key, selected_transport, timeout, timestamp)


def _generation_error(response: safe_curl.CurlResult) -> str | None:
    error = _http_error(response)
    return error if error else None


def _ollama_num_ctx(environ: Mapping[str, str]) -> int | None:
    raw = environ.get("OLLAMA_NUM_CTX", "32768")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1024 <= value <= 131072 else None


def _ollama_generate_request(
    prompt: str, model: str, timeout: int, environ: Mapping[str, str],
) -> safe_curl.CurlRequest | None:
    num_ctx = _ollama_num_ctx(environ)
    if num_ctx is None:
        return None
    payload = {
        "model": model, "prompt": prompt, "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    }
    path = "/api/generate"
    policy = safe_curl.CurlPolicy((OLLAMA_ORIGIN,), (path,), 4 * 1024 * 1024)
    return safe_curl.CurlRequest(
        "POST", f"{OLLAMA_ORIGIN}{path}", policy,
        json.dumps(payload, separators=(",", ":")).encode(),
        (("Content-Type", "application/json"),), timeout,
    )


def _generate_ollama(
    prompt: str, model: str, timeout: int, transport: Transport, environ: Mapping[str, str],
) -> tuple[int, str, str]:
    request = _ollama_generate_request(prompt, model, timeout, environ)
    if request is None:
        return 1, "", "invalid_configuration"
    response = transport(request)
    error = _generation_error(response)
    if error:
        return 1, "", error
    payload = _json_object(response.body)
    if payload is None:
        return 1, "", "malformed_response"
    if isinstance(payload.get("error"), str):
        return 1, "", "provider_error"
    text = payload.get("response")
    return (0, text, "") if isinstance(text, str) and text.strip() else (1, "", "empty_response")


def _gemini_generate_request(
    prompt: str, model: str, key: str, timeout: int,
) -> safe_curl.CurlRequest:
    path = f"/v1beta/models/{model}:generateContent"
    policy = safe_curl.CurlPolicy((GEMINI_ORIGIN,), (path,), 4 * 1024 * 1024)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 16384, "temperature": 0.2},
    }
    return safe_curl.CurlRequest(
        "POST", f"{GEMINI_ORIGIN}{path}", policy,
        json.dumps(payload, separators=(",", ":")).encode(),
        (("Content-Type", "application/json"), ("x-goog-api-key", key)), timeout,
    )


def _gemini_text(payload: dict) -> tuple[str, bool]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return "", True
    if not candidates:
        return "", False
    if not isinstance(candidates[0], dict):
        return "", True
    content = candidates[0].get("content")
    if content is None:
        return "", False
    if not isinstance(content, dict):
        return "", True
    parts = content.get("parts")
    if parts is None:
        return "", False
    if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
        return "", True
    texts = [part["text"] for part in parts if "text" in part]
    if any(not isinstance(text, str) for text in texts):
        return "", True
    return "".join(texts), False


def _generate_gemini(
    prompt: str, model: str, timeout: int, transport: Transport, environ: Mapping[str, str],
) -> tuple[int, str, str]:
    key = _gemini_key(environ)
    if key is None:
        return 127, "", "credential_missing"
    if not _valid_key(key):
        return 1, "", "credential_invalid"
    response = transport(_gemini_generate_request(prompt, model, key, timeout))
    error = _generation_error(response)
    if error:
        return 1, "", error
    payload = _json_object(response.body)
    if payload is None:
        return 1, "", "malformed_response"
    text, malformed = _gemini_text(payload)
    if malformed:
        return 1, "", "malformed_response"
    return (0, text, "") if text.strip() else (1, "", "empty_response")


def generate(
    provider_name: str,
    prompt: str,
    model: str,
    timeout: int,
    *,
    transport: Transport | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """Generate after a caller-owned successful preflight, returning safe codes."""
    selected_environ = environ if environ is not None else os.environ
    if provider_name == "gemini" and _model_contains_credential(model, selected_environ):
        return 1, "", "model_matches_credential"
    if not _validate_model(provider_name, model):
        return 1, "", "invalid_model"
    selected_transport = transport or safe_curl.execute
    if provider_name == "ollama":
        return _generate_ollama(prompt, model, timeout, selected_transport, selected_environ)
    if provider_name == "gemini":
        return _generate_gemini(prompt, model, timeout, selected_transport, selected_environ)
    raise ValueError(f"unknown provider: {provider_name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Metadata-only provider preflight")
    parser.add_argument("--provider", required=True, choices=("ollama", "gemini"))
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    result = preflight(args.provider, args.model)
    print(json.dumps(result.receipt.as_dict(), sort_keys=True))
    return 0 if result.receipt.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
