"""Bounded post-build gate over the authenticated block execution proof."""
from __future__ import annotations

import copy
import dataclasses
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_execution_gate as gate
import artifact_execution_graph as graph
import artifact_layout
import artifact_staging


def _tar(files: dict[str, bytes]) -> io.BytesIO:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    stream.seek(0)
    return stream


def _metadata(**overrides) -> bytes:
    value = {"name": "test/card", "title": "Card", "category": "widgets", **overrides}
    return json.dumps(value, separators=(",", ":")).encode()


def _files() -> dict[str, bytes]:
    return {
        "blocks/card/block.json": _metadata(),
        "blocks/card/build/block.json": _metadata(render="file:./render.php"),
        "blocks/card/build/render.php": b"<?php echo 'built';",
        "blocks/card/outside.inc": b"<?php return [];",
        "blocks/card/payload.txt": b"prefix <?php echo 'text';",
    }


def _source_layout():
    content = _metadata()
    manifest = (
        artifact_staging.ManifestEntry(
            "blocks/card/block.json", "regular", len(content), graph.sha256_bytes(content)
        ),
    )
    return artifact_layout.select_source_layout(manifest)


def _output(tmp_path: Path, files: dict[str, bytes] | None = None):
    return artifact_staging.import_tar_stream(_tar(files or _files()), tmp_path / "output")


def _stub_external(
    monkeypatch, *, syntax_failure: str | bool | None = None,
    mutate_api: bool = False,
):
    calls = {"php": [], "api": [], "security": []}
    monkeypatch.setattr(gate.shutil, "which", lambda name: "/usr/bin/php" if name == "php" else None)

    def run(command, **_kwargs):
        calls["php"].append(tuple(command))
        failed = syntax_failure is True or (
            isinstance(syntax_failure, str)
            and str(command[-1]).endswith(syntax_failure)
        )
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="syntax error" if failed else "")

    def api(_root, **kwargs):
        selected = list(kwargs["explicit_files"])
        calls["api"].append(selected)
        if mutate_api:
            selected[-1].write_bytes(b"<?php changed();")
        return {"status": "pass"}

    def security(_root, **kwargs):
        calls["security"].append(list(kwargs["explicit_files"]))
        return {"status": "pass"}

    monkeypatch.setattr(gate, "run_bounded", run)
    monkeypatch.setattr(gate.wp_api_lint, "run_api_lint", api)
    monkeypatch.setattr(gate.wp_api_lint, "summarize_report", lambda _report: "API pass")
    monkeypatch.setattr(gate.wp_security_gate, "run_security_gate", security)
    monkeypatch.setattr(gate.wp_security_gate, "summarize_report", lambda _report: "security pass")
    return calls


def _relative_calls(paths, root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]


def test_one_handoff_and_exact_lists_cover_all_php_candidates(tmp_path, monkeypatch):
    calls = _stub_external(monkeypatch)
    handoffs = []
    held_roles = []
    original = gate.artifact_staging.stage_scan_handoff
    original_hold = gate.artifact_staging.hold_staged_tree

    def stage(held, parent=None, members=None):
        handoffs.append(tuple(members))
        return original(held, parent, members)

    def hold(staged, **kwargs):
        held_roles.append(staged.role)
        return original_hold(staged, **kwargs)

    monkeypatch.setattr(gate.artifact_staging, "stage_scan_handoff", stage)
    monkeypatch.setattr(gate.artifact_staging, "hold_staged_tree", hold)
    output = _output(tmp_path)
    try:
        validation = gate.validate_block_execution_artifact(
            output, _source_layout(), 30, parent=tmp_path / "handoff"
        )
    finally:
        artifact_staging.cleanup_staged_tree(output)

    proof = validation.proof
    receipt = validation.staging_receipts[0]
    expected_all = tuple(item.path for item in proof.scan_files)
    expected_php = [item.path for item in proof.scan_files if "wp_api" in item.scan_ids]
    assert validation.gate["status"] == "pass"
    assert handoffs == [expected_all]
    assert held_roles.count(artifact_staging.StageRole.SANDBOX_OUTPUT) == 1
    assert len(calls["api"]) == len(calls["security"]) == 1
    assert _relative_calls(calls["api"][0], receipt.root) == expected_php
    assert _relative_calls(calls["security"][0], receipt.root) == expected_php
    assert [Path(command[-1]).relative_to(receipt.root).as_posix() for command in calls["php"]] == expected_php
    assert {"blocks/card/outside.inc", "blocks/card/payload.txt"} <= set(expected_php)
    assert receipt.state == "removed" and not receipt.root.exists()
    assert validation.gate["selected_root"] == "blocks/card/build"
    assert validation.gate["selection_reason"] == "built_block_json"
    assert validation.gate["edges"] == [dataclasses.asdict(item) for item in proof.edges]
    assert validation.gate["files"] == [dataclasses.asdict(item) for item in proof.files]
    assert validation.gate["scan_files"] == [dataclasses.asdict(item) for item in proof.scan_files]
    assert validation.gate["component_digests"]["artifact"] == proof.artifact_proof_digest
    with pytest.raises(dataclasses.FrozenInstanceError):
        validation.proof = None


