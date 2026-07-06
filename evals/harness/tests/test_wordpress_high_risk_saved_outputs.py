"""Tests for the high-risk WordPress saved-output runner."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import run_wordpress_high_risk_saved_outputs as runner


def test_parse_csv_trims_empty_items():
    assert runner.parse_csv(" skill, baseline-zero-shot, ,baseline-few-shot ") == [
        "skill",
        "baseline-zero-shot",
        "baseline-few-shot",
    ]


def test_fixture_ids_for_suite_uses_eval_config():
    fixtures = runner.fixture_ids_for_suite("wordpress-security-critic")

    assert {
        "rest-ajax-authorization-v1",
        "input-sql-output-handling-v1",
        "upload-filesystem-boundary-v1",
        "security-gate-consumption-v1",
    } <= set(fixtures)


def test_validate_contract_writes_result(tmp_path):
    output = tmp_path / "output.md"
    contract = tmp_path / "contract.json"
    output.write_text(
        """\
**VERDICT: REVISE**

**Overall Assessment**
The custom REST route has a reachable authorization gap.

**Pre-commitment Predictions**
Expected a missing route capability boundary.

**Security Gate Evidence**
No security-gate.json sidecar was supplied; this is critic-derived review only.

**Critical Findings**
None.

**Major Findings**
`register_rest_route()` lacks a `permission_callback` that calls `current_user_can()`.

**Minor Findings**
None.

**Suppression Review**
No suppressed_annotations[] sidecar evidence was supplied.

**What's Missing**
This does not prove runtime exploitability.

**Multi-Perspective Notes**
Security and operations both need a capability-backed route test.

**Exploitability Notes**
A logged-in subscriber can trigger the mutation path.

**Verdict Justification**
REVISE until the route has an authorization boundary.

**Remediation Guide**
Add `permission_callback`, cover it with PHPUnit, and run Plugin Check.

**Open Questions**
Unknown: which custom capability should own the route.
""",
        encoding="utf-8",
    )

    result = runner.validate_contract("wordpress-security-critic", output, contract)

    assert result["pass"] is True
    assert json.loads(contract.read_text(encoding="utf-8"))["pass"] is True


def test_validate_contract_threads_security_gate_sidecar(tmp_path):
    output = tmp_path / "output.md"
    contract = tmp_path / "contract.json"
    gate = tmp_path / "security-gate.json"
    output.write_text(
        """\
**VERDICT: REVISE**

**Overall Assessment**
The artifact fails the supplied security gate.

**Pre-commitment Predictions**
Expected escaped-output evidence from the gate.

**Security Gate Evidence**
Gate-derived evidence from `security-gate.json` reports status `fail`.
`phpcs-suppression-diff` / `--ignore-annotations` found advisory
`WordPress.DB.DirectDatabaseQuery.DirectQuery` at `plugin.php:11`; enforced
`WordPress.Security.EscapeOutput.OutputNotEscaped` is at `plugin.php:12`.

**Critical Findings**
None until reachability is proven.

**Major Findings**
The rendered value needs `esc_html()` and the action still needs `current_user_can()`.

**Minor Findings**
None.

**Suppression Review**
No suppressed_annotations[] sidecar evidence was supplied.

**What's Missing**
The gate's negative space does not prove authorization correctness.

**Multi-Perspective Notes**
Security and operations treat the sidecar as deterministic evidence.

**Exploitability Notes**
No CRITICAL finding without a caller path.

**Verdict Justification**
REVISE until the gate is clean and reachability is reviewed.

**Remediation Guide**
Use `esc_html()`, keep any SQL remediation on `$wpdb->prepare()`, rerun
PHPCS/WPCS, and rerun the security gate.

