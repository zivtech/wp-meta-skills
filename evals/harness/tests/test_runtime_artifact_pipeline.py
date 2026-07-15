"""Security contracts for Step 5 runtime artifact capability flow."""
import dataclasses
import io
import json
import tarfile
from pathlib import Path

import pytest

import artifact_execution
import artifact_execution_graph
import artifact_layout
import artifact_staging
import run_wordpress_runtime_smoke as runtime_smoke
import runtime_artifact_pipeline as pipeline
import sandbox_evidence
import workspace_lease


def write_block(root: Path, marker: str) -> Path:
    block = root / "blocks" / "card"
    build = block / "build"
    build.mkdir(parents=True)
    (block / "block.json").write_text(
        '{"apiVersion":3,"name":"acme/card","title":"Card","category":"widgets","textdomain":"acme-card"}'
    )
    (build / "block.json").write_text((block / "block.json").read_text())
    (build / "marker.js").write_text(marker)
    return root


def import_sandbox_output(source: Path, parent: Path):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive:
        archive.add(source,arcname=".")
    stream.seek(0)
    return artifact_staging.import_tar_stream(stream,parent,dependency_policy="strict")


def proof_for(output):
    source_entries = tuple(
        entry for entry in output.manifest
        if entry.path.endswith("block.json") and "build" not in Path(entry.path).parts
    )
    source = artifact_layout.select_source_layout(source_entries)
    layout = artifact_layout.select_post_build_layout(output.manifest, source)
    with artifact_staging.hold_staged_tree(output) as held:
        return artifact_execution_graph.build_execution_proof(held, layout)


def test_pass_without_authentic_sandbox_output_blocks(tmp_path, monkeypatch):
    source = write_block(tmp_path / "source", "stale")
    staged = artifact_staging.stage_tree(source, tmp_path / "input")
    outcome = artifact_execution.ExecutionOutcome("pass", "passed", ("npm", "run", "build"), None)
    monkeypatch.setattr(pipeline.artifact_execution, "run_generated", lambda *_args: outcome)
    try:
        result = pipeline.build_block(staged, 5)
        assert result.status == "blocked"
        assert result.output is None
    finally:
        workspace_lease.cleanup(staged.lease)


def test_forged_privileged_role_is_rejected_downstream(tmp_path):
    source=write_block(tmp_path/"source","stale")
    staged=artifact_staging.stage_tree(source,tmp_path/"input")
    forged=dataclasses.replace(staged,role=artifact_staging.StageRole.SANDBOX_OUTPUT)
    try: assert pipeline._authentic_role(forged,artifact_staging.StageRole.SANDBOX_OUTPUT) is False
    finally: workspace_lease.cleanup(staged.lease)


def test_typed_staging_receipt_survives_execution_outcome_and_build_result(tmp_path, monkeypatch):
    source=write_block(tmp_path/"source","fresh")
    staged=artifact_staging.stage_tree(source,tmp_path/"input")
    receipt=artifact_staging.StagingCleanupReceipt(
        "sandbox_output",artifact_staging.StageRole.SANDBOX_OUTPUT,staged.lease,staged.root,
        "retained",True,True,str(staged.root),"WorkspaceCleanupError: cleanup did not complete normally",
    )
    result=pipeline.artifact_execution.sandboxed_package_runner.SandboxResult(
        "blocked",None,"","",None,"import blocked","container",staging_cleanup_receipts=(receipt,)
    )
    monkeypatch.setattr(pipeline.artifact_execution,"_profile",lambda *_args:"approved")
    monkeypatch.setattr(pipeline.artifact_execution,"_image",lambda _kind:"node@sha256:"+"a"*64)
    monkeypatch.setattr(pipeline.artifact_execution.sandboxed_package_runner,"run_sandbox",lambda _request:result)
    try:
        outcome=pipeline.artifact_execution.run_generated(staged,"npm-build",5)
        build=pipeline.build_block(staged,5)
        assert outcome.staging_cleanup_receipts==(receipt,)
        assert build.status=="blocked" and build.staging_cleanup_receipts==(receipt,)
    finally: workspace_lease.cleanup(staged.lease)


