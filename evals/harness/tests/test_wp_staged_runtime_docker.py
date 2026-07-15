"""Live Docker tests for the staged WordPress runtime boundary."""
from __future__ import annotations

import platform
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_staging
import isolated_runtime_contract as runtime_contract
import materialize_wordpress_executor_packet as materializer
import run_wordpress_runtime_smoke as smoke
import runtime_artifact_pipeline
import wp_env_network_guard as guard
from wp_runtime_types import RuntimeRequest


def _synthesized(tmp_path, slug="safe-plugin"):
    source = tmp_path / "source"
    source.mkdir()
    fixture_root = HARNESS / "tests/fixtures"
    body = (fixture_root / "adversarial-runtime-plugin.php").read_text(encoding="utf-8")
    (source / "plugin.php").write_text(body, encoding="utf-8")
    generated_js = fixture_root / "adversarial-runtime-plugin.js"
    (source / "wp-runtime-adversarial.js").write_bytes(generated_js.read_bytes())
    staged = artifact_staging.stage_tree(source, tmp_path / "input-parent")
    synthesized = runtime_artifact_pipeline.synthesize_plugin_runtime(
        staged, slug, tmp_path / "runtime-parent",
    )
    digest = artifact_staging.digest_manifest_tree(staged.manifest)
    return staged, synthesized, digest


def _cleanup(staged, synthesized):
    runtime_artifact_pipeline.cleanup_component("synthesized_runtime", synthesized.staged)
    artifact_staging.cleanup_staged_tree(staged)


def _request(synthesized, digest, parent):
    return RuntimeRequest(
        synthesized.staged, synthesized.plugin_slug, "evidence-123", digest, digest,
        1800, parent, requested_oracles=runtime_contract.ADVERSARIAL_REQUESTED_ORACLES,
    )


@pytest.fixture(scope="module")
def live_runtime_result(tmp_path_factory):
    if platform.system() != "Linux" or shutil.which("docker") is None:
        pytest.skip("real staged runtime requires Linux Docker")
    tmp_path = tmp_path_factory.mktemp("isolated-runtime")
    staged, synthesized, digest = _synthesized(tmp_path)
    try:
        yield guard.run_staged_runtime(_request(synthesized, digest, tmp_path / "live-result"))
    finally:
        _cleanup(staged, synthesized)


@pytest.mark.docker_boundary
def test_real_generated_plugin_uses_internal_runtime(live_runtime_result):
    assert live_runtime_result.status == "pass", live_runtime_result.reason


@pytest.mark.docker_boundary
def test_real_runtime_exercises_named_hostile_canaries(live_runtime_result):
    expected = set(runtime_contract.REQUIRED_CHECKS_BY_PROFILE[runtime_contract.ADVERSARIAL_PROFILE])
    checks = {item["id"]: item["status"] for item in live_runtime_result.checks}
    assert expected <= set(checks) and all(checks[name] == "pass" for name in expected)


@pytest.mark.docker_boundary
def test_real_runtime_is_mount_free_and_cleanup_converges(live_runtime_result):
    created = live_runtime_result.inspection["created"]["services"]
    assert all(not service["mounts"] for service in created.values())
    assert all(
        item["state"] not in {"retained", "unknown"}
        for item in live_runtime_result.cleanup.values()
    )


@pytest.fixture(scope="module")
def live_block_runtime_results(tmp_path_factory):
    if platform.system() != "Linux" or shutil.which("docker") is None:
        pytest.skip("real isolated block runtime requires Linux Docker")
    root = tmp_path_factory.mktemp("isolated-block-runtime")
    packet = HARNESS.parent / "suites/wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md"
    artifact = root / "artifact"
    materialized = materializer.materialize_packet(
        "block", packet.read_text(encoding="utf-8"), artifact,
    )
    assert materialized["pass"] is True
    digest = artifact_staging.digest_regular_tree(artifact)

    def run(name, text):
        return smoke.run_smoke(
            timeout_sec=1800, workdir=root / name, artifact_path=artifact,
            artifact_kind="block", expected_artifact_digest=digest,
            evidence_id=f"plan011-{name}", block_build_smoke=True,
            block_name="acme/runtime-card", editor_insert_render_smoke=True,
            expected_frontend_selector=".wp-block-acme-runtime-card",
            expected_frontend_text=text, provision_full_profile=True,
            strict_full_profile=True,
        )

    started = time.monotonic()
    passing = run("pass", "Runtime block smoke")
    near_miss = run("near-miss", "Runtime block smoke near miss")
    return passing, near_miss, round(time.monotonic() - started, 3)


@pytest.mark.docker_boundary
def test_real_block_profile_proves_registration_editor_frontend_and_cleanup(
    live_block_runtime_results,
):
    passing, _near_miss, elapsed = live_block_runtime_results
    assert elapsed <= 1800
    assert passing["status"] == "pass" and passing["runtime_profile_id"] == "block-runtime"
    assert [item["id"] for item in passing["checks"]] == [
        "wp_cli_activation", "plugin_check", "block_registration",
        "container_browser", "block_editor_frontend", "runtime_identity",
    ]
    assert passing["block_build_smoke_status"] == "pass"
    assert passing["block_runtime_artifact_gate_status"] == "pass"
    assert passing["execution_proof_digest"] == passing["block_runtime_artifact_gate"]["execution_proof_digest"]
    assert passing["sandbox_posture"]["host_fallback"] is False
    assert passing["artifact_retention"]["retained"] is False


@pytest.mark.docker_boundary
def test_real_block_near_miss_fails_and_still_converges_cleanup(live_block_runtime_results):
    _passing, near_miss, _elapsed = live_block_runtime_results
    assert near_miss["status"] != "pass" and near_miss["pass"] is False
    assert near_miss["artifact_retention"]["retained"] is False
    assert all(item["state"] in {"removed", "released"}
               for item in near_miss.get("cleanup", {}).values())
