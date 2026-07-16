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
import functools
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "evals" / "harness" / "data"
REGISTRY_PATH = DATA_DIR / "wp-exact-surfaces.json"
SYMBOLS_PATH = DATA_DIR / "wp-symbols.json"

VERDICTS = {"REJECT", "REVISE", "ACCEPT-WITH-RESERVATIONS", "ACCEPT"}
CATEGORY_NAMES = {
    "hooks": "hook", "wildcard_hooks": "hook", "argument_keys": "argument_key",
    "capabilities": "capability", "wp_cli_commands": "wp_cli_command",
    "packages": "package", "named_oracles": "named_oracle",
    "file_surfaces": "file_glob", "reviewed_composed": "reviewed_composed",
}
CONTEXTUAL_ARGUMENT_KEYS = frozenset({"category", "description", "label"})
IDENTIFIER_CATEGORIES = frozenset({"hook", "argument_key", "capability", "reviewed_composed"})

VERIFICATION_TERMS = (
    "apm", "block validation", "browser devtools", "browser performance trace",
    "core web vitals", "crawl comparison", "database query logs", "dry run", "dry-run",
    "editor smoke", "explain select", "frontend smoke", "import-log", "launch rehearsal",
    "network panel", "object-cache metrics", "php -l", "phpcs", "phpstan", "phpunit",
    "playground", "playwright", "plugin check", "psalm", "query monitor", "redirect map",
    "rollback test", "screaming frog", "site editor", "theme check", "wp cli",
    "wp cron event list", "wp-env", "wp media import", "wp option list", "wp post list",
    "wp profile", "wp redirection", "wp rewrite flush", "wp rewrite list", "wp search-replace",
    "wpcs", "security-gate.json", "phpcs-suppression-diff", "--ignore-annotations",
    "suppressed_annotations",
)

NEGATIVE_SPACE_TERMS = (
    "does not prove", "does not claim", "is not claimed", "not claimed", "not claiming",
    "not proven", "outside scope", "out of scope", "negative space", "cannot verify",
    "assumption", "open question", "unknown",
)

PLACEHOLDER_RE = re.compile(r"(\b(TBD|TODO|FIXME|PLACEHOLDER)\b|\[(?i:finding|todo|placeholder)\])")
GENERIC_LABELS = (
    "add security", "check accessibility", "ensure performance", "fix the issue", "run tests",
    "use capabilities", "use escaping", "use nonces", "use wordpress apis",
)

MD_HEADING_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
BOLD_HEADING_RE = re.compile(r"(?m)^\*\*(.+?)\*\*\s*$")
VERDICT_RE = re.compile(r"(?im)^\*\*VERDICT:\s*([A-Z-]+).*?\*\*")