def test_failed_generated_command_adds_bounded_scrubbed_diagnostic(tmp_path, monkeypatch):
    source=write_block(tmp_path/"source","fresh")
    staged=artifact_staging.stage_tree(source,tmp_path/"input")
    stderr="x"*1200+"\npassword=topsecret\nwebpack failed at blocks/card/index.js"
    result=pipeline.artifact_execution.sandboxed_package_runner.SandboxResult(
        "fail",1,"",stderr,None,
        sandbox_evidence.encode("fail",error="generated command failed"),"container",
    )
    monkeypatch.setattr(pipeline.artifact_execution,"_profile",lambda *_args:"approved")
    monkeypatch.setattr(pipeline.artifact_execution,"_image",lambda _kind:"node@sha256:"+"a"*64)
    monkeypatch.setattr(
        pipeline.artifact_execution.sandboxed_package_runner,"run_sandbox",
        lambda _request:result,
    )
    try:
        outcome=pipeline.artifact_execution.run_generated(staged,"npm-build",5)
        errors=json.loads(outcome.detail)["errors"]
        assert errors[0]=="generated command failed"
        assert errors[1].endswith("password=[REDACTED]\nwebpack failed at blocks/card/index.js")
        tail=errors[1].removeprefix(pipeline.artifact_execution.DIAGNOSTIC_PREFIX)
        assert "topsecret" not in outcome.detail
        assert len(tail)<=pipeline.artifact_execution.DIAGNOSTIC_TAIL_LIMIT
    finally: workspace_lease.cleanup(staged.lease)


@pytest.mark.parametrize("output,secret", [
    ("password=x "*300, "password=x"),
    ("password=topsecret"+"z"*991, "topsecret"),
])
def test_generated_diagnostic_redacts_before_final_tail_bound(output, secret):
    result=pipeline.artifact_execution.sandboxed_package_runner.SandboxResult(
        "fail",1,"",output,None,sandbox_evidence.encode("fail"),"container",
    )
    detail=pipeline.artifact_execution._diagnostic_detail(result)
    diagnostic=json.loads(detail)["errors"][-1]
    tail=diagnostic.removeprefix(pipeline.artifact_execution.DIAGNOSTIC_PREFIX)
    assert secret not in diagnostic
    assert len(tail)<=pipeline.artifact_execution.DIAGNOSTIC_TAIL_LIMIT


def test_generated_diagnostic_prefers_stderr_and_leaves_pass_detail_unchanged():
    failed=pipeline.artifact_execution.sandboxed_package_runner.SandboxResult(
        "fail",1,"stdout marker","stderr marker",None,
        sandbox_evidence.encode("fail"),"container",
    )
    diagnostic=json.loads(
        pipeline.artifact_execution._diagnostic_detail(failed)
    )["errors"][-1]
    assert "stderr marker" in diagnostic and "stdout marker" not in diagnostic
    stdout_only=dataclasses.replace(failed,stderr="")
    assert "stdout marker" in pipeline.artifact_execution._diagnostic_detail(stdout_only)
    passed=dataclasses.replace(failed,status="pass",detail="unchanged")
    assert pipeline.artifact_execution._diagnostic_detail(passed)=="unchanged"
    empty=dataclasses.replace(failed,stdout="",stderr="",detail="empty")
    assert pipeline.artifact_execution._diagnostic_detail(empty)=="empty"


