#!/usr/bin/env python3
"""Deterministic contract oracle for WordPress executor packets.

This validates saved outputs from the WordPress plugin/block/blueprint executors.
It is intentionally cheap: no LLM judge, no WordPress runtime, no network. The
goal is to catch dead executor packets before they enter a model comparison:
missing output sections, vague WordPress surfaces, no runnable verification
oracles, unsafe production commands, or invalid Blueprint JSON.
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

EXACT_SURFACES = (
    "$wpdb->prepare",
    "@wordpress/abilities",
    "@wordpress/core-abilities",
    "@wordpress/scripts",
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
    "delete_transient",
    "deprecated block versions",
    "esc_attr",
    "esc_html",
    "esc_url",
    "map_meta_cap",
    "permission_callback",
    "phpcs",
    "phpunit",
    "playwright",
    "playground",
    "blueprint",
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
    "set_transient",
    "show_in_rest",
    "theme.json",
    "uninstall.php",
    "wp cli",
    "wp export",
    "wp import",
    "wp media import",
    "wp search-replace --dry-run",
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
    "wp_register_ability_category",
    "wp_abilities_api_categories_init",
    "label",
    "description",
    "category",
    "input_schema",
    "output_schema",
    "execute_callback",
    "wp_ai_client_prompt",
    "wp_connectors_init",
    "wp_verify_nonce",
    "wordpress/mcp-adapter",
)

GENERIC_SURFACE_LABELS = (
    "add security",
    "block templates",
    "cache it",
    "do sanitization",
    "object cache",
    "run tests",
    "use capabilities",
    "use escaping",
    "use nonces",
    "use wordpress apis",
)

BANNED_UNSAFE_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bchmod\s+777\b",
    r"\bdrop\s+table\b",
    r"\bdelete\s+from\b",
    r"\bwp\s+db\s+reset\b",
    r"\bwp\s+site\s+empty\b",
)

FILE_PATH_RE = re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:`)?[a-z0-9_./-]+\.(?:php|js|jsx|ts|tsx|json|css|scss|md|txt|html)(?:`)?\b")
FILE_PATH_TOKEN_RE = re.compile(r"`([a-z0-9_./-]+\.(?:php|js|jsx|ts|tsx|json|css|scss|md|txt|html))`", re.IGNORECASE)
SECTION_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Check:
    id: str
    passed: bool
    weight: int
    detail: str


CONTRACTS: dict[str, dict[str, Any]] = {
    "plugin": {
        "headings": [
            "Spec Conformance",
            "Generated File Map",
            "Implementation Packets",
            "Security Notes",
            "Deviation Log",
            "Verification Notes",
            "Critic Handoff",
        ],
        "required_surfaces": ["current_user_can", "Plugin Check", "PHPCS", "PHPUnit"],
        "min_exact_surfaces": 4,
        "verification_terms": ["phpcs", "wpcs", "phpunit", "wp-cli", "plugin check"],
        "handoff_terms": ["wordpress-security-critic", "wordpress-critic"],
        "needs_file_map": True,
        "needs_json": False,
    },
    "block": {
        "headings": [
            "Spec Conformance",
            "Generated Block Files",
            "Compatibility Notes",
            "Security Performance And Accessibility Notes",
            "Deviation Log",
            "Verification Notes",
            "Critic Handoff",
        ],
        "required_surfaces": ["block.json", "register_block_type", "@wordpress/scripts"],
        "min_exact_surfaces": 4,
        "verification_terms": ["npm", "block validation", "editor smoke", "frontend smoke"],
        "handoff_terms": ["wordpress-critic", "wordpress-performance-critic"],
        "needs_file_map": True,
        "needs_json": False,
    },
    "blueprint": {
        "headings": [
            "Input Summary",
            "Generated Blueprint",
            "Provenance Notes",
            "Safety And Determinism Notes",
            "Deviation Log",
            "Verification Notes",
            "Critic Handoff",
        ],
        "required_surfaces": ["Playground", "Blueprint"],
        "min_exact_surfaces": 2,
        "verification_terms": ["blueprint schema", "playground", "smoke", "reset"],
        "handoff_terms": ["wordpress-critic"],
        "needs_file_map": False,
        "needs_json": True,
    },
}


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("->", " ")
    text = re.sub(r"[^a-z0-9_@./$*-]+", " ", text)
    return " ".join(text.split())


def _surface_present(surface: str, text: str) -> bool:
    normalized = _norm(text)
    tokens = [tok for tok in _norm(surface).split() if tok]
    return bool(tokens) and all(tok in normalized for tok in tokens)


def sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    out: dict[str, str] = {}
    for idx, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        out[name] = text[start:end].strip()
    return out


def check_headings(text: str, contract: dict[str, Any]) -> Check:
    found = set(sections(text))
    missing = [heading for heading in contract["headings"] if heading not in found]
    return Check(
        "required_headings",
        not missing,
        3,
        "all required headings present" if not missing else f"missing headings: {', '.join(missing)}",
    )


def check_packet_only(text: str, contract: dict[str, Any]) -> Check:
    expected = contract["headings"][0]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    issues: list[str] = []
    if first_line != f"## {expected}":
        issues.append(f"first non-empty line must be ## {expected}")
    if re.search(r"(?m)^##\s+Phase\b", text):
        issues.append("phase transcript headings are not allowed")
    if re.search(r"(?m)^##\s+(Deviations|Verification Commands|Quality Self-Check)\b", text):
        issues.append("renamed contract headings are not allowed")
    return Check(
        "packet_only_output",
        not issues,
        2,
        "packet starts with the required first heading and has no phase transcript" if not issues else "; ".join(issues),
    )


def check_file_map(text: str, contract: dict[str, Any]) -> Check:
    if not contract["needs_file_map"]:
        return Check("file_map", True, 1, "file map not required for this executor")
    found = list(FILE_PATH_RE.findall(text)) + FILE_PATH_TOKEN_RE.findall(text)
    return Check(
        "file_map",
        len(found) >= 2,
        2,
        f"{len(found)} file-like paths found" if found else "no file-like paths found",
    )


def check_exact_surfaces(text: str, contract: dict[str, Any]) -> Check:
    required = contract["required_surfaces"]
    missing = [surface for surface in required if not _surface_present(surface, text)]
    matched = [surface for surface in EXACT_SURFACES if _surface_present(surface, text)]
    generic_hits = [label for label in GENERIC_SURFACE_LABELS if label in text.lower()]
    min_exact = int(contract.get("min_exact_surfaces", 4))
    passed = not missing and len(set(matched)) >= min_exact and not generic_hits
    detail = f"matched {len(set(matched))} exact surfaces"
    if missing:
        detail += f"; missing required: {', '.join(missing)}"
    if generic_hits:
        detail += f"; generic labels present: {', '.join(generic_hits)}"
    return Check("exact_surfaces", passed, 3, detail)


# Model-readable hints describing HOW to satisfy each verification term. The pass/fail
# logic is unchanged (see verification_term_present); these only make the failure message
# actionable so weaker models know which line to add. A local coder repeatedly told
# "missing: wp-cli" never inferred the gate wanted a runnable `wp ...` command. The hint is
# emitted in the gate detail and relayed verbatim to the model by the repair loop.
VERIFICATION_TERM_HINTS = {
    "phpcs": "name a PHPCS run, e.g. `phpcs --standard=WordPress`",
    "wpcs": "reference the WordPress Coding Standards (WPCS) ruleset",
    "phpunit": "name a PHPUnit run, e.g. `phpunit` or `composer test`",
    "wp-cli": "add a runnable WP-CLI command line, e.g. `wp plugin activate <slug>`",
    "plugin check": "reference the Plugin Check (PCP) tool",
    "npm": "name an npm script, e.g. `npm run build`",
    "block validation": "reference block validation against the block.json schema",
    "editor smoke": "describe an editor smoke check (insert/edit the block in wp-admin)",
    "frontend smoke": "describe a frontend smoke check (render the block on a page)",
    "blueprint schema": "reference Blueprint JSON schema validation",
    "playground": "reference a WordPress Playground run",
    "smoke": "describe a smoke check that exercises the artifact",
    "reset": "describe a reset/teardown step for a reproducible run",
}


def check_verification(text: str, contract: dict[str, Any]) -> Check:
    lower = text.lower()
    missing = [term for term in contract["verification_terms"] if not verification_term_present(term, lower)]
    if missing:
        itemised = ", ".join(
            f"{term} ({VERIFICATION_TERM_HINTS[term]})" if term in VERIFICATION_TERM_HINTS else term
            for term in missing
        )
        detail = f"missing verification terms: {itemised}"
    else:
        detail = "verification terms present"
    return Check("verification_oracles", not missing, 3, detail)


def verification_term_present(term: str, lower_text: str) -> bool:
    if term in lower_text:
        return True
    if term == "wp-cli":
        return bool(re.search(r"(?m)^\s*(?:#.*\n)?\s*wp\s+[a-z0-9:_-]+", lower_text)) or "wp cli" in lower_text
    return False


def check_handoff(text: str, contract: dict[str, Any]) -> Check:
    lower = text.lower()
    missing = [term for term in contract["handoff_terms"] if term not in lower]
    return Check(
        "critic_handoff",
        not missing,
        2,
        "critic handoff names expected critics" if not missing else f"missing critic handoff terms: {', '.join(missing)}",
    )


def check_safety(text: str) -> Check:
    lower = text.lower()
    hits = [pattern for pattern in BANNED_UNSAFE_PATTERNS if re.search(pattern, lower)]
    secretish = re.search(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]{8,}", text)
    passed = not hits and secretish is None
    detail = "no banned destructive commands or literal secret assignments"
    if hits:
        detail = f"unsafe command patterns: {', '.join(hits)}"
    if secretish:
        detail += "; possible literal secret assignment"
    return Check("safety", passed, 3, detail)


def extract_blueprint_json(text: str) -> tuple[dict[str, Any] | None, str]:
    generated = sections(text).get("Generated Blueprint", text)
    for match in FENCE_RE.finditer(generated):
        candidate = match.group(1).strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, "parsed fenced JSON object"
    return None, "no parseable fenced JSON object"


def check_blueprint_json(text: str, contract: dict[str, Any]) -> Check:
    if not contract["needs_json"]:
        return Check("blueprint_json", True, 1, "Blueprint JSON not required for this executor")
    parsed, detail = extract_blueprint_json(text)
    if parsed is None:
        return Check("blueprint_json", False, 3, detail)
    steps = parsed.get("steps")
    passed = isinstance(steps, list) and len(steps) > 0
    return Check(
        "blueprint_json",
        passed,
        3,
        detail if passed else "Blueprint JSON parsed but missing non-empty steps array",
    )


def validate_packet(text: str, executor: str) -> dict[str, Any]:
    if executor not in CONTRACTS:
        raise ValueError(f"unknown executor `{executor}`")
    contract = CONTRACTS[executor]
    checks = [
        check_headings(text, contract),
        check_packet_only(text, contract),
        check_file_map(text, contract),
        check_exact_surfaces(text, contract),
        check_verification(text, contract),
        check_handoff(text, contract),
        check_safety(text),
        check_blueprint_json(text, contract),
    ]
    total_weight = sum(check.weight for check in checks)
    earned = sum(check.weight for check in checks if check.passed)
    score = earned / total_weight if total_weight else 0.0
    return {
        "executor": executor,
        "pass": all(check.passed for check in checks),
        "score": round(score, 4),
        "checks": [asdict(check) for check in checks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", required=True, choices=sorted(CONTRACTS))
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    text = args.packet.read_text(encoding="utf-8")
    result = validate_packet(text, args.executor)
    result["packet"] = str(args.packet)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "PASS" if result["pass"] else "FAIL"
        print(f"{status} {args.executor} packet contract score={result['score']}")
        for check in result["checks"]:
            marker = "ok" if check["passed"] else "FAIL"
            print(f"  - {marker} {check['id']}: {check['detail']}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
