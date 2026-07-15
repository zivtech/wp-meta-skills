"""Tests for WordPress saved skill-output contract validation."""

import json

import pytest

import validate_wordpress_skill_output as oracle


GOOD_PLANNER = """\
## Plugin Scope
Build an editorial review plugin for an existing WordPress admin workflow.

## Current-State Evidence
The repo already uses `register_post_type()` and `register_post_meta()` with `show_in_rest`.

## Architecture And File Map
Use a small plugin bootstrap plus an admin settings class.

## Hook And Data Flow
Use `register_setting()`, `current_user_can()`, and `check_admin_referer()`.

## Security And Data Integrity
Rich text uses `wp_kses_post()` and redirects use `wp_safe_redirect()`.

## Operations And Release Plan
Run PHPCS/WPCS, PHPUnit, WP-CLI smoke, and Plugin Check before release.

## Assumption Register
    Assumption: no exact WordPress API applies to external CRM ownership because
    WordPress does not control the vendor account; the CRM owner must confirm it
    against the vendor API contract.

## Test Strategy
PHPUnit covers settings persistence; Plugin Check covers package readiness.

## Acceptance Criteria
Admin save succeeds only for users with the mapped capability.

## Executor Handoff
Generate plugin files and tests.

## Critic Handoff
Send to wordpress-security-critic and wordpress-critic.
"""


BAD_PLANNER = """\
## Plugin Scope
[Finding]

## Architecture
Use WordPress APIs, use nonces, use capabilities, and run tests.
"""


GOOD_CRITIC = """\
**VERDICT: REVISE**

**Overall Assessment**
The implementation has a real REST authorization gap.

**Pre-commitment Predictions**
Expected issue: missing `permission_callback` on a custom route.

**Critical Findings**
- None.

**Major Findings**
- `register_rest_route()` lacks a specific `permission_callback` using `current_user_can()`.

**Minor Findings**
- None.

**What's Missing**
This review does not prove runtime behavior or editor smoke results.

**Multi-Perspective Notes**
Security and operations agree the route needs a capability boundary.

**Verdict Justification**
REVISE because the code is close but cannot ship without authorization.

**Remediation Guide**
Add a `permission_callback`, cover it with PHPUnit, then run WP-CLI smoke and Plugin Check.

**Open Questions**
Unknown: which role should receive the new capability.
"""


BAD_CRITIC = """\
**VERDICT: MAYBE**

**Overall Assessment**
Looks fine.
"""


SECURITY_GATE_REPORT = {
    "schema": "wordpress-security-gate",
    "schema_version": 1,
    "status": "fail",
    "tools": [
        {"id": "phpcs-security", "status": "fail"},
        {"id": "phpcs-suppression-diff", "status": "fail"},
    ],
    "findings": [
        {
            "rule_id": "WordPress.Security.EscapeOutput.OutputNotEscaped",
            "file": "acme-report/admin.php",
            "line": 38,
            "severity": "error",
            "enforced": True,
        },
        {
            "rule_id": "WordPress.DB.DirectDatabaseQuery.DirectQuery",
            "file": "acme-report/admin.php",
            "line": 40,
            "severity": "warning",
            "enforced": False,
        }
    ],
    "suppressed_annotations": [
        {
            "file": "acme-report/admin.php",
            "line": 42,
            "suppressed_rules": ["WordPress.DB.PreparedSQL.InterpolatedNotPrepared"],
            "security_relevant": True,
            "reappears_without_annotations": True,
        },
        {
            "file": "blocks/render.php",
            "line": 16,
            "suppressed_rules": ["WordPress.Security.EscapeOutput.OutputNotEscaped"],
            "security_relevant": False,
            "reviewed_safe_api": "get_block_wrapper_attributes",
        },
    ],
    "summary": {"errors": 1, "warnings": 0, "suppressed_security": 1, "reviewed_suppressed": 1},
    "negative_space": ["No authorization/IDOR/capability-correctness reasoning."],
}