def test_synthesized_runtime_uses_exact_sandbox_output(tmp_path, monkeypatch):
    source = write_block(tmp_path / "source", "stale")
    built = write_block(tmp_path / "built", "fresh")
    staged = artifact_staging.stage_tree(source, tmp_path / "input")
    output = import_sandbox_output(built, tmp_path / "output")
    outcome = artifact_execution.ExecutionOutcome("pass", "passed", ("npm", "run", "build"), output)
    monkeypatch.setattr(pipeline.artifact_execution, "run_generated", lambda *_args: outcome)
    synthesized = None
    try:
        build = pipeline.build_block(staged, 5)
        proof = proof_for(build.output)
        synthesized = pipeline.synthesize_block_runtime(
            build.output, proof, tmp_path / "runtime"
        )
        marker = synthesized.staged.root / "acme-card" / "generated" / "blocks" / "card" / "build" / "marker.js"
        assert marker.read_text() == "fresh"
        assert synthesized.staged.role is artifact_staging.StageRole.SYNTHESIZED_RUNTIME
        assert synthesized.source_role is artifact_staging.StageRole.SANDBOX_OUTPUT
        assert synthesized.block_proof_origin is pipeline.BlockProofOrigin.BUILT_SANDBOX_OUTPUT
        assert synthesized.execution_proof is not None
        wrapper = synthesized.plugin_dir / "acme-card.php"
        assert "file_exists" not in wrapper.read_text()
        assert "generated/blocks/card/build/block.json" in wrapper.read_text()
    finally:
        if synthesized is not None: workspace_lease.cleanup(synthesized.staged.lease)
        workspace_lease.cleanup(output.lease)
        workspace_lease.cleanup(staged.lease)


@pytest.mark.parametrize("artifact_kind", ["block", "plugin"])
def test_held_exit_drift_prevents_synthesized_lease_creation(tmp_path, monkeypatch, artifact_kind):
    source = tmp_path / "source"
    if artifact_kind == "block":
        write_block(source, "fresh")
        changed = Path("blocks/card/build/marker.js")
    else:
        source.mkdir()
        (source / "plugin.php").write_text("<?php")
        changed = Path("plugin.php")
    staged = (
        import_sandbox_output(source, tmp_path / "input")
        if artifact_kind == "block"
        else artifact_staging.stage_tree(source, tmp_path / "input")
    )
    live_before = set(workspace_lease._LIVE_LEASES)
    if artifact_kind == "block":
        original_copy = pipeline.artifact_runtime_staging._copy_member

        def copy_then_drift(*args, **kwargs):
            copied = original_copy(*args, **kwargs)
            (staged.root / changed).write_text("drift")
            return copied

        monkeypatch.setattr(
            pipeline.artifact_runtime_staging, "_copy_member", copy_then_drift
        )
    else:
        original_snapshot = artifact_staging.snapshot_held_tree

        def snapshot_then_drift(held):
            snapshot = original_snapshot(held)
            (staged.root / changed).write_text("drift")
            return snapshot

        monkeypatch.setattr(
            artifact_staging, "snapshot_held_tree", snapshot_then_drift
        )
    runtime_parent = tmp_path / "runtime"
    try:
        with pytest.raises(
            (ValueError, pipeline.RuntimePreparationError),
            match="held staged tree changed|changed while streaming|source manifest mismatch",
        ):
            if artifact_kind == "block":
                pipeline.synthesize_block_runtime(
                    staged, proof_for(staged), runtime_parent
                )
            else:
                pipeline.synthesize_plugin_runtime(staged, "plugin", runtime_parent)
        assert set(workspace_lease._LIVE_LEASES) == live_before
        assert not runtime_parent.exists() or not any(runtime_parent.iterdir())
    finally:
        workspace_lease.cleanup(staged.lease)


