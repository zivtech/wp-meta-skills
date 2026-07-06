"""Tests for the WordPress security gate — static profile (phase 1).

Unit tests run against recorded phpcs `--report=json` output and are hermetic.
Tests marked `real_security_gate` run the pinned phpcs/WPCS toolchain end-to-end
and skip (with the blocking reason) when `evals/harness/php-tools` has not been
composer-installed with WPCS; CI installs the toolchain so they run there.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import certify_wordpress_executor_artifact as certifier
import validate_wordpress_artifact as oracle
import wp_security_gate


HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wp_security_gate"

TOOLCHAIN, TOOLCHAIN_ERROR = wp_security_gate.resolve_toolchain()
needs_toolchain = pytest.mark.skipif(TOOLCHAIN is None, reason=f"pinned phpcs/WPCS toolchain unavailable: {TOOLCHAIN_ERROR}")


def oracle_args():
    return SimpleNamespace(
        profile="static",
        require_tool=[],
        timeout_sec=120,
        wp_root=None,
        wp_env_root=None,
        plugin_check_require=None,
    )


def certifier_args(packet, out_dir, result_dir):
    return SimpleNamespace(
        executor="plugin",
        packet=packet,
        out_dir=out_dir,
        overwrite=False,
        result_dir=result_dir,
        profile="static",
        require_tool=[],
        wp_root=None,
        wp_env_root=None,
        plugin_check_require=None,
        timeout_sec=120,
    )


# Recorded from `phpcs --standard=WordPress --sniffs=... --report=json`.
# Shapes match phpcs 3.x report-json (source/type/line/column/severity/fixable).
def _phpcs_json(file_path, messages):
    return {
        "totals": {"errors": sum(1 for m in messages if m["type"] == "ERROR"), "warnings": sum(1 for m in messages if m["type"] == "WARNING"), "fixable": 0},
        "files": {file_path: {"errors": 0, "warnings": 0, "messages": messages}},
    }


PREPARED_SQL_ERROR = {
    "message": "Use placeholders and $wpdb->prepare(); found interpolated variable {$slug}.",
    "source": "WordPress.DB.PreparedSQL.InterpolatedNotPrepared",
    "severity": 5,
    "fixable": False,
    "type": "ERROR",
    "line": 37,
    "column": 10,
}
ESCAPE_OUTPUT_ERROR = {
    "message": "All output should be run through an escaping function.",
    "source": "WordPress.Security.EscapeOutput.OutputNotEscaped",
    "severity": 5,
    "fixable": False,
    "type": "ERROR",
    "line": 12,
    "column": 6,
}
NONCE_WARNING = {
    "message": "Processing form data without nonce verification.",
    "source": "WordPress.Security.NonceVerification.Missing",
    "severity": 5,
    "fixable": False,
    "type": "WARNING",
    "line": 8,
    "column": 3,
}

BLOCK_WRAPPER_SUPPRESSION = {
    "message": "All output should be run through an escaping function, found 'get_block_wrapper_attributes'.",
    "source": "WordPress.Security.EscapeOutput.OutputNotEscaped",
    "severity": 5,
    "fixable": False,
    "type": "ERROR",
    "line": 16,
    "column": 7,
}


def test_parse_phpcs_output_flattens_and_relativizes():
    output = _phpcs_json("/work/artifact/suppression-abuse.php", [PREPARED_SQL_ERROR])
    violations = wp_security_gate.parse_phpcs_output(output, Path("/work/artifact"))

    assert len(violations) == 1
    violation = violations[0]
    assert violation["file"] == "suppression-abuse.php"
    assert violation["line"] == 37
    assert violation["source"] == "WordPress.DB.PreparedSQL.InterpolatedNotPrepared"
    assert violation["type"] == "ERROR"


def test_diff_suppressions_flags_only_reappearing():
    ignored = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/work/artifact/suppression-abuse.php", [PREPARED_SQL_ERROR]), Path("/work/artifact")
    )
    normal = []  # the phpcs:ignore suppressed it in the normal run

    suppressed = wp_security_gate.diff_suppressions(normal, ignored)

    assert len(suppressed) == 1
    assert suppressed[0]["suppressed_rules"] == ["WordPress.DB.PreparedSQL.InterpolatedNotPrepared"]
    assert suppressed[0]["security_relevant"] is True
    assert suppressed[0]["reappears_without_annotations"] is True
    assert suppressed[0]["vuln_class"] == "sqli"


def test_diff_suppressions_ignores_violation_present_in_both_runs():
    both = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/work/artifact/x.php", [PREPARED_SQL_ERROR]), Path("/work/artifact")
    )
    assert wp_security_gate.diff_suppressions(both, both) == []


def test_diff_suppressions_allow_prefix_downgrades_relevance():
    ignored = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/work/artifact/x.php", [PREPARED_SQL_ERROR]), Path("/work/artifact")
    )
    suppressed = wp_security_gate.diff_suppressions([], ignored, allow_prefixes=("WordPress.DB.PreparedSQL",))
    assert suppressed[0]["security_relevant"] is False


def test_diff_suppressions_marks_reviewed_block_wrapper_helper_as_advisory():
    ignored = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/work/artifact/render.php", [BLOCK_WRAPPER_SUPPRESSION]), Path("/work/artifact")
    )
    suppressed = wp_security_gate.diff_suppressions([], ignored)

    assert suppressed[0]["security_relevant"] is False
    assert suppressed[0]["reviewed_safe_api"] == "get_block_wrapper_attributes"


def test_classify_hard_fails_prepared_sql_error():
    violations = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/a/x.php", [PREPARED_SQL_ERROR]), Path("/a")
    )
    findings, status, summary = wp_security_gate.classify(violations, [])

    assert status == "fail"
    assert findings[0]["enforced"] is True
    assert findings[0]["vuln_class"] == "sqli"
    assert summary["errors"] == 1


def test_classify_escape_output_error_is_enforced():
    violations = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/a/x.php", [ESCAPE_OUTPUT_ERROR]), Path("/a")
    )
    findings, status, _summary = wp_security_gate.classify(violations, [])
    assert status == "fail"
    assert findings[0]["enforced"] is True
    assert findings[0]["vuln_class"] == "xss"


def test_classify_advisory_warning_passes():
    violations = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/a/x.php", [NONCE_WARNING]), Path("/a")
    )
    findings, status, summary = wp_security_gate.classify(violations, [])

    assert status == "pass"
    assert findings[0]["enforced"] is False
    assert summary["advisory"] == 1
    assert summary["warnings"] == 1


def test_classify_suppressed_security_fails_even_with_no_direct_violations():
    ignored = wp_security_gate.parse_phpcs_output(
        _phpcs_json("/a/x.php", [PREPARED_SQL_ERROR]), Path("/a")
    )
    suppressed = wp_security_gate.diff_suppressions([], ignored)
    findings, status, summary = wp_security_gate.classify([], suppressed)

    assert findings == []
    assert status == "fail"
    assert summary["suppressed_security"] == 1


def test_vuln_class_mapping():
    assert wp_security_gate.vuln_class_for("WordPress.DB.PreparedSQL.NotPrepared") == "sqli"
    assert wp_security_gate.vuln_class_for("WordPress.Security.EscapeOutput.X") == "xss"
    assert wp_security_gate.vuln_class_for("WordPress.Security.NonceVerification.Missing") == "csrf"
    assert wp_security_gate.vuln_class_for("WordPress.Something.Else") == "other"


def test_summarize_report_phrases_each_status():
    assert "blocked" in wp_security_gate.summarize_report({"status": "blocked", "blocked_reason": "phpcs blocked"})
    assert wp_security_gate.summarize_report({"status": "skip"}) == "no PHP files to scan"

    passing = {"status": "pass", "findings": [], "suppressed_annotations": [], "summary": {"advisory": 2}}
    assert "no enforced security violations" in wp_security_gate.summarize_report(passing)
    assert "2 advisory" in wp_security_gate.summarize_report(passing)

    failing = {
        "status": "fail",
        "findings": [{"rule_id": "WordPress.DB.PreparedSQL", "severity": "error", "file": "x.php", "line": 36, "enforced": True}],
        "suppressed_annotations": [],
        "summary": {},
    }
    summary = wp_security_gate.summarize_report(failing)
    assert "1 enforced finding(s)" in summary
    assert "WordPress.DB.PreparedSQL" in summary


@pytest.mark.real_security_gate
@needs_toolchain
def test_configured_standard_registers_all_security_sniffs():
    command = [
        TOOLCHAIN.php,
        str(TOOLCHAIN.phpcs),
        f"--standard={wp_security_gate.PHPCS_STANDARD}",
        "--sniffs=" + ",".join(wp_security_gate.SECURITY_SNIFFS),
        "--runtime-set",
        "installed_paths",
        TOOLCHAIN.installed_paths,
        "-e",
    ]
    proc = subprocess.run(command, text=True, capture_output=True, timeout=120)

    assert proc.returncode == 0, proc.stderr or proc.stdout
    for sniff in wp_security_gate.SECURITY_SNIFFS:
        assert sniff in proc.stdout


def test_run_security_gate_blocked_without_toolchain(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "plugin.php").write_text("<?php\n/**\n * Plugin Name: Sample\n */\n", encoding="utf-8")

    report = wp_security_gate.run_security_gate(artifact, php_tools_root=tmp_path / "empty-tools")

    assert report["status"] == "blocked"
    assert report["findings"] == []
    reason = report["blocked_reason"]
    assert "composer install" in reason or "php executable" in reason
    assert wp_security_gate.summarize_report(report) == reason


def test_run_security_gate_skips_without_php_files(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "readme.txt").write_text("just text\n", encoding="utf-8")
    report = wp_security_gate.run_security_gate(artifact)
    assert report["status"] == "skip"


@pytest.mark.real_security_gate
def test_check_security_gate_skips_without_php_files(tmp_path):
    check, report = oracle.check_security_gate(tmp_path)
    assert check.status == "skip"
    assert report is None


@pytest.mark.real_security_gate
def test_oracle_surfaces_report_and_fails_artifact(monkeypatch, tmp_path):
    # Wiring test (no PHP): prove structural_checks -> extras -> result surfacing
    # carries the gate report onto the artifact result and a hard finding flips
    # the artifact status to fail. Stubs the phpcs subprocess layer only.
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "plugin.php").write_text(
        "<?php\n/**\n * Plugin Name: X\n * Requires at least: 6.5\n *\n * @package X\n */\n",
        encoding="utf-8",
    )
    fail_report = {
        "schema": wp_security_gate.SCHEMA,
        "schema_version": wp_security_gate.SCHEMA_VERSION,
        "status": "fail",
        "findings": [
            {
                "tool": "phpcs",
                "rule_id": "WordPress.DB.PreparedSQL.InterpolatedNotPrepared",
                "file": "plugin.php",
                "line": 5,
                "severity": "error",
                "vuln_class": "sqli",
                "enforced": True,
                "message": "interpolated query",
            }
        ],
        "suppressed_annotations": [],
        "summary": {"errors": 1, "warnings": 0, "advisory": 0, "suppressed_security": 0},
        "negative_space": [],
    }
    monkeypatch.setattr(wp_security_gate, "run_security_gate", lambda path, timeout_sec=120: fail_report)

    result = oracle.validate_artifact("plugin", plugin, oracle_args())

    assert result["status"] == "fail"
    assert result["security_gate"]["status"] == "fail"
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}
    assert "security_gate" in failed


@pytest.mark.real_security_gate
@needs_toolchain
def test_suppression_abuse_fixture_hard_fails():
    result = oracle.validate_artifact("plugin", FIXTURES / "suppression-abuse", oracle_args())

    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}
    assert "security_gate" in failed
    assert result["security_gate"]["status"] == "fail"
    suppressed = result["security_gate"]["suppressed_annotations"]
    assert any(entry["security_relevant"] for entry in suppressed)
    assert any("PreparedSQL" in rule for entry in suppressed for rule in entry["suppressed_rules"])


@pytest.mark.real_security_gate
@needs_toolchain
def test_prepared_escaped_and_clean_control_pass_the_gate():
    for fixture in ("prepared-escaped", "clean-control"):
        result = oracle.validate_artifact("plugin", FIXTURES / fixture, oracle_args())
        gate = result["security_gate"]
        assert gate["status"] == "pass", f"{fixture} should pass the security gate; got {gate}"
        assert all(not finding["enforced"] for finding in gate["findings"])


@pytest.mark.real_security_gate
@needs_toolchain
def test_broken_access_control_passes_gate_documenting_blind_spot():
    # The deterministic blind spot: sniffs are silent on __return_true; the gate
    # must pass here and hand exploitability judgment to the critic. If a future
    # sniff starts catching this, flip the assertion and move it to the critic.
    result = oracle.validate_artifact("plugin", FIXTURES / "broken-access-control", oracle_args())
    assert result["security_gate"]["status"] == "pass"


@pytest.mark.real_security_gate
@needs_toolchain
def test_certifier_writes_security_gate_json(tmp_path):
    packet = REPO / "evals" / "suites" / "wordpress-plugin-executor" / "examples" / "smoke-wordpress-v1.materializable-packet.md"
    result_dir = tmp_path / "result"
    result = certifier.certify_executor_artifact(certifier_args(packet, tmp_path / "generated", result_dir))

    gate = result["artifact_gate"]["security_gate"]
    assert gate["status"] in {"pass", "skip"}
    security_path = result_dir / "security-gate.json"
    assert security_path.exists()
    written = json.loads(security_path.read_text(encoding="utf-8"))
    assert written["schema"] == wp_security_gate.SCHEMA
    assert written["schema_version"] == wp_security_gate.SCHEMA_VERSION
    assert written["negative_space"]
    assert "reviewed_suppressed" in written["summary"]
    assert {tool["id"] for tool in written["tools"]} == {"phpcs-security", "phpcs-suppression-diff"}
    assert all(tool["command"] for tool in written["tools"])