GOOD_SECURITY_CRITIC_WITH_GATE = """\
**VERDICT: REVISE**

**Overall Assessment**
The artifact fails the supplied `security-gate.json` static profile and needs
reachability review before release.

**Pre-commitment Predictions**
Expected failures: suppressed SQL preparation and escaped-output gaps.

**Security Gate Evidence**
Gate-derived evidence from `security-gate.json` reports status `fail`.
`phpcs-suppression-diff` / `--ignore-annotations` found
`WordPress.DB.PreparedSQL.InterpolatedNotPrepared` at
`acme-report/admin.php:42`. The enforced PHPCS finding
`WordPress.Security.EscapeOutput.OutputNotEscaped` is at
`acme-report/admin.php:38`. Advisory gate-derived evidence includes
`WordPress.DB.DirectDatabaseQuery.DirectQuery` at `acme-report/admin.php:40`.

**Critical Findings**
- None until the caller path is proven.

**Major Findings**
- The report query suppression hides a `$wpdb->prepare()` failure, and the
  rendered admin output must use `wp_kses_post()` or `esc_html()` by context.

**Minor Findings**
- None.

**Suppression Review**
- `acme-report/admin.php:42` is a security-relevant suppression because
  `WordPress.DB.PreparedSQL.InterpolatedNotPrepared` reappears without
  annotations.
- `blocks/render.php:16` suppresses
  `WordPress.Security.EscapeOutput.OutputNotEscaped`; it is not
  security-relevant because the reviewed safe API is
  `get_block_wrapper_attributes`.

**What's Missing**
The gate's negative space does not prove authorization, IDOR, or capability
correctness; that critic-derived path review remains open.

**Multi-Perspective Notes**
Security and operations agree the deterministic sidecar blocks release.

**Exploitability Notes**
No CRITICAL finding until a role, route, or admin-post caller path is named.

**Verdict Justification**
REVISE because gate-derived evidence is deterministic and the critic-derived
reachability review is incomplete.

**Remediation Guide**
Remove the SQL suppression, prepare the query with `$wpdb->prepare()`, keep
contextual output escaping with `wp_kses_post()` or `esc_html()`, then rerun
PHPCS/WPCS and the security gate.

**Open Questions**
Unknown: which capability is required to reach `acme-report/admin.php`.
"""


def test_good_planner_output_passes():
    result = oracle.validate_output("wordpress-plugin-planner", GOOD_PLANNER)

    assert result["pass"] is True
    assert result["score"] == 1.0


def test_blanket_non_applicability_cannot_replace_exact_surfaces():
    check = oracle.check_exact_surfaces(
        "No exact WordPress API applies.",
        {"min_surfaces": 2},
    )

    assert check.passed is False
    assert "expected at least 2" in check.detail


def test_exact_surface_matching_is_boundary_and_order_aware():
    partial = oracle.check_exact_surfaces(
        "current_user_canary and register_rest_routeable are custom names.",
        {"min_surfaces": 1},
    )
    scattered = oracle.check_exact_surfaces(
        "Use register_rest_route. In a separate sentence, add permission_callback.",
        {"min_surfaces": 2},
    )
    exact = oracle.check_exact_surfaces(
        "Use current_user_can() and register_rest_route permission_callback.",
        {"min_surfaces": 2},
    )

    assert partial.passed is False
    assert scattered.passed is False
    assert exact.passed is True
    assert "core_function:current_user_can()" in exact.detail
    assert "reviewed_composed:register_rest_route permission_callback" in exact.detail


@pytest.mark.parametrize(
    "statement",
    [
        "No exact WordPress API applies because this is external; verify it with the owner.",
        "No exact WordPress API applies to external CRM ownership; verify it with the CRM owner.",
        "No exact WordPress API applies to external CRM ownership because WordPress does not control it.",
    ],
)
def test_non_applicability_requires_scope_reason_and_oracle(statement):
    text = f"Use current_user_can() and register_post_type(). {statement}"

    check = oracle.check_exact_surfaces(text, {"min_surfaces": 2})

    assert check.passed is False
    assert "invalid non-applicability" in check.detail


def test_scoped_non_applicability_does_not_waive_surface_minimum():
    statement = (
        "No exact WordPress API applies to external CRM ownership because WordPress "
        "does not control the vendor account; verify it with the CRM owner against "
        "the vendor API contract."
    )

    too_few = oracle.check_exact_surfaces(
        f"Use current_user_can(). {statement}",
        {"min_surfaces": 2},
    )
    enough = oracle.check_exact_surfaces(
        f"Use current_user_can() and register_post_type(). {statement}",
        {"min_surfaces": 2},
    )

    assert too_few.passed is False
    assert enough.passed is True
    assert "scoped non-applicability" in enough.detail


def test_dot_notation_planner_alias_passes():
    result = oracle.validate_output("wordpress-planner.plugin", GOOD_PLANNER)

    assert result["pass"] is True
    assert result["skill"] == "wordpress-plugin-planner"
    assert result["requested_skill"] == "wordpress-planner.plugin"


def test_bad_planner_output_fails_contract_checks():
    result = oracle.validate_output("wordpress-plugin-planner", BAD_PLANNER)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert {"required_output_headings", "no_placeholders", "no_generic_wp_labels"} <= failed


def test_good_critic_output_passes():
    result = oracle.validate_output("wordpress-critic", GOOD_CRITIC)

    assert result["pass"] is True


def test_performance_verification_terms_are_contract_evidence():
    check = oracle.check_verification_specificity(
        "Measure before and after with Query Monitor, Core Web Vitals, "
        "browser performance trace, object-cache metrics, and "
        "`wp option list --autoload=on`."
    )

    assert check.passed is True
    assert "query monitor" in check.detail
    assert "wp option list" in check.detail


