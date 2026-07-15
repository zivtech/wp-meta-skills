"""Executable parity tests for the isolated authenticated request contract."""
from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import isolated_runtime_contract as contract  # noqa: E402
import wp_runtime_oracles as oracles  # noqa: E402
import wp_runtime_topology as topology  # noqa: E402
from wp_runtime_evidence import RuntimeDeadline  # noqa: E402
from wp_runtime_types import BlockRuntimeAssertion  # noqa: E402


def test_plain_permalink_rest_canary_is_query_bounded():
    policy = (HARNESS / "runtime-images/browser/request-policy.js").read_text()
    assert "entries.length !== Object.keys(expected).length" in policy
    assert "rest_route" in policy
    assert "/wp-json/wp-runtime-canary/v1/" not in policy


def test_generated_browser_fixture_attempts_the_controlled_host_listener():
    fixture = (HARNESS / "tests/fixtures/adversarial-runtime-plugin.js").read_text()
    policy = (HARNESS / "runtime-images/browser/browser-policy.js").read_text()
    assert "__WP_RUNTIME_HOST_LISTENER_URL__" in fixture and "host_listener:" in fixture
    assert "controlledHostListener" in policy and "host_listener" in policy


def test_browser_policy_reads_cookie_complete_headers():
    policy = (HARNESS / "runtime-images/browser/browser-policy.js").read_text()
    assert "await request.allHeaders()" in policy
    assert "headers: request.headers()" not in policy


def test_block_topology_binds_exact_profile_and_disposable_post():
    images = {name: "sha256:" + str(index) * 64
              for index, name in enumerate(("database", "wordpress", "browser"), 1)}
    identities = {"database": "999:999", "wordpress": "33:33", "browser": "1000:1000"}
    artifact_image = "sha256:" + "4" * 64
    spec = topology.build_compose(
        images, identities, artifact_image, "safe-plugin",
        contract.BLOCK_PROFILE, contract.BLOCK_CANARY_POST_ID,
    )
    assert spec["services"]["gateway"]["command"] == [
        "/opt/wp-runtime/gateway-policy.js", "safe-plugin",
        contract.BLOCK_PROFILE, str(contract.BLOCK_CANARY_POST_ID),
    ]
    assert topology.validate_compose(
        spec, artifact_image, "safe-plugin", contract.BLOCK_PROFILE,
        contract.BLOCK_CANARY_POST_ID,
    )
    with pytest.raises(ValueError, match="post identity"):
        topology.build_compose(
            images, identities, artifact_image, "safe-plugin",
            contract.BLOCK_PROFILE, contract.BLOCK_CANARY_POST_ID + 1,
        )
    mutated = json.loads(json.dumps(spec))
    mutated["services"]["gateway"]["command"][-1] = "0"
    with pytest.raises(ValueError, match="command drift"):
        topology.validate_compose(
            mutated, artifact_image, "safe-plugin", contract.BLOCK_PROFILE,
            contract.BLOCK_CANARY_POST_ID,
        )


def test_block_post_creation_uses_and_verifies_reviewed_import_id(monkeypatch):
    calls = []
    monkeypatch.setattr(oracles, "_run", lambda command, *_args: (
        calls.append(command) or {"returncode": 0,
                                  "stdout": str(contract.BLOCK_CANARY_POST_ID),
                                  "stderr": ""}
    ))
    observed = oracles._create_disposable_block_post(
        ["docker", "compose"], RuntimeDeadline.start(60),
    )
    assert observed == contract.BLOCK_CANARY_POST_ID
    assert f"--import_id={contract.BLOCK_CANARY_POST_ID}" in calls[0]


def test_block_post_creation_failure_preserves_completed_oracle_rows(monkeypatch):
    completed = tuple({"id": check_id, "status": "pass"} for check_id in (
        "wp_cli_activation", "plugin_check", "block_registration",
    ))
    monkeypatch.setattr(oracles, "_run_steps", lambda _steps: completed)
    monkeypatch.setattr(
        oracles, "_create_disposable_block_post",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("post refused")),
    )
    assertion = BlockRuntimeAssertion(
        "acme/runtime-card", ".wp-block-acme-runtime-card", "Exact runtime text",
    )
    with pytest.raises(oracles.OracleFailure) as caught:
        oracles._block_oracles(
            ["docker", "compose"], "safe-plugin", RuntimeDeadline.start(60), assertion,
        )
    assert caught.value.step == "block_post_create"
    assert caught.value.checks == completed


def test_standard_browser_profile_does_not_require_fixture_markers(monkeypatch):
    common = {name: True for name in {"same_origin", "external_http", "external_navigation",
        "websocket", "webrtc", "service_worker", "download", "popup"}}
    monkeypatch.setattr(oracles, "_run", lambda *_args: {"returncode": 0,
        "stdout": json.dumps({"profile": contract.STANDARD_PROFILE,
                              "canaries": common}) + "\n", "stderr": ""})
    checks = oracles._browser_policy(
        ["docker", "compose"], RuntimeDeadline.start(60), contract.STANDARD_PROFILE,
        "safe-plugin",
    )
    assert tuple(item["id"] for item in checks) == ("container_browser",)
    assert "generated_frontend_js" not in checks[0]["canaries"]