def test_post_stage_constructor_failure_cleans_synthesized_lease(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir(); (source / "plugin.php").write_text("<?php")
    staged = artifact_staging.stage_tree(source, tmp_path / "input")
    created = []
    original_stage = artifact_staging._stage_synthesized_snapshot

    def capture_stage(*args, **kwargs):
        synthesized = original_stage(*args, **kwargs)
        created.append(synthesized)
        return synthesized

    monkeypatch.setattr(artifact_staging, "_stage_synthesized_snapshot", capture_stage)
    monkeypatch.setattr(pipeline, "SynthesizedRuntime", lambda *_args: (_ for _ in ()).throw(RuntimeError("constructor failed")))
    try:
        with pytest.raises(pipeline.RuntimePreparationError, match="constructor failed") as caught:
            pipeline.synthesize_plugin_runtime(staged, "plugin", tmp_path / "runtime")
        receipt = caught.value.receipts[0]
        assert receipt.component == "synthesized_runtime" and receipt.state == "removed"
        assert not created[0].root.exists()
        assert created[0].lease.lease_id not in workspace_lease._LIVE_LEASES
    finally:
        workspace_lease.cleanup(staged.lease)


def test_block_synthesis_rejects_stale_or_forged_proof_before_staging(tmp_path):
    first = write_block(tmp_path / "first", "one")
    second = write_block(tmp_path / "second", "two")
    first_output = import_sandbox_output(first, tmp_path / "first-output")
    second_output = import_sandbox_output(second, tmp_path / "second-output")
    proof = proof_for(first_output)
    runtime_parent = tmp_path / "runtime"
    try:
        with pytest.raises(ValueError, match="manifest"):
            pipeline.synthesize_block_runtime(second_output, proof, runtime_parent)
        forged = dataclasses.replace(proof, selected_block_json="other/block.json")
        with pytest.raises(ValueError, match="proof"):
            pipeline.synthesize_block_runtime(first_output, forged, runtime_parent)
        assert not runtime_parent.exists() or not any(runtime_parent.iterdir())
    finally:
        workspace_lease.cleanup(first_output.lease)
        workspace_lease.cleanup(second_output.lease)


def test_wrapper_literal_encoder_blocks_injection_and_preserves_exact_path(tmp_path):
    block_dir = tmp_path / "source" / "blocks" / "odd'?>${bait}"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        '{"name":"acme/odd","title":"Odd","category":"widgets","textdomain":"acme-odd"}'
    )
    output = import_sandbox_output(tmp_path / "source", tmp_path / "output")
    synthesized = None
    try:
        proof = proof_for(output)
        synthesized = pipeline.synthesize_block_runtime(
            output, proof, tmp_path / "runtime"
        )
        wrapper = (synthesized.plugin_dir / "acme-odd.php").read_text()
        assert "file_exists" not in wrapper
        assert "register_block_type( __DIR__ . '/generated/blocks/odd\\'?>${bait}/block.json' );" in wrapper
        assert "file_put_contents" not in wrapper
    finally:
        if synthesized is not None:
            workspace_lease.cleanup(synthesized.staged.lease)
        workspace_lease.cleanup(output.lease)


def test_php_single_quoted_literal_escapes_quote_and_backslash():
    assert pipeline._php_single_quoted_literal("/odd'\\path") == "'/odd\\'\\\\path'"


def test_wrapper_literal_rejects_control_character_path_bait(tmp_path):
    block_dir = tmp_path / "source" / "blocks" / "bad\nname"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        '{"name":"acme/bad","title":"Bad","category":"widgets"}'
    )
    output = import_sandbox_output(tmp_path / "source", tmp_path / "output")
    try:
        with pytest.raises(ValueError, match="control"):
            pipeline.synthesize_block_runtime(
                output, proof_for(output), tmp_path / "runtime"
            )
    finally:
        workspace_lease.cleanup(output.lease)


def test_source_fallback_registers_exact_source_block_json(tmp_path):
    source = tmp_path / "source" / "blocks" / "card"
    source.mkdir(parents=True)
    (source / "block.json").write_text(
        '{"name":"acme/card","title":"Card","category":"widgets","textdomain":"acme-card"}'
    )
    output = import_sandbox_output(tmp_path / "source", tmp_path / "output")
    synthesized = None
    try:
        proof = proof_for(output)
        synthesized = pipeline.synthesize_block_runtime(
            output, proof, tmp_path / "runtime"
        )
        wrapper = (synthesized.plugin_dir / "acme-card.php").read_text()
        assert proof.selection_reason == "source_block_json"
        assert "'/generated/blocks/card/block.json'" in wrapper
        assert "/build/block.json" not in wrapper
    finally:
        if synthesized is not None:
            workspace_lease.cleanup(synthesized.staged.lease)
        workspace_lease.cleanup(output.lease)