**Open Questions**
Unknown: which capability should own the action.
""",
        encoding="utf-8",
    )
    gate.write_text(
        json.dumps(
            {
                "schema": "wordpress-security-gate",
                "schema_version": 1,
                "status": "fail",
                "tools": [{"id": "phpcs-suppression-diff"}],
                "findings": [
                    {
                        "rule_id": "WordPress.Security.EscapeOutput.OutputNotEscaped",
                        "file": "plugin.php",
                        "line": 12,
                        "enforced": True,
                    },
                    {
                        "rule_id": "WordPress.DB.DirectDatabaseQuery.DirectQuery",
                        "file": "plugin.php",
                        "line": 11,
                        "enforced": False,
                    },
                ],
                "suppressed_annotations": [],
                "negative_space": ["No authorization reasoning."],
            }
        ),
        encoding="utf-8",
    )

    result = runner.validate_contract("wordpress-security-critic", output, contract, security_gate_path=gate)
    archived = json.loads(contract.read_text(encoding="utf-8"))

    assert result["pass"] is True
    assert archived["security_gate_path"].endswith("security-gate.json")


def test_run_saved_output_reuses_existing_output(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULTS_ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "invoke_or_reuse",
        lambda **kwargs: None,
    )

    output = runner.saved_output_path("run-1", "wordpress-security-critic", "skill", "fixture-a")
    metadata = runner.saved_metadata_path("run-1", "wordpress-security-critic", "skill", "fixture-a")
    output.parent.mkdir(parents=True)
    output.write_text("saved output", encoding="utf-8")
    metadata.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "validate_contract",
        lambda skill_name, output_path, contract_path, security_gate_path=None: {
            "pass": False,
            "score": 0.5,
            "skill": skill_name,
        },
    )

    entry = runner.run_saved_output(
        run_id="run-1",
        suite="wordpress-security-critic",
        fixture_id="fixture-a",
        condition="skill",
        skill_name="wordpress-security-critic",
        resume=True,
        timeout_sec=1,
        max_retries=1,
        model=None,
        effort=None,
    )

    assert entry.generation_ok is True
    assert entry.contract_pass is False
    assert entry.contract_score == 0.5


def test_run_saved_output_passes_fixture_security_gate_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULTS_ROOT", tmp_path)
    sidecar = tmp_path / "fixtures" / "security-gate.json"
    sidecar.parent.mkdir()
    sidecar.write_text("{}", encoding="utf-8")
    seen: dict[str, Path | None] = {}

    monkeypatch.setattr(runner, "invoke_or_reuse", lambda **kwargs: None)
    monkeypatch.setattr(runner, "security_gate_sidecar_path", lambda suite, fixture_id: sidecar)

    output = runner.saved_output_path("run-1", "wordpress-security-critic", "skill", "fixture-a")
    metadata = runner.saved_metadata_path("run-1", "wordpress-security-critic", "skill", "fixture-a")
    output.parent.mkdir(parents=True)
    output.write_text("saved output", encoding="utf-8")
    metadata.write_text("{}", encoding="utf-8")

    def fake_validate(skill_name, output_path, contract_path, security_gate_path=None):
        seen["security_gate_path"] = security_gate_path
        return {"pass": True, "score": 1.0, "skill": skill_name}

    monkeypatch.setattr(runner, "validate_contract", fake_validate)

    entry = runner.run_saved_output(
        run_id="run-1",
        suite="wordpress-security-critic",
        fixture_id="fixture-a",
        condition="skill",
        skill_name="wordpress-security-critic",
        resume=True,
        timeout_sec=1,
        max_retries=1,
        model=None,
        effort=None,
    )

    assert seen["security_gate_path"] == sidecar
    assert entry.security_gate_path == str(sidecar)
    assert entry.contract_pass is True


def test_run_saved_output_records_invocation_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULTS_ROOT", tmp_path)

    result = SimpleNamespace(ok=False, total_duration_sec=1.2, error="model failed")
    monkeypatch.setattr(runner, "invoke_or_reuse", lambda **kwargs: result)
    monkeypatch.setattr(
        runner,
        "validate_contract",
        lambda skill_name, output_path, contract_path, security_gate_path=None: {
            "pass": False,
            "score": 0.0,
            "skill": skill_name,
        },
    )

    entry = runner.run_saved_output(
        run_id="run-1",
        suite="wordpress-security-critic",
        fixture_id="fixture-a",
        condition="baseline-zero-shot",
        skill_name="wordpress-security-critic",
        resume=False,
        timeout_sec=1,
        max_retries=1,
        model=None,
        effort=None,
    )

    assert entry.generation_ok is False
    assert entry.error == "model failed"
    assert entry.duration_sec == 1.2


def test_summarize_preserves_evidence_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULTS_ROOT", tmp_path)
    entries = [
        runner.SavedOutputEntry(
            suite="wordpress-security-critic",
            fixture_id="fixture-a",
            condition="skill",
            output_path="out.md",
            metadata_path="meta.json",
            contract_path="contract.json",
            security_gate_path=None,
            generation_ok=True,
            contract_pass=True,
            contract_score=1.0,
            duration_sec=2.0,
        ),
        runner.SavedOutputEntry(
            suite="wordpress-security-critic",
            fixture_id="fixture-a",
            condition="baseline-zero-shot",
            output_path="out.md",
            metadata_path="meta.json",
            contract_path="contract.json",
            security_gate_path=None,
            generation_ok=True,
            contract_pass=False,
            contract_score=0.4,
            duration_sec=2.0,
        ),
        runner.SavedOutputEntry(
            suite="wordpress-security-critic",
            fixture_id="smoke-wordpress-v1",
            condition="skill",
            output_path="out.md",
            metadata_path="meta.json",
            contract_path="contract.json",
            security_gate_path=None,
            generation_ok=True,
            contract_pass=False,
            contract_score=0.2,
            duration_sec=2.0,
        ),
    ]

    summary = runner.summarize(
        "run-1",
        "wordpress-security-critic",
        "wordpress-security-critic",
        entries,
    )

    assert summary["generation_ok_count"] == 3
    assert summary["contract_pass_count"] == 1
    assert summary["all_contracts_pass"] is False
    assert summary["focused_fixture_summary"]["skill_contract_pass_count"] == 1
    assert summary["focused_fixture_summary"]["skill_entry_count"] == 1
    assert summary["focused_fixture_summary"]["all_focused_skill_contracts_pass"] is True
    assert "not answer-key scoring" in summary["evidence_boundary"]