def test_block_browser_profile_requires_exact_selector_scoped_proof(monkeypatch):
    assertion = BlockRuntimeAssertion(
        "acme/runtime-card", ".wp-block-acme-runtime-card", "Exact runtime text",
    )
    digest = hashlib.sha256(assertion.expected_frontend_text.encode()).hexdigest()
    common = {name: True for name in {"same_origin", "external_http", "external_navigation",
        "websocket", "webrtc", "service_worker", "download", "popup"}}
    proof = {"status": "pass", "block_name": assertion.block_name,
        "frontend_selector": assertion.frontend_selector, "expected_text_sha256": digest,
        "observed_text_sha256": digest, "match_count": 1, "visible": True,
        "normalization": "unicode-nfc-whitespace-collapse-trim"}
    monkeypatch.setattr(oracles, "_run", lambda *_args: {"returncode": 0,
        "stdout": json.dumps({"profile": contract.BLOCK_PROFILE,
                              "canaries": common, "block_editor_frontend": proof}) + "\n",
        "stderr": ""})
    checks = oracles._browser_policy(
        ["docker", "compose"], RuntimeDeadline.start(60), contract.BLOCK_PROFILE,
        "safe-plugin", assertion, contract.BLOCK_CANARY_POST_ID,
    )
    assert tuple(item["id"] for item in checks) == (
        "container_browser", "block_editor_frontend",
    )
    malformed = dict(proof, match_count=2)
    with pytest.raises(RuntimeError, match="malformed or mismatched"):
        oracles._block_frontend_check({"block_editor_frontend": malformed}, assertion)


def _policy_cases():
    post_id = contract.BLOCK_CANARY_POST_ID
    block = {"origin": "http://gateway-frontend:8081", "slug": "safe-plugin",
             "profile": contract.BLOCK_PROFILE, "postId": post_id}
    standard = dict(block, profile=contract.STANDARD_PROFILE, postId=0)
    adversarial = dict(block, profile=contract.ADVERSARIAL_PROFILE, postId=0)
    headers = {"content-type": "application/json", "x-wp-nonce": "abcdefghij",
               "cookie": "wordpress=canary"}
    body = json.dumps({"id": post_id, "content": "<!-- wp:acme/runtime-card /-->",
                       "status": "publish"})
    return [
        (block, "GET", f"/?p={post_id}", {}, "", True),
        (block, "GET", f"/?p={post_id + 1}", {}, "", False),
        (block, "GET", f"/wp-admin/post.php?post={post_id}&action=edit", {}, "", True),
        (block, "GET", f"/wp-admin/post.php?post={post_id + 1}&action=edit", {}, "", False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}?_locale=user", headers, body, True),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id + 1}?_locale=user", headers, body, False),
        (standard, "PUT", f"/wp-json/wp/v2/posts/{post_id}", headers, body, False),
        (adversarial, "GET", "/wp-admin/post-new.php", {}, "", True),
        (block, "GET", "/wp-admin/post-new.php", {}, "", False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}?_locale=user&_locale=user", headers, body, False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}?context=edit", headers, body, False),
        (block, "POST", f"/wp-json/wp/v2/posts/{post_id}", headers, body, False),
        (block, "PATCH", f"/wp-json/wp/v2/posts/{post_id}", headers, body, False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}", headers,
         json.dumps({"id": post_id + 1, "content": "wrong", "status": "publish"}), False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}", headers,
         json.dumps({"content": "missing id", "status": "publish"}), False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}",
         dict(headers, **{"content-type": "application/jsonp"}), body, False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}",
         dict(headers, **{"x-wp-nonce": "short"}), body, False),
        (block, "PUT", f"/wp-json/wp/v2/posts/{post_id}",
         dict(headers, cookie="x" * 4097), body, False),
        (block, "GET", "/wp-content/plugins/safe-plugin/view.js?ver=1", {}, "", True),
        (block, "GET", "/wp-content/plugins/safe-plugin/view.js?ver=1&ver=1", {}, "", False),
        (block, "GET", "/wp-json/wp/v2/users", {}, "", False),
    ]


def test_browser_and_gateway_use_one_executable_request_policy():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    browser = (HARNESS / "runtime-images/browser/browser-policy.js").read_text()
    gateway = (HARNESS / "runtime-images/browser/gateway-policy.js").read_text()
    assert "require('./request-policy')" in browser and "require('./request-policy')" in gateway
    payload = [{"context": context, "request": {"method": method, "url": url,
                "headers": headers}, "body": value, "expected": expected}
               for context, method, url, headers, value, expected in _policy_cases()]
    script = """
const policy=require(process.argv[1]);
for (const item of JSON.parse(process.argv[2])) {
  const kind=policy.classifyRequest(item.request,item.context);
  const actual=Boolean(kind && (kind==='read' || policy.validateBody(kind,Buffer.from(item.body),item.context)));
  if (actual!==item.expected) throw new Error(JSON.stringify({item,kind,actual}));
}
"""
    result = subprocess.run(
        [node, "-e", script, str(HARNESS / "runtime-images/browser/request-policy.js"),
         json.dumps(payload)], check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
