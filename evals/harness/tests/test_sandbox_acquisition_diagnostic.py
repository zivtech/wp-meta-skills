import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import sandbox_acquisition_diagnostic as diagnostic


PROFILE = SimpleNamespace(allowed_hosts=frozenset({"api.github.com", "codeload.github.com"}))


def test_rate_limit_diagnostic_emits_only_allowlisted_category_and_host():
    secret = "super-secret-bearer-value"
    stderr = f"Bearer {secret}\nhttps://user:pass@api.github.com/repos/x/y?token={secret}\nAPI rate limit exceeded"
    value = json.loads(diagnostic.describe(PROFILE, {"returncode": 1, "stdout": "", "stderr": stderr}))
    encoded = json.dumps(value)
    assert value["category"] == "http-status" and value["detail"] == "rate-limit"
    assert value["hosts"] == ["api.github.com"] and value["returncode"] == 1
    assert secret not in encoded and "user" not in encoded and "pass" not in encoded and "token" not in encoded


@pytest.mark.parametrize(("message", "category", "detail"), [
    ("curl error 6 while downloading", "dns", "curl-6"),
    ("curl error 7 while downloading", "proxy-connect", "curl-7"),
    ("curl error 60 while downloading", "tls", "curl-60"),
    ("HTTP/2 403 from codeload.github.com", "http-status", "http-403"),
    ("Your requirements could not be resolved", "dependency-resolution", "solver"),
])
def test_recognized_failures_have_fixed_diagnostic_vocabulary(message, category, detail):
    value = json.loads(diagnostic.describe(PROFILE, {"returncode": 2, "stdout": message, "stderr": ""}))
    assert (value["category"], value["detail"]) == (category, detail)


def test_unknown_malformed_and_oversized_output_is_digest_only():
    secret = b"Cookie: session=hidden\x1b[31m\x00\xff" + b"x" * 20000
    encoded = diagnostic.describe(PROFILE, {"returncode": True, "stdout": secret, "stderr": b"\xffunknown"})
    value = json.loads(encoded)
    assert value["category"] == "unclassified" and value["detail"] == "none" and value["returncode"] == -1
    assert value["stdout"]["bytes"] == len(secret) and len(value["stdout"]["sha256"]) == 64
    assert len(encoded) < 512 and "hidden" not in encoded and "cookie" not in encoded


def test_host_matching_rejects_suffix_and_subdomain_confusion():
    value = json.loads(diagnostic.describe(PROFILE, {"returncode": 1, "stdout": "evilapi.github.com api.github.com.evil", "stderr": ""}))
    assert value["hosts"] == []


def test_proxy_snapshot_is_numeric_only_bounded_and_excludes_nonce_and_secrets():
    status={"accepted":1,"active":0,"completed":0,"rejected":1,"rejected_peer":0,"rejected_capacity":1,"rejected_handler":0,"nonce":"secret-nonce","credential":"hidden"}
    encoded=diagnostic.describe(PROFILE,{"returncode":1,"stdout":"Bearer hidden","stderr":""},status); value=json.loads(encoded)
    assert value["proxy_status"]=={key:status[key] for key in diagnostic._PROXY_KEYS}
    assert len(encoded)<1024 and "secret-nonce" not in encoded and "credential" not in encoded and "hidden" not in encoded
