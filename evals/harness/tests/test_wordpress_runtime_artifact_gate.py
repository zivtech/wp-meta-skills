"""Focused smoke-runner integration tests for the block artifact gate."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_execution_gate
import artifact_staging
import run_wordpress_runtime_smoke as smoke
from wp_runtime_types import RuntimeResult


EXECUTION_DIGEST = "c" * 64
RUNTIME_CHECKS = (
    {"id": "wp_cli_activation", "status": "pass", "required": True,
     "duration_sec": 0.1},
    {"id": "plugin_check", "status": "pass", "required": True,
     "duration_sec": 0.2},
    {"id": "container_browser", "status": "pass", "required": True,
     "duration_sec": 0.3},
)


def _gate(status: str, check_id: str, digest: str | None = None) -> dict:
    gate = {"status": status, "pass": status == "pass", "checks": [
        {"id": check_id, "status": status, "required": True},
    ]}
    if digest is not None:
        gate["execution_proof_digest"] = digest
    return gate


def _synthesized(staged, digest: str | None = EXECUTION_DIGEST):
    proof = SimpleNamespace(execution_proof_digest=digest) if digest is not None else None
    return SimpleNamespace(staged=staged, plugin_slug="generated", execution_proof=proof)


def _prepared(staged, build_status="pass", artifact_status="pass", *, digest=EXECUTION_DIGEST):
    artifact_gate = _gate(artifact_status, "runtime_artifact")
    if artifact_status == "pass":
        artifact_gate["execution_proof_digest"] = digest
    return smoke.PreparedRuntimeArtifact(
        synthesized=_synthesized(staged, digest), effective_block=staged,
        sandbox_output=None, block_build_gate=_gate(build_status, "npm_build"),
        block_runtime_artifact_gate=artifact_gate, phpunit_gate=None, wpcs_gate=None,
        trusted_provisioning={}, wrapped=None,
    )


def _kwargs(tmp_path, staged, *, artifact_kind="block", build=True):
    return {
        "artifact_kind": artifact_kind,
        "artifact_source_path": tmp_path / "source",
        "block_build_smoke": build,
        "phpunit_smoke": False,
        "provision_full_profile": False,
        "strict_full_profile": False,
        "expected_artifact_digest": artifact_staging.digest_manifest_tree(staged.manifest),
        "timeout_sec": 5,
        "workdir": tmp_path / "runtime",
    }


@pytest.fixture
def staged(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "plugin.php").write_text("<?php\n")
    value = artifact_staging.stage_tree(source, tmp_path / "stage")
    try:
        yield value
    finally:
        if value.lease.lease_id in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES:
            smoke.runtime_artifact_pipeline.workspace_lease.cleanup(value.lease)


def _run_with_prepared(tmp_path, monkeypatch, staged, prepared):
    calls = []
    monkeypatch.setattr(smoke, "_prepare_generated_runtime", lambda *_args: prepared)
    monkeypatch.setattr(smoke, "_release_prepared_runtime", lambda *_args: [])

    def run(request):
        calls.append(request)
        manifest = artifact_staging.manifest_sha256(request.staged.manifest)
        return RuntimeResult(
            "pass", request.evidence_id, request.input_artifact_digest,
            manifest, RUNTIME_CHECKS,
        )

    monkeypatch.setattr(smoke.wp_env_network_guard, "run_staged_runtime", run)
    result = smoke._run_isolated_smoke_input(
        staged, "evidence", _kwargs(tmp_path, staged),
    )
    return result, calls


@pytest.mark.parametrize("artifact_status", ["fail", "blocked"])
def test_nonpassing_artifact_gate_never_starts_runtime(
    tmp_path, monkeypatch, staged, artifact_status,
):
    result,calls=_run_with_prepared(
        tmp_path,monkeypatch,staged,_prepared(staged,artifact_status=artifact_status),
    )
    assert calls == []
    assert result["status"] == artifact_status
    assert result["block_build_smoke_status"] == "pass"
    assert result["block_runtime_artifact_gate_status"] == artifact_status


def test_build_failure_skips_artifact_validation_and_runtime(tmp_path, monkeypatch, staged):
    validation_calls=[]
    monkeypatch.setattr(
        smoke.runtime_artifact_pipeline,"build_block",
        lambda *_args: smoke.runtime_artifact_pipeline.BuildResult(
            "fail","build failed",("npm","run","build"),None,
        ),
    )
    monkeypatch.setattr(
        smoke.artifact_execution_gate,"validate_block_execution_artifact",
        lambda *_args,**_kwargs: validation_calls.append(True),
    )
    block_source=tmp_path/"block-source"; block_source.mkdir()
    (block_source/"block.json").write_text('{"name":"acme/card"}')
    restaged=artifact_staging.stage_tree(block_source,tmp_path/"block-stage")
    try:
        result=smoke._prepare_block_build(restaged,"block",True,5)
        assert result[2]["status"] == "fail"
        assert result[3] is None and result[4] is None
        assert validation_calls == []
    finally:
        smoke.runtime_artifact_pipeline.workspace_lease.cleanup(restaged.lease)
    prepared=smoke.PreparedRuntimeArtifact(
        None,staged,None,_gate("fail","npm_build"),None,None,None,{},None,
    )
    terminal,calls=_run_with_prepared(tmp_path,monkeypatch,staged,prepared)
    assert calls == [] and terminal["pass"] is False


def test_build_pass_runs_artifact_validation_exactly_once(tmp_path, monkeypatch, staged):
    block_source=tmp_path/"build-source"; block_source.mkdir()
    (block_source/"block.json").write_text('{"name":"acme/card"}')
    source=artifact_staging.stage_tree(block_source,tmp_path/"source-stage")
    output=artifact_staging.stage_tree(block_source,tmp_path/"output-stage")
    validation_calls=[]
    validation=artifact_execution_gate.BlockExecutionValidation(
        object(),_gate("fail","runtime_artifact"),(),
    )
    monkeypatch.setattr(
        smoke.runtime_artifact_pipeline,"build_block",
        lambda *_args: smoke.runtime_artifact_pipeline.BuildResult(
            "pass","built",("npm","run","build"),output,
        ),
    )

    def validate(*_args,**_kwargs):
        validation_calls.append(True)
        return validation

    monkeypatch.setattr(
        smoke.artifact_execution_gate,"validate_block_execution_artifact",validate,
    )
    try:
        result=smoke._prepare_block_build(source,"block",True,5)
        assert len(validation_calls) == 1
        assert result[2]["checks"] == [{
            "id":"npm_build","status":"pass","required":True,
            "detail":"built","command":["npm","run","build"],
        }]
        assert result[3]["status"] == "fail" and result[4] is validation.proof
    finally:
        smoke.runtime_artifact_pipeline.workspace_lease.cleanup(output.lease)
        smoke.runtime_artifact_pipeline.workspace_lease.cleanup(source.lease)


def test_both_gates_pass_runs_once_and_emits_exact_digest(tmp_path, monkeypatch, staged):
    result,calls=_run_with_prepared(tmp_path,monkeypatch,staged,_prepared(staged))
    assert len(calls) == 1
    assert result["status"] == "pass" and result["pass"] is True
    assert result["execution_proof_digest"] == EXECUTION_DIGEST
    assert result["block_runtime_artifact_gate"]["execution_proof_digest"] == EXECUTION_DIGEST


@pytest.mark.parametrize("gate_digest", [None, "d" * 64])
def test_missing_or_mismatched_bound_digest_never_starts_runtime(
    tmp_path, monkeypatch, staged, gate_digest,
):
    prepared=_prepared(staged)
    gate=dict(prepared.block_runtime_artifact_gate)
    if gate_digest is None:
        gate.pop("execution_proof_digest")
    else:
        gate["execution_proof_digest"]=gate_digest
    prepared=smoke.PreparedRuntimeArtifact(
        prepared.synthesized,prepared.effective_block,prepared.sandbox_output,
        prepared.block_build_gate,gate,prepared.phpunit_gate,prepared.wpcs_gate,
        prepared.trusted_provisioning,prepared.wrapped,
    )
    result,calls=_run_with_prepared(tmp_path,monkeypatch,staged,prepared)
    assert calls == []
    assert result["status"] == "blocked"
    assert result["block_runtime_artifact_gate_status"] == "blocked"


def test_plugin_runtime_does_not_request_block_artifact_gate(tmp_path, monkeypatch, staged):
    prepared=smoke.PreparedRuntimeArtifact(
        _synthesized(staged,None),None,None,None,None,None,None,{},None,
    )
    calls=[]
    monkeypatch.setattr(smoke,"_prepare_generated_runtime",lambda *_args:prepared)
    monkeypatch.setattr(smoke,"_release_prepared_runtime",lambda *_args:[])

    def run(request):
        calls.append(request)
        return RuntimeResult(
            "pass",request.evidence_id,request.input_artifact_digest,
            artifact_staging.manifest_sha256(request.staged.manifest),RUNTIME_CHECKS,
        )

    monkeypatch.setattr(smoke.wp_env_network_guard,"run_staged_runtime",run)
    result=smoke._run_isolated_smoke_input(
        staged,"evidence",_kwargs(tmp_path,staged,artifact_kind="plugin",build=False),
    )
    assert len(calls) == 1 and result["status"] == "pass"
    assert result["block_runtime_artifact_requested"] is False
    assert result["block_runtime_artifact_gate_status"] == "not_run"