def test_prepare_generated_runtime_accepts_authentic_source_only_caller_input(tmp_path):
    block = tmp_path / "source" / "blocks" / "card"
    block.mkdir(parents=True)
    (block / "block.json").write_text(
        '{"name":"acme/card","title":"Card","category":"widgets","textdomain":"acme-card"}'
    )
    (block / "render.php").write_text("<?php return '<p>Card</p>';", encoding="utf-8")
    staged = artifact_staging.stage_tree(tmp_path / "source", tmp_path / "input")
    prepared = None
    try:
        prepared = runtime_smoke._prepare_generated_runtime(
            staged, "block", tmp_path / "source", False, False, False, 5,
            tmp_path / "runtime", tmp_path / "temporary",
        )
        assert prepared.synthesized is not None
        assert prepared.sandbox_output is None
        assert prepared.block_runtime_artifact_gate is None
        assert prepared.synthesized.source_role is artifact_staging.StageRole.CALLER_INPUT
        assert (
            prepared.synthesized.block_proof_origin
            is pipeline.BlockProofOrigin.SOURCE_ONLY_CALLER_INPUT
        )
        wrapper = prepared.synthesized.plugin_dir / "acme-card.php"
        assert "'/generated/blocks/card/block.json'" in wrapper.read_text()
    finally:
        if prepared is not None and prepared.synthesized is not None:
            workspace_lease.cleanup(prepared.synthesized.staged.lease)
        workspace_lease.cleanup(staged.lease)


def test_caller_input_cannot_claim_built_or_partial_source_proof(tmp_path):
    built_source = write_block(tmp_path / "built-source", "fresh")
    built_input = artifact_staging.stage_tree(built_source, tmp_path / "built-input")
    partial_source = tmp_path / "partial-source" / "blocks" / "card"
    partial_source.mkdir(parents=True)
    (partial_source / "block.json").write_text(
        '{"name":"acme/card","title":"Card","category":"widgets"}'
    )
    (partial_source / "extra.js").write_text("extra")
    partial_input = artifact_staging.stage_tree(
        tmp_path / "partial-source", tmp_path / "partial-input"
    )
    try:
        with pytest.raises(ValueError, match="source-only proof"):
            pipeline.synthesize_block_runtime(
                built_input, proof_for(built_input), tmp_path / "built-runtime"
            )
        with pytest.raises(ValueError, match="source-only proof"):
            pipeline.synthesize_block_runtime(
                partial_input, proof_for(partial_input), tmp_path / "partial-runtime"
            )
    finally:
        workspace_lease.cleanup(built_input.lease)
        workspace_lease.cleanup(partial_input.lease)


def test_synthesis_streams_only_the_explicit_runtime_closure(
    tmp_path, monkeypatch
):
    root = write_block(tmp_path / "source", "fresh")
    source_json = root / "blocks/card/block.json"
    build_json = root / "blocks/card/build/block.json"
    source_json.write_text(
        '{"name":"acme/source","title":"Source","category":"widgets","textdomain":"source"}'
    )
    build_json.write_text(
        '{"name":"acme/built","title":"Built","category":"widgets","textdomain":"built"}'
    )
    (root / "blocks/card/source-note.txt").write_text("must not enter runtime")
    output = import_sandbox_output(root, tmp_path / "output")
    proof = proof_for(output)
    synthesized = None
    monkeypatch.setattr(
        artifact_staging,
        "snapshot_held_tree",
        lambda _held: (_ for _ in ()).throw(AssertionError("snapshot forbidden")),
    )
    try:
        synthesized = pipeline.synthesize_block_runtime(
            output, proof, tmp_path / "runtime"
        )
        assert synthesized.plugin_slug == "built"
        assert synthesized.block_name == "acme/built"
        generated = synthesized.plugin_dir / "generated"
        assert (generated / "blocks/card/build/marker.js").read_text() == "fresh"
        assert not (generated / "blocks/card/source-note.txt").exists()
    finally:
        if synthesized is not None:
            workspace_lease.cleanup(synthesized.staged.lease)
        workspace_lease.cleanup(output.lease)


def test_plugin_synthesis_has_no_block_execution_proof(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "plugin.php").write_text("<?php")
    staged = artifact_staging.stage_tree(source, tmp_path / "input")
    synthesized = None
    try:
        synthesized = pipeline.synthesize_plugin_runtime(
            staged, "plugin", tmp_path / "runtime"
        )
        assert synthesized.execution_proof is None
    finally:
        if synthesized is not None:
            workspace_lease.cleanup(synthesized.staged.lease)
        workspace_lease.cleanup(staged.lease)