def test_bad_built_php_fails_artifact_without_rewriting_build_result(tmp_path, monkeypatch):
    calls = _stub_external(monkeypatch, syntax_failure="blocks/card/build/render.php")
    output = _output(tmp_path)
    build_gate = {"status": "pass", "detail": "npm build completed"}
    try:
        validation = gate.validate_block_execution_artifact(output, _source_layout(), 30)
    finally:
        artifact_staging.cleanup_staged_tree(output)

    checks = {item["id"]: item for item in validation.gate["checks"]}
    assert validation.gate["status"] == "fail"
    assert checks["php_syntax"]["status"] == "fail"
    assert len(calls["php"]) == len(validation.proof.php_candidates)
    assert build_gate == {"status": "pass", "detail": "npm build completed"}
    assert "block_build_gate" not in validation.gate


def test_php_syntax_stops_after_the_reported_failure_cap(tmp_path, monkeypatch):
    calls = _stub_external(monkeypatch, syntax_failure=True)
    files = _files()
    for index in range(gate.MAX_REPORTED_HITS + 4):
        files[f"blocks/card/build/failure-{index}.php"] = b"<?php broken("
    output = _output(tmp_path, files)
    try:
        validation = gate.validate_block_execution_artifact(
            output, _source_layout(), 30
        )
    finally:
        artifact_staging.cleanup_staged_tree(output)

    assert validation.gate["status"] == "fail"
    assert len(calls["php"]) == gate.MAX_REPORTED_HITS
    assert calls["api"] and calls["security"]


@pytest.mark.parametrize(
    "payload,check_id",
    [
        (b"<?php " + b"api_" + b"key = '" + b"x" * 16 + b"';", "hardcoded_secrets"),
        (b"<?php shell_exec('" + b"rm " + b"-rf /tmp/example');", "unsafe_commands"),
    ],
)
def test_bounded_text_scan_fails_secret_and_destructive_bait(
    tmp_path, monkeypatch, payload, check_id
):
    _stub_external(monkeypatch)
    files = _files()
    files["blocks/card/payload.txt"] = payload
    output = _output(tmp_path, files)
    try:
        validation = gate.validate_block_execution_artifact(output, _source_layout(), 30)
    finally:
        artifact_staging.cleanup_staged_tree(output)

    checks = {item["id"]: item for item in validation.gate["checks"]}
    assert validation.gate["status"] == "fail"
    assert checks[check_id]["status"] == "fail"
    assert checks["metadata_json"]["status"] == "pass"
    assert checks["structural"]["status"] == "pass"


def test_missing_required_built_metadata_fails_before_scanners(tmp_path, monkeypatch):
    calls = _stub_external(monkeypatch)
    files = _files()
    files["blocks/card/build/block.json"] = b'{"name":"test/card"}'
    output = _output(tmp_path, files)
    try:
        validation = gate.validate_block_execution_artifact(
            output, _source_layout(), 30
        )
    finally:
        artifact_staging.cleanup_staged_tree(output)

    checks = {item["id"]: item for item in validation.gate["checks"]}
    assert validation.gate["status"] == "fail"
    assert checks["execution_graph"]["status"] == "fail"
    assert "title, category" in checks["execution_graph"]["detail"]
    assert calls == {"php": [], "api": [], "security": []}


def test_static_block_without_php_candidates_passes_with_explicit_skips(tmp_path):
    metadata = _metadata(editorScript="file:./index.js")
    files = {
        "blocks/card/block.json": _metadata(),
        "blocks/card/build/block.json": metadata,
        "blocks/card/build/index.js": b"export const card = true;",
    }
    output = _output(tmp_path, files)
    try:
        validation = gate.validate_block_execution_artifact(
            output, _source_layout(), 30
        )
    finally:
        artifact_staging.cleanup_staged_tree(output)

    checks = {item["id"]: item for item in validation.gate["checks"]}
    assert validation.gate["status"] == "pass"
    assert checks["wp_api"]["status"] == "pass"
    assert checks["wp_security"]["status"] == "pass"
    assert validation.gate["scanner_aliases"] == []


