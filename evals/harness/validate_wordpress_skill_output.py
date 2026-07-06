#!/usr/bin/env python3
"""Deterministic contract oracle for saved WordPress skill outputs.

This validates the shape and usefulness of a saved WordPress planner, executor,
or critic response. It is intentionally model-free: no judge, no network, no
WordPress runtime. The goal is to measure the skill suite's durable value:
consistent contracts, explicit boundaries, exact WordPress surfaces, and
verification-oracle specificity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

VERDICTS = {"REJECT", "REVISE", "ACCEPT-WITH-RESERVATIONS", "ACCEPT"}

EXACT_SURFACES = (
    "$wpdb->prepare",
    "@wordpress/scripts",
    "@wordpress/abilities",
    "@wordpress/core-abilities",
    "Action Scheduler",
    "Plugin Check",
    "Query Monitor",
    "WP-CLI",
    "WP_Query",
    "admin-ajax.php",
    "block.json",
    "check_admin_referer",
    "check_ajax_referer",
    "current_user_can",
    "map_meta_cap",
    "permission_callback",
    "register_activation_hook",
    "register_block_type",
    "register_deactivation_hook",
    "register_post_meta",
    "register_post_type",
    "register_rest_route",
    "register_setting",
    "register_taxonomy",
    "render_callback",
    "sanitize_key",
    "sanitize_text_field",
    "show_in_rest",
    "theme.json",
    "uninstall.php",
    "wp cli",
    "wp-env",
    "wp_cache_get",
    "wp_cache_set",
    "wp_enqueue_script",
    "wp_handle_upload",
    "wp_interactivity_config",
    "wp_interactivity_state",
    "wp_kses_post",
    "wp_next_scheduled",
    "wp_safe_redirect",
    "wp_schedule_event",
    "wp_register_ability",
    "wp_abilities_api_init",
    "wp_ai_client_prompt",
    "wp_connectors_init",
    "wp_verify_nonce",
    "wordpress/mcp-adapter",
)

VERIFICATION_TERMS = (
    "apm",
    "block validation",
    "browser devtools",
    "browser performance trace",
    "core web vitals",
    "crawl comparison",
    "database query logs",
    "dry run",
    "dry-run",
    "editor smoke",
    "explain select",
    "frontend smoke",
    "import-log",
    "launch rehearsal",
    "network panel",
    "object-cache metrics",
    "php -l",
    "phpcs",
    "phpstan",
    "phpunit",
    "playground",
    "playwright",
    "plugin check",
    "psalm",
    "query monitor",
    "redirect map",
    "rollback test",
    "screaming frog",
    "site editor",
    "theme check",
    "wp cli",
    "wp cron event list",
    "wp-env",
    "wp media import",
    "wp option list",
    "wp post list",
    "wp profile",
    "wp redirection",
    "wp rewrite flush",
    "wp rewrite list",
    "wp search-replace",
    "wpcs",
    "security-gate.json",
    "phpcs-suppression-diff",
    "--ignore-annotations",
    "suppressed_annotations",
)

NEGATIVE_SPACE_TERMS = (
    "does not prove",
    "does not claim",
    "is not claimed",
    "not claimed",
    "not claiming",
    "not proven",
    "outside scope",
    "out of scope",
    "negative space",
    "cannot verify",
    "assumption",
    "open question",
    "unknown",
)

PLACEHOLDER_RE = re.compile(r"(\b(TBD|TODO|FIXME|PLACEHOLDER)\b|\[(?i:finding|todo|placeholder)\])")
GENERIC_LABELS = (
    "add security",
    "check accessibility",
    "ensure performance",
    "fix the issue",
    "run tests",
    "use capabilities",
    "use escaping",
    "use nonces",
    "use wordpress apis",
)

MD_HEADING_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
BOLD_HEADING_RE = re.compile(r"(?m)^\*\*(.+?)\*\*\s*$")
VERDICT_RE = re.compile(r"(?im)^\*\*VERDICT:\s*([A-Z-]+).*?\*\*")


PLANNER_HEADINGS = {
    "wordpress-planner": [
        "Scope Summary",
        "Current-State Evidence",
        "Architecture Plan",
        "WordPress-Specific Decisions",
        "Assumption Register",
        "Test And Verification Strategy",
        "Implementation Sequence",
        "Executor Handoff",
        "Critic Checkpoints",
        "Acceptance Criteria",
        "Assumptions And Open Questions",
    ],
    "wordpress-plugin-planner": [
        "Plugin Scope",
        "Current-State Evidence",
        "Architecture And File Map",
        "Hook And Data Flow",
        "Security And Data Integrity",
        "Operations And Release Plan",
        "Assumption Register",
        "Test Strategy",
        "Acceptance Criteria",
        "Executor Handoff",
        "Critic Handoff",
    ],
    "wordpress-block-planner": [
        "Block Scope",
        "Current-State Evidence",
        "Metadata And Attribute Plan",
        "Render And Interaction Plan",
        "Compatibility And Migration Plan",
        "Security Performance And Accessibility Notes",
        "Assumption Register",
        "Test Strategy",
        "Acceptance Criteria",
        "Executor Handoff",
        "Critic Handoff",
    ],
    "wordpress-theme-planner": [
        "Theme Scope",
        "Current-State Evidence",
        "Theme JSON And Template Plan",
        "Pattern And Style Variation Plan",
        "Editor Frontend Parity Plan",
        "Accessibility Responsive And Performance Plan",
        "Assumption Register",
        "Test Strategy",
        "Acceptance Criteria",
        "Executor Handoff",
        "Critic Handoff",
    ],
    "wordpress-content-model-planner": [
        "Content Model Summary",
        "Current-State Evidence",
        "Content Behavior Analysis",
        "Post Type Taxonomy And Field Matrix",
        "Editorial Workflow",
        "API Search And Template Implications",
        "Migration And Validation Plan",
        "Assumption Register",
        "Alternatives Considered",
        "Acceptance Criteria",
        "Executor Handoff",
        "Critic Handoff",
    ],
    "wordpress-migration-planner": [
        "Migration Scope",
        "Current-State Evidence",
        "Source Audit",
        "Target Mapping",
        "Transform And Execution Plan",
        "Validation Plan",
        "Rollback And Monitoring",
        "Assumption Register",
        "Test Strategy",
        "Acceptance Criteria",
        "Critic Handoff",
    ],
}

EXECUTOR_HEADINGS = {
    "wordpress-plugin-executor": [
        "Spec Conformance",
        "Generated File Map",
        "Implementation Packets",
        "Security Notes",
        "Deviation Log",
        "Verification Notes",
        "Critic Handoff",
    ],
    "wordpress-block-executor": [
        "Spec Conformance",
        "Generated Block Files",
        "Compatibility Notes",
        "Security Performance And Accessibility Notes",
        "Deviation Log",
        "Verification Notes",
        "Critic Handoff",
    ],
    "wordpress-theme-executor": [
        "Spec Conformance",
        "Generated Theme Files",
        "Accessibility And Performance Notes",
        "Editor Frontend Parity Notes",
        "Deviation Log",
        "Verification Notes",
        "Critic Handoff",
    ],
    "wordpress-blueprint-executor": [
        "Input Summary",
        "Generated Blueprint",
        "Provenance Notes",
        "Safety And Determinism Notes",
        "Deviation Log",
        "Verification Notes",
        "Critic Handoff",
    ],
}

CRITIC_HEADINGS = {
    "wordpress-critic": [
        "VERDICT",
        "Overall Assessment",
        "Pre-commitment Predictions",
        "Critical Findings",
        "Major Findings",
        "Minor Findings",
        "What's Missing",
        "Multi-Perspective Notes",
        "Verdict Justification",
        "Remediation Guide",
        "Open Questions",
    ],
    "wordpress-security-critic": [
        "VERDICT",
        "Overall Assessment",
        "Pre-commitment Predictions",
        "Security Gate Evidence",
        "Critical Findings",
        "Major Findings",
        "Minor Findings",
        "Suppression Review",
        "What's Missing",
        "Multi-Perspective Notes",
        "Exploitability Notes",
        "Verdict Justification",
        "Remediation Guide",
        "Open Questions",
    ],
    "wordpress-theme-critic": [
        "VERDICT",
        "Overall Assessment",
        "Pre-commitment Predictions",
        "Critical Findings",
        "Major Findings",
        "Minor Findings",
        "What's Missing",
        "Multi-Perspective Notes",
        "Verdict Justification",
        "Remediation Guide",
        "Open Questions",
    ],
    "wordpress-performance-critic": [
        "VERDICT",
        "Overall Assessment",
        "Pre-commitment Predictions",
        "Critical Findings",
        "Major Findings",
        "Minor Findings",
        "What's Missing",
        "Multi-Perspective Notes",
        "Measurement Notes",
        "Verdict Justification",
        "Remediation Guide",
        "Open Questions",
    ],
}

CONTRACTS: dict[str, dict[str, Any]] = {}
for skill_name, headings in PLANNER_HEADINGS.items():
    CONTRACTS[skill_name] = {"role": "planner", "headings": headings, "min_surfaces": 2, "needs_verdict": False}
for skill_name, headings in EXECUTOR_HEADINGS.items():
    CONTRACTS[skill_name] = {"role": "executor", "headings": headings, "min_surfaces": 3, "needs_verdict": False}
for skill_name, headings in CRITIC_HEADINGS.items():
    CONTRACTS[skill_name] = {"role": "critic", "headings": headings, "min_surfaces": 2, "needs_verdict": True}

ALIASES = {
    "wordpress-planner.block": "wordpress-block-planner",
    "wordpress-planner.content-model": "wordpress-content-model-planner",
    "wordpress-planner.migration": "wordpress-migration-planner",
    "wordpress-planner.plugin": "wordpress-plugin-planner",
    "wordpress-planner.theme": "wordpress-theme-planner",
}
CONTRACT_CHOICES = sorted(set(CONTRACTS) | set(ALIASES))


@dataclass(frozen=True)
class Check:
    id: str
    passed: bool
    weight: int
    detail: str


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("->", " ")
    text = re.sub(r"[^a-z0-9_@./$*-]+", " ", text)
    return " ".join(text.split())


def _surface_present(surface: str, text: str) -> bool:
    tokens = [tok for tok in _norm(surface).split() if tok]
    normalized = _norm(text)
    return bool(tokens) and all(tok in normalized for tok in tokens)


def found_headings(text: str) -> set[str]:
    headings = {match.group(1).strip() for match in MD_HEADING_RE.finditer(text)}
    for match in BOLD_HEADING_RE.finditer(text):
        heading = match.group(1).strip()
        if heading.upper().startswith("VERDICT:"):
            headings.add("VERDICT")
        else:
            headings.add(heading)
    return headings


def check_headings(text: str, contract: dict[str, Any]) -> Check:
    found = found_headings(text)
    missing = [heading for heading in contract["headings"] if heading not in found]
    return Check(
        "required_output_headings",
        not missing,
        4,
        "all required headings present" if not missing else f"missing headings: {', '.join(missing)}",
    )


def check_verdict(text: str, contract: dict[str, Any]) -> Check:
    if not contract["needs_verdict"]:
        return Check("critic_verdict", True, 1, "verdict not required for this role")
    match = VERDICT_RE.search(text)
    if not match:
        return Check("critic_verdict", False, 3, "missing bold VERDICT heading")
    verdict = match.group(1).upper()
    return Check(
        "critic_verdict",
        verdict in VERDICTS,
        3,
        f"valid verdict: {verdict}" if verdict in VERDICTS else f"invalid verdict: {verdict}",
    )


def check_exact_surfaces(text: str, contract: dict[str, Any]) -> Check:
    matched = sorted({surface for surface in EXACT_SURFACES if _surface_present(surface, text)})
    has_non_applicability = "no exact wordpress api applies" in text.lower()
    min_surfaces = int(contract["min_surfaces"])
    passed = len(matched) >= min_surfaces or has_non_applicability
    detail = f"matched {len(matched)} exact WordPress surfaces"
    if has_non_applicability:
        detail += "; explicit non-applicability statement present"
    if not passed:
        detail += f"; expected at least {min_surfaces}"
    return Check("exact_wordpress_surfaces", passed, 3, detail)


def check_verification_specificity(text: str) -> Check:
    normalized = _norm(text)
    matched = sorted({term for term in VERIFICATION_TERMS if _norm(term) in normalized})
    return Check(
        "verification_specificity",
        bool(matched),
        3,
        f"verification terms present: {', '.join(matched)}" if matched else "no concrete verification oracle named",
    )


def check_negative_space(text: str) -> Check:
    lower = text.lower()
    matched = sorted({term for term in NEGATIVE_SPACE_TERMS if term in lower})
    return Check(
        "negative_space",
        bool(matched),
        2,
        f"boundary terms present: {', '.join(matched)}" if matched else "no negative-space or uncertainty language found",
    )


def check_no_placeholders(text: str) -> Check:
    hits = sorted({match.group(0) for match in PLACEHOLDER_RE.finditer(text)})
    return Check(
        "no_placeholders",
        not hits,
        2,
        "no placeholder markers found" if not hits else f"placeholder markers found: {', '.join(hits)}",
    )


def check_no_generic_labels(text: str) -> Check:
    lower = text.lower()
    hits = []
    for label in GENERIC_LABELS:
        pattern = rf"(?<![a-z0-9_-]){re.escape(label)}(?![a-z0-9_-])"
        for match in re.finditer(pattern, lower):
            if label == "run tests":
                rest = lower[match.end():match.end() + 8]
                if re.match(r"\s+\d", rest):
                    continue
            hits.append(label)
            break
    hits = sorted(set(hits))
    return Check(
        "no_generic_wp_labels",
        not hits,
        2,
        "no generic WordPress labels found" if not hits else f"generic labels found: {', '.join(hits)}",
    )


def _mentions(value: Any, text: str) -> bool:
    if value is None:
        return True
    return _norm(str(value)) in _norm(text)


def _mentions_location(file_name: Any, line: Any, text: str) -> bool:
    if not file_name:
        return True
    raw = text.lower().replace("`", "")
    file_text = str(file_name).lower()
    if file_text not in raw:
        return False
    if line in {None, ""}:
        return True
    line_text = str(line)
    return (
        f"{file_text}:{line_text}" in raw
        or f"{file_text} line {line_text}" in raw
        or f"{file_text}, line {line_text}" in raw
        or f"{file_text} (line {line_text})" in raw
    )


def load_security_gate(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"security gate JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("security gate JSON must contain an object")
    return payload


def _mentions_blocked_reason(reason: Any, text: str) -> bool:
    if not reason:
        return True
    normalized_text = _norm(text)
    reason_text = _norm(str(reason))
    if reason_text in normalized_text:
        return True
    indicators = ("blocked", "phpcs", "wpcs", "composer install", "toolchain", "not found", "missing")
    return any(_norm(indicator) in normalized_text for indicator in indicators)


def check_security_gate_consumption(text: str, report: dict[str, Any]) -> Check:
    missing: list[str] = []
    if report.get("schema") != "wordpress-security-gate":
        missing.append("schema=wordpress-security-gate")
    if report.get("schema_version") != 1:
        missing.append("schema_version=1")

    status = report.get("status")
    if status not in {"pass", "fail", "blocked", "skip"}:
        missing.append("valid security gate status")
    elif not _mentions(status, text):
        missing.append(f"gate status {status}")

    if "security-gate.json" not in text.lower() and "security gate" not in text.lower():
        missing.append("security-gate.json provenance")

    provenance_terms = ("gate-derived", "critic-derived", "evidence provenance", "sidecar")
    if not any(term in text.lower() for term in provenance_terms):
        missing.append("gate-derived vs critic-derived provenance")

    tool_ids = {str(tool.get("id")) for tool in report.get("tools", []) if isinstance(tool, dict) and tool.get("id")}
    if "phpcs-suppression-diff" in tool_ids and not (
        "phpcs-suppression-diff" in text.lower() or "--ignore-annotations" in text.lower()
    ):
        missing.append("phpcs-suppression-diff tool evidence")

    if status == "blocked" and not _mentions_blocked_reason(report.get("blocked_reason"), text):
        missing.append("blocked_reason")
    if status == "skip" and "no php" not in text.lower() and "skip" not in text.lower():
        missing.append("skip/no PHP explanation")

    enforced_findings = [
        finding
        for finding in report.get("findings", [])
        if isinstance(finding, dict) and finding.get("enforced")
    ]
    advisory_findings = [
        finding
        for finding in report.get("findings", [])
        if isinstance(finding, dict) and not finding.get("enforced")
    ]
    for finding in enforced_findings:
        rule_id = finding.get("rule_id")
        if rule_id and not _mentions(rule_id, text):
            missing.append(f"enforced rule {rule_id}")
        if not _mentions_location(finding.get("file"), finding.get("line"), text):
            missing.append(f"enforced location {finding.get('file')}:{finding.get('line')}")
    for finding in advisory_findings:
        rule_id = finding.get("rule_id")
        if rule_id and not _mentions(rule_id, text):
            missing.append(f"advisory rule {rule_id}")
        if not _mentions_location(finding.get("file"), finding.get("line"), text):
            missing.append(f"advisory location {finding.get('file')}:{finding.get('line')}")
    if advisory_findings and "advisory" not in text.lower():
        missing.append("advisory finding calibration")

    suppressed_entries = [
        entry
        for entry in report.get("suppressed_annotations", [])
        if isinstance(entry, dict)
    ]
    if suppressed_entries and "suppression" not in text.lower():
        missing.append("suppression review")
    for entry in suppressed_entries:
        if not _mentions_location(entry.get("file"), entry.get("line"), text):
            missing.append(f"suppression location {entry.get('file')}:{entry.get('line')}")
        for rule in entry.get("suppressed_rules") or []:
            if not _mentions(rule, text):
                missing.append(f"suppressed rule {rule}")
        reviewed_api = entry.get("reviewed_safe_api")
        if reviewed_api and not _mentions(reviewed_api, text):
            missing.append(f"reviewed safe API {reviewed_api}")
        if entry.get("security_relevant") and "security-relevant" not in text.lower() and "security relevant" not in text.lower():
            missing.append(f"security relevance {entry.get('file')}:{entry.get('line')}")
        if entry.get("security_relevant") is False and not (
            "not security-relevant" in text.lower()
            or "not security relevant" in text.lower()
            or "reviewed safe" in text.lower()
            or "advisory" in text.lower()
        ):
            missing.append(f"non-security suppression calibration {entry.get('file')}:{entry.get('line')}")
        if entry.get("reappears_without_annotations") and not (
            "reappears" in text.lower()
            or "without annotations" in text.lower()
            or "--ignore-annotations" in text.lower()
        ):
            missing.append(f"suppression reappearance {entry.get('file')}:{entry.get('line')}")

    if report.get("negative_space") and not (
        "negative space" in text.lower()
        or "does not prove" in text.lower()
        or "blind spot" in text.lower()
    ):
        missing.append("security gate negative space")

    return Check(
        "security_gate_consumption",
        not missing,
        4,
        "security gate evidence consumed" if not missing else f"missing: {', '.join(sorted(set(missing)))}",
    )


def validate_output(skill: str, text: str, security_gate: dict[str, Any] | None = None) -> dict[str, Any]:
    requested_skill = skill
    skill = ALIASES.get(skill, skill)
    if skill not in CONTRACTS:
        raise KeyError(f"unknown WordPress skill: {requested_skill}")
    contract = CONTRACTS[skill]
    checks = [
        check_headings(text, contract),
        check_verdict(text, contract),
        check_exact_surfaces(text, contract),
        check_verification_specificity(text),
        check_negative_space(text),
        check_no_placeholders(text),
        check_no_generic_labels(text),
    ]
    if skill == "wordpress-security-critic" and security_gate is not None:
        checks.append(check_security_gate_consumption(text, security_gate))
    total = sum(check.weight for check in checks)
    earned = sum(check.weight for check in checks if check.passed)
    return {
        "skill": skill,
        "requested_skill": requested_skill,
        "role": contract["role"],
        "pass": all(check.passed for check in checks),
        "score": round(earned / total, 4) if total else 0.0,
        "checks": [asdict(check) for check in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate saved WordPress skill output contract conformance.")
    parser.add_argument("--skill", choices=CONTRACT_CHOICES, required=True)
    parser.add_argument("--output", required=True, help="Saved skill output markdown file.")
    parser.add_argument(
        "--security-gate",
        help="Optional security-gate.json sidecar to require in wordpress-security-critic output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = Path(args.output)
    if not output_path.exists():
        print(json.dumps({"pass": False, "error": f"output file not found: {output_path}"}, indent=2), file=sys.stderr)
        return 1
    security_gate = None
    if args.security_gate:
        gate_path = Path(args.security_gate)
        if not gate_path.exists():
            print(json.dumps({"pass": False, "error": f"security gate file not found: {gate_path}"}, indent=2), file=sys.stderr)
            return 1
        try:
            security_gate = load_security_gate(gate_path)
        except ValueError as exc:
            print(json.dumps({"pass": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 1
    result = validate_output(args.skill, output_path.read_text(encoding="utf-8"), security_gate=security_gate)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