def test_synthesized_php_closure_drift_fails_and_cleans_stage(tmp_path, monkeypatch):
    source = write_block(tmp_path / "source", "fresh")
    output = import_sandbox_output(source, tmp_path / "output")
    proof = proof_for(output)
    original = pipeline._block_extras

    def inject(*args, **kwargs):
        extras, wrapper_path, wrapper_bytes = original(*args, **kwargs)
        extras += (
            pipeline.artifact_runtime_staging.ExtraFile(
                "acme-card/extra.txt", b"<?php echo 'drift';"
            ),
        )
        return extras, wrapper_path, wrapper_bytes

    monkeypatch.setattr(pipeline, "_block_extras", inject)
    try:
        with pytest.raises(pipeline.RuntimePreparationError, match="closure") as caught:
            pipeline.synthesize_block_runtime(output, proof, tmp_path / "runtime")
        assert caught.value.receipts[0].state == "removed"
    finally:
        workspace_lease.cleanup(output.lease)


def test_runtime_digest_changes_with_wrapper_bytes(tmp_path, monkeypatch):
    source = write_block(tmp_path / "source", "fresh")
    output = import_sandbox_output(source, tmp_path / "output")
    proof = proof_for(output)
    first = second = None
    try:
        first = pipeline.synthesize_block_runtime(output, proof, tmp_path / "runtime-a")
        original = pipeline._block_wrapper
        monkeypatch.setattr(
            pipeline, "_block_wrapper",
            lambda textdomain, selected: original(textdomain + "-changed", selected),
        )
        second = pipeline.synthesize_block_runtime(output, proof, tmp_path / "runtime-b")
        assert first.execution_proof.wrapper_sha256 != second.execution_proof.wrapper_sha256
        assert first.execution_proof.execution_proof_digest != second.execution_proof.execution_proof_digest
    finally:
        if first is not None: workspace_lease.cleanup(first.staged.lease)
        if second is not None: workspace_lease.cleanup(second.staged.lease)
        workspace_lease.cleanup(output.lease)


def test_wrapper_verification_rejects_extra_bootstrap_and_cleans(tmp_path, monkeypatch):
    source = write_block(tmp_path / "source", "fresh")
    output = import_sandbox_output(source, tmp_path / "output")
    proof = proof_for(output)
    original = pipeline._block_wrapper
    monkeypatch.setattr(
        pipeline,
        "_block_wrapper",
        lambda *args: original(*args) + b"\nregister_block_type( 'other' );\n",
    )
    try:
        with pytest.raises(
            pipeline.RuntimePreparationError, match="exact registration bootstrap"
        ) as caught:
            pipeline.synthesize_block_runtime(
                output, proof, tmp_path / "runtime"
            )
        assert caught.value.receipts[0].state == "removed"
    finally:
        workspace_lease.cleanup(output.lease)