def test_gate_persists_bound_alias_mapping_and_scanner_evidence(tmp_path, monkeypatch):
    _stub_external(monkeypatch)
    output = _output(tmp_path)
    try:
        validation = gate.validate_block_execution_artifact(
            output, _source_layout(), 30
        )
    finally:
        artifact_staging.cleanup_staged_tree(output)

    aliases = list(graph.scanner_aliases(validation.proof))
    assert validation.gate["scanner_aliases"] == aliases
    assert validation.gate["component_digests"]["scanner_aliases"] == (
        graph.scanner_alias_digest(validation.proof)
    )
    assert set(validation.gate["scanner_evidence"]) == {"wp_api", "wp_security"}


def test_security_runtime_evidence_prioritizes_enforced_and_suppressed_items():
    findings = [
        {"rule_id": f"advisory-{index}", "enforced": False}
        for index in range(gate.MAX_REPORTED_HITS + 2)
    ] + [{"rule_id": "enforced", "enforced": True}]
    suppressed = [
        {"suppressed_rules": [f"advisory-{index}"], "security_relevant": False}
        for index in range(gate.MAX_REPORTED_HITS + 2)
    ] + [{"suppressed_rules": ["security"], "security_relevant": True}]

    evidence = gate._security_runtime_evidence({
        "status": "fail", "findings": findings,
        "suppressed_annotations": suppressed,
    })

    assert evidence["finding_count"] == len(findings)
    assert evidence["suppressed_annotation_count"] == len(suppressed)
    assert evidence["findings"][0]["rule_id"] == "enforced"
    assert evidence["suppressed_annotations"][0]["suppressed_rules"] == ["security"]


def test_text_bound_blocks_before_any_external_scanner(tmp_path, monkeypatch):
    calls = _stub_external(monkeypatch)
    handoffs = []
    monkeypatch.setattr(
        gate.artifact_staging,
        "stage_scan_handoff",
        lambda *args, **kwargs: handoffs.append((args, kwargs)),
    )
    monkeypatch.setattr(gate, "MAX_TEXT_SCAN_BYTES", 1)
    output = _output(tmp_path)
    try:
        validation = gate.validate_block_execution_artifact(
            output, _source_layout(), 30
        )
    finally:
        artifact_staging.cleanup_staged_tree(output)

    assert validation.gate["status"] == "blocked"
    assert calls == {"php": [], "api": [], "security": []}
    assert handoffs == []


def test_mutation_between_scanner_and_reproof_blocks_and_cleans(tmp_path, monkeypatch):
    calls = _stub_external(monkeypatch, mutate_api=True)
    output = _output(tmp_path)
    try:
        validation = gate.validate_block_execution_artifact(output, _source_layout(), 30)
    finally:
        artifact_staging.cleanup_staged_tree(output)

    assert validation.gate["status"] == "blocked"
    assert len(calls["api"]) == 1
    assert calls["security"] == []
    assert len(validation.staging_receipts) == 1
    assert validation.staging_receipts[0].state == "removed"
    assert not validation.staging_receipts[0].root.exists()


def test_bind_runtime_gate_copies_and_checks_artifact_digest(tmp_path, monkeypatch):
    _stub_external(monkeypatch)
    output = _output(tmp_path)
    try:
        validation = gate.validate_block_execution_artifact(output, _source_layout(), 30)
    finally:
        artifact_staging.cleanup_staged_tree(output)
    wrapper = graph.block_runtime_wrapper.build(
        "test-card", validation.proof.selected_block_json
    )
    wrapper_validation = graph.build_wrapper_validation(
        wrapper, validation.proof.selected_block_json, php_syntax_passed=True
    )
    runtime = graph.bind_runtime_proof(
        validation.proof, "plugin/block-wrapper.php", wrapper, "a" * 64,
        wrapper_validation,
    )
    before = copy.deepcopy(validation.gate)

    bound = gate.bind_runtime_gate(validation, runtime)

    assert bound is not validation.gate
    assert validation.gate == before
    assert bound["artifact_proof_digest"] == validation.proof.artifact_proof_digest
    assert bound["wrapper_sha256"] == runtime.wrapper_sha256
    assert bound["wrapper_validation_digest"] == runtime.wrapper_validation_digest
    assert bound["wrapper_checks"] == [
        {"id": "bootstrap_exact", "status": "pass"},
        {"id": "php_syntax", "status": "pass"},
    ]
    assert bound["synthesized_manifest_sha256"] == runtime.synthesized_manifest_sha256
    assert bound["execution_proof_digest"] == runtime.execution_proof_digest
    forged = dataclasses.replace(
        runtime,
        artifact=dataclasses.replace(runtime.artifact, artifact_proof_digest="0" * 64),
    )
    with pytest.raises(ValueError, match="digest"):
        gate.bind_runtime_gate(validation, forged)
