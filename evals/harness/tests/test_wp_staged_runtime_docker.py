"""Live Docker tests for the staged WordPress runtime boundary."""
from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_staging
import isolated_runtime_contract as runtime_contract
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