def test_internal_synthesized_stage_dual_failure_preserves_primary_and_receipt(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir(); (source / "plugin.php").write_text("<?php")
    staged = artifact_staging.stage_tree(source, tmp_path / "input")
    original_cleanup = pipeline.workspace_lease.cleanup
    monkeypatch.setattr(artifact_staging, "_manifest_from_fd", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synth verification failed")))
    monkeypatch.setattr(pipeline.workspace_lease, "cleanup", lambda _lease: (_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("cleanup failed")))
    retained = None
    try:
        with pytest.raises(pipeline.RuntimePreparationError, match="synth verification failed") as caught:
            pipeline.synthesize_plugin_runtime(staged, "plugin", tmp_path / "runtime")
        error = caught.value; receipt = error.receipts[0]
        assert isinstance(error.primary, RuntimeError) and str(error.primary) == "synth verification failed"
        assert receipt.component == "synthesized_runtime" and receipt.state == "retained"
        assert receipt.exists and receipt.live and receipt.error
        assert receipt.recovery_path and Path(receipt.recovery_path).exists()
        retained = next(
            lease for lease in workspace_lease._LIVE_LEASES.values()
            if lease.root / "artifact" == Path(receipt.resource_path)
        )
    finally:
        monkeypatch.setattr(pipeline.workspace_lease, "cleanup", original_cleanup)
        if retained is not None and retained.lease_id in workspace_lease._LIVE_LEASES:
            original_cleanup(retained)
        original_cleanup(staged.lease)


def test_post_stage_constructor_and_cleanup_failure_preserve_retained_evidence(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir(); (source / "plugin.php").write_text("<?php")
    staged = artifact_staging.stage_tree(source, tmp_path / "input")
    created = []
    original_stage = artifact_staging._stage_synthesized_snapshot
    original_cleanup = pipeline.workspace_lease.cleanup

    def capture_stage(*args, **kwargs):
        synthesized = original_stage(*args, **kwargs)
        created.append(synthesized)
        return synthesized

    monkeypatch.setattr(artifact_staging, "_stage_synthesized_snapshot", capture_stage)
    monkeypatch.setattr(pipeline, "SynthesizedRuntime", lambda *_args: (_ for _ in ()).throw(RuntimeError("constructor failed")))
    monkeypatch.setattr(pipeline.workspace_lease, "cleanup", lambda _lease: (_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("cleanup failed")))
    try:
        with pytest.raises(pipeline.RuntimePreparationError, match="constructor failed") as caught:
            pipeline.synthesize_plugin_runtime(staged, "plugin", tmp_path / "runtime")
        receipt = caught.value.receipts[0]
        assert receipt.state == "retained" and receipt.error
        assert receipt.recovery_path == str(created[0].root) and created[0].root.exists()
        assert created[0].lease.lease_id in workspace_lease._LIVE_LEASES
    finally:
        monkeypatch.setattr(pipeline.workspace_lease, "cleanup", original_cleanup)
        for owned in created:
            if owned.lease.lease_id in workspace_lease._LIVE_LEASES:
                original_cleanup(owned.lease)
        original_cleanup(staged.lease)


def test_cleanup_receipt_distinguishes_before_and_after_removal(tmp_path, monkeypatch):
    first_source = tmp_path / "first"; first_source.mkdir(); (first_source / "a").write_text("a")
    second_source = tmp_path / "second"; second_source.mkdir(); (second_source / "b").write_text("b")
    first = artifact_staging.stage_tree(first_source, tmp_path / "leases-a")
    second = artifact_staging.stage_tree(second_source, tmp_path / "leases-b")
    original = workspace_lease.cleanup
    try:
        monkeypatch.setattr(pipeline.workspace_lease, "cleanup", lambda _lease: (_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("before")))
        retained = pipeline.cleanup_component("sandbox_output", first)
        assert retained.state == "retained" and retained.exists and retained.live
        def after(lease):
            original(lease)
            raise workspace_lease.WorkspaceCleanupError("after")
        monkeypatch.setattr(pipeline.workspace_lease, "cleanup", after)
        removed = pipeline.cleanup_component("sandbox_output", second)
        assert removed.state == "removed" and not removed.exists and not removed.live
    finally:
        monkeypatch.setattr(pipeline.workspace_lease, "cleanup", original)
        if first.lease.lease_id in workspace_lease._LIVE_LEASES: original(first.lease)
        if second.lease.lease_id in workspace_lease._LIVE_LEASES: original(second.lease)


def test_retention_summary_preserves_retained_then_removed_same_component(tmp_path):
    first_source=tmp_path/"first"; first_source.mkdir(); (first_source/"a").write_text("a")
    second_source=tmp_path/"second"; second_source.mkdir(); (second_source/"b").write_text("b")
    first=artifact_staging.stage_tree(first_source,tmp_path/"leases-a")
    second=artifact_staging.stage_tree(second_source,tmp_path/"leases-b")
    try:
        retained=pipeline.observe_component("sandbox_output",first)
        removed=pipeline.cleanup_component("sandbox_output",second)
        summary=pipeline.retention_summary([retained,removed])
        component=summary["components"]["sandbox_output"]
        assert summary["retained"] is True and component["state"]=="retained"
        assert component["recovery_path"]==str(first.root)
        assert [item["state"] for item in component["resources"]]==["retained","removed"]
        assert len(summary["resources"])==2
    finally:
        if first.lease.lease_id in workspace_lease._LIVE_LEASES: workspace_lease.cleanup(first.lease)