def test_migration_verification_terms_are_contract_evidence():
    check = oracle.check_verification_specificity(
        "Validate with `wp post list`, `wp media import`, "
        "`wp search-replace --dry-run`, a crawl comparison, "
        "launch rehearsal, and rollback test."
    )

    assert check.passed is True
    assert "wp post list" in check.detail
    assert "wp search-replace" in check.detail


def test_bad_critic_output_fails_verdict_and_headings():
    result = oracle.validate_output("wordpress-critic", BAD_CRITIC)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert {"critic_verdict", "required_output_headings"} <= failed


def test_lowercase_placeholder_word_in_prose_is_not_marker():
    result = oracle.check_no_placeholders(
        "Replace placeholder values with the canonical plugin constants, but do not leave TODO markers."
    )

    assert result.passed is False

    clean = oracle.check_no_placeholders(
        "Replace placeholder values with the canonical plugin constants before release."
    )

    assert clean.passed is True


def test_generic_label_check_allows_numbered_rerun_test_references():
    allowed = oracle.check_no_generic_labels(
        "Rerun tests: import the redirect map, then run tests 4 and 5 again."
    )
    rejected = oracle.check_no_generic_labels("Use WordPress APIs and run tests.")

    assert allowed.passed is True
    assert rejected.passed is False


def test_security_critic_output_passes_without_sidecar_when_contract_is_met():
    result = oracle.validate_output("wordpress-security-critic", GOOD_SECURITY_CRITIC_WITH_GATE)

    assert result["pass"] is True
    assert "security_gate_consumption" not in {check["id"] for check in result["checks"]}


def test_security_gate_sidecar_requires_rule_and_suppression_consumption():
    result = oracle.validate_output(
        "wordpress-security-critic",
        GOOD_SECURITY_CRITIC_WITH_GATE,
        security_gate=SECURITY_GATE_REPORT,
    )

    assert result["pass"] is True
    assert any(check["id"] == "security_gate_consumption" and check["passed"] for check in result["checks"])

    weak_output = GOOD_SECURITY_CRITIC_WITH_GATE.replace(
        "WordPress.DB.PreparedSQL.InterpolatedNotPrepared",
        "the prepared SQL sniff",
    )
    weak_result = oracle.validate_output(
        "wordpress-security-critic",
        weak_output,
        security_gate=SECURITY_GATE_REPORT,
    )
    failed = {check["id"] for check in weak_result["checks"] if not check["passed"]}

    assert weak_result["pass"] is False
    assert "security_gate_consumption" in failed

    no_advisory = GOOD_SECURITY_CRITIC_WITH_GATE.replace(
        "Advisory gate-derived evidence includes\n`WordPress.DB.DirectDatabaseQuery.DirectQuery` at `acme-report/admin.php:40`.",
        "There is no advisory gate-derived evidence.",
    )
    no_advisory_result = oracle.validate_output(
        "wordpress-security-critic",
        no_advisory,
        security_gate=SECURITY_GATE_REPORT,
    )
    no_advisory_failed = {check["id"] for check in no_advisory_result["checks"] if not check["passed"]}

    assert no_advisory_result["pass"] is False
    assert "security_gate_consumption" in no_advisory_failed


def test_security_gate_sidecar_requires_file_bound_locations():
    loose_location = GOOD_SECURITY_CRITIC_WITH_GATE.replace(
        "`acme-report/admin.php:42`",
        "`acme-report/admin.php` near line 42",
    )

    result = oracle.validate_output(
        "wordpress-security-critic",
        loose_location,
        security_gate=SECURITY_GATE_REPORT,
    )
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "security_gate_consumption" in failed


def test_cli_accepts_security_gate_sidecar(tmp_path, capsys):
    output = tmp_path / "candidate.md"
    gate = tmp_path / "security-gate.json"
    output.write_text(GOOD_SECURITY_CRITIC_WITH_GATE, encoding="utf-8")
    gate.write_text(json.dumps(SECURITY_GATE_REPORT), encoding="utf-8")

    rc = oracle.main(
        [
            "--skill",
            "wordpress-security-critic",
            "--output",
            str(output),
            "--security-gate",
            str(gate),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["pass"] is True
    assert captured.err == ""


def test_cli_missing_security_gate_fails_cleanly(tmp_path, capsys):
    output = tmp_path / "candidate.md"
    output.write_text(GOOD_SECURITY_CRITIC_WITH_GATE, encoding="utf-8")

    rc = oracle.main(
        [
            "--skill",
            "wordpress-security-critic",
            "--output",
            str(output),
            "--security-gate",
            str(tmp_path / "missing-security-gate.json"),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert rc == 1
    assert payload["pass"] is False
    assert "security gate file not found" in payload["error"]