PLANNER_HEADINGS = {
    "wordpress-planner": [
        "Scope Summary", "Current-State Evidence", "Architecture Plan",
        "WordPress-Specific Decisions", "Assumption Register", "Test And Verification Strategy",
        "Implementation Sequence", "Executor Handoff", "Critic Checkpoints", "Acceptance Criteria",
        "Assumptions And Open Questions",
    ],
    "wordpress-plugin-planner": [
        "Plugin Scope", "Current-State Evidence",
        "Architecture And File Map", "Hook And Data Flow",
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


@dataclass(frozen=True)
class RegisteredSurface:
    name: str
    category: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceMatch:
    name: str
    category: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class SurfaceCatalog:
    registered: tuple[RegisteredSurface, ...]
    functions: frozenset[str]
    classes: frozenset[str]


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("->", " ")
    text = re.sub(r"[^a-z0-9_@./$*-]+", " ", text)
    return " ".join(text.split())


def _entry(item: Any) -> tuple[str, tuple[str, ...]]:
    if isinstance(item, str) and item.strip():
        return item, ()
    if isinstance(item, dict) and set(item) == {"name", "aliases"}:
        aliases = item.get("aliases")
        if isinstance(item.get("name"), str) and isinstance(aliases, list) and all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            return item["name"], tuple(aliases)
    raise ValueError("malformed exact-surface registry entry")


def _registry_value_valid(key: str, value: str) -> bool:
    if key == "wildcard_hooks":
        return bool(re.fullmatch(r"[a-z][a-z0-9_]*_\*", value))
    if key == "file_surfaces":
        if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/"):
            return False
        grammar = r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*(?:/\*)?\.(?:php|json|html|txt)"
        return bool(re.fullmatch(grammar, value))
    if key in {"hooks", "argument_keys", "capabilities"}:
        return bool(re.fullmatch(r"[a-z][a-z0-9_]+", value))
    if key == "packages":
        return bool(re.fullmatch(r"(?:@[a-z0-9_-]+|[a-z0-9_-]+)/[a-z0-9_-]+", value))
    if key == "wp_cli_commands":
        return value == "WP-CLI" or bool(re.fullmatch(r"wp [a-z0-9_-]+(?: [a-z0-9_.*:/-]+)*", value))
    return value.isprintable() and len(value) <= 120 and ".." not in value


@functools.lru_cache(maxsize=1)
def _surface_catalog() -> SurfaceCatalog:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        symbols = json.loads(SYMBOLS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("exact-surface registry or symbol snapshot is unavailable") from exc
    if registry.get("schema_version") != 1 or registry.get("wp_version") != symbols.get("wp_version"):
        raise ValueError("exact-surface registry version is incompatible")
    provenance = registry.get("provenance")
    if not isinstance(registry.get("boundary"), str) or not registry["boundary"].strip():
        raise ValueError("exact-surface registry boundary metadata is missing")
    if not isinstance(provenance, dict) or set(provenance) != {"reviewed_for", "reviewed_at"} or not all(
        isinstance(value, str) and value.strip() for value in provenance.values()
    ):
        raise ValueError("exact-surface registry provenance metadata is malformed")
    categories = registry.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(CATEGORY_NAMES):
        raise ValueError("exact-surface registry categories are malformed")
    registered: list[RegisteredSurface] = []
    seen: set[str] = set()
    for key, category in CATEGORY_NAMES.items():
        if not isinstance(categories[key], list):
            raise ValueError("exact-surface registry category is malformed")
        for item in categories[key]:
            name, aliases = _entry(item)
            if not all(_registry_value_valid(key, value) for value in (name, *aliases)):
                raise ValueError(f"invalid exact-surface registry {key} entry")
            normalized = {_norm(value) for value in (name, *aliases)}
            if "" in normalized or seen & normalized:
                raise ValueError("duplicate exact-surface registry entry")
            seen.update(normalized)
            registered.append(RegisteredSurface(name, category, aliases))
    functions, classes = symbols.get("functions"), symbols.get("classes")
    if not isinstance(functions, dict) or not isinstance(classes, dict):
        raise ValueError("WordPress symbol snapshot is malformed")
    return SurfaceCatalog(tuple(registered), frozenset(functions), frozenset(classes))


def _surface_pattern(value: str, functions: frozenset[str], category: str) -> re.Pattern[str]:
    pieces = []
    for piece in value.strip().split():
        token = re.escape(piece)
        if piece.lower() in functions or "->" in piece:
            token += r"(?:\s*\(\s*\))?"
        pieces.append(token)
    body = r"\s+".join(pieces)
    left = r"(?<![A-Za-z0-9_$@>:])" if category in IDENTIFIER_CATEGORIES else r"(?<![A-Za-z0-9_])"
    return re.compile(rf"{left}{body}(?![A-Za-z0-9_])", re.IGNORECASE)


def _unsafe_php_context(text: str, start: int) -> bool:
    prefix = text[max(0, start - 128):start]
    return bool(re.search(r"(?:\?->|->|::|@)\s*$", prefix))


def _has_global_rest_route(sentence: str) -> bool:
    pattern = r"(?<![A-Za-z0-9_$@>:])register_rest_route(?:\s*\(\s*\))?(?![A-Za-z0-9_])"
    return any(not _unsafe_php_context(sentence, match.start()) for match in re.finditer(pattern, sentence, re.I))


def _registered_match_allowed(surface: RegisteredSurface, text: str, match: re.Match[str]) -> bool:
    sentence_start = max(text.rfind(mark, 0, match.start()) for mark in ".!?\n") + 1
    sentence_end_candidates = [text.find(mark, match.end()) for mark in ".!?\n"]
    sentence_end = min((value for value in sentence_end_candidates if value >= 0), default=len(text))
    sentence = text[sentence_start:sentence_end]
    if surface.category in IDENTIFIER_CATEGORIES and _unsafe_php_context(text, match.start()):
        return False
    before = text[match.start() - 1] if match.start() else ""
    after = text[match.end()] if match.end() < len(text) else ""
    if surface.name.lower() == "wp-env" and (before in "./\\-" or after in "./\\-"):
        return False
    quoted = before in "`'\"" and after == before
    assigned = bool(re.match(r"\s*(?::|=>)", text[match.end():]))
    key_context = quoted or assigned
    if surface.name.lower() == "permission_callback" and not (key_context or _has_global_rest_route(sentence)):
        return False
    if surface.category != "argument_key" or surface.name.lower() not in CONTEXTUAL_ARGUMENT_KEYS:
        return True
    return key_context


def _candidate_matches(text: str, catalog: SurfaceCatalog) -> list[SurfaceMatch]:
    matches: list[SurfaceMatch] = []
    token_re = re.compile(
        r"(?<![A-Za-z0-9_$@>:\\./-])([A-Za-z_][A-Za-z0-9_\\]*)(?:\s*\(\s*\))?"
        r"(?![A-Za-z0-9_\\/-]|\.[A-Za-z0-9])"
    )
    for match in token_re.finditer(text):
        if _unsafe_php_context(text, match.start()):
            continue
        name = match.group(1).lower()
        category = "core_function" if name in catalog.functions else "core_class" if name in catalog.classes else None
        if category:
            matches.append(SurfaceMatch(name, category, match.group(0), match.start(), match.end()))
    for surface in catalog.registered:
        for alias in (surface.name, *surface.aliases):
            for match in _surface_pattern(alias, catalog.functions, surface.category).finditer(text):
                if _registered_match_allowed(surface, text, match):
                    matches.append(SurfaceMatch(surface.name, surface.category, match.group(0), match.start(), match.end()))
        if surface.category == "hook" and surface.name.endswith("*"):
            pattern = re.compile(rf"(?<![A-Za-z0-9_$@>:]){re.escape(surface.name[:-1])}[a-z0-9_]+(?![A-Za-z0-9_])", re.I)
            for match in pattern.finditer(text):
                if not _unsafe_php_context(text, match.start()):
                    matches.append(SurfaceMatch(match.group(0), "hook", match.group(0), match.start(), match.end()))
    path_re = re.compile(r"(?<![A-Za-z0-9_./-])(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+\.(?:php|json|html|txt)(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])")
    for match in path_re.finditer(text):
        if ".." not in match.group(0).split("/"):
            matches.append(SurfaceMatch(match.group(0), "file_glob", match.group(0), match.start(), match.end()))
    basename_re = re.compile(
        r"(?<![A-Za-z0-9_./-])(?<!\\)(?:render\.php|\.wp-env\.json)(?![A-Za-z0-9_./-])(?!\\)",
        re.I,
    )
    for match in basename_re.finditer(text):
        matches.append(SurfaceMatch(match.group(0), "file_glob", match.group(0), match.start(), match.end()))
    return matches


def find_surface_matches(text: str) -> tuple[SurfaceMatch, ...]:
    candidates = sorted(_candidate_matches(text, _surface_catalog()), key=lambda item: (item.start, -(item.end - item.start)))
    accepted: list[SurfaceMatch] = []
    names: set[tuple[str, str]] = set()
    for candidate in candidates:
        if any(candidate.start >= item.start and candidate.end <= item.end for item in accepted):
            continue
        identity = (candidate.category, candidate.name.lower())
        if identity not in names:
            accepted.append(candidate)
            names.add(identity)
    return tuple(accepted)


def _non_applicability(text: str) -> tuple[int, bool]:
    statements = re.findall(r"[^.!?]*no exact wordpress api applies[^.!?]*[.!?]?", text, re.IGNORECASE)
    if not statements:
        return 0, True
    for statement in statements:
        lower = " ".join(statement.lower().split())
        scope = re.search(r"applies\s+to\s+(.+?)(?=\s+(?:because|since|as)\b|[;,]|$)", lower)
        scope_words = re.findall(r"[a-z0-9]+", scope.group(1)) if scope else []
        generic = {"foo", "bar", "thing", "things", "this", "that", "work", "problem"}
        named = len(scope_words) >= 2 and not set(scope_words) <= generic
        reason_match = re.search(r"\b(?:because|since|as)\b(.+?)(?=;|$)", lower)
        reason_text = reason_match.group(1) if reason_match else ""
        reason = len(reason_text.split()) >= 4 and bool(re.search(
            r"wordpress.+(?:not|cannot|outside)|(?:external|vendor|owned|controlled)|system of record", reason_text
        ))
        oracle = bool(re.search(
            r"\b(?!(?:the|a|an)\s)[a-z0-9_-]+\s+owner\b|vendor api(?: contract)?|system of record|(?:vendor|integration) (?:documentation|runbook)",
            lower,
        ))
        if not (named and reason and oracle):
            return len(statements), False
    return len(statements), True


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
    matched = find_surface_matches(text)
    note_count, valid_notes = _non_applicability(text)
    min_surfaces = int(contract["min_surfaces"])
    passed = len(matched) >= min_surfaces and valid_notes
    evidence = ", ".join(f"{item.category}:{item.text}" for item in matched)
    detail = f"matched {len(matched)} exact WordPress surfaces"
    if evidence:
        detail += f" ({evidence})"
    if note_count and valid_notes:
        detail += "; scoped non-applicability includes subproblem, reason, and oracle/owner"
    elif note_count:
        detail += "; invalid non-applicability (requires named subproblem, reason, and oracle/owner)"
    if len(matched) < min_surfaces:
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
