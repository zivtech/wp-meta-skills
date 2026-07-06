#!/usr/bin/env python3
"""Validate the WordPress Exact API and Verification Contract.

This is a cheap deterministic guard for the improvement surfaced by the
answer-key diagnostics: WordPress skills must name exact remediation APIs,
surfaces, packages, commands, or verification oracles, and the eval rubrics must
not drift back to generic category labels that make API coverage look better
than it is.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent
MONOREPO_WORDPRESS = ROOT / "wordpress-skills"
WORDPRESS = MONOREPO_WORDPRESS if (MONOREPO_WORDPRESS / ".claude").exists() else ROOT
AGENT_DIR = WORDPRESS / ".claude" / "agents"
SKILL_DIR = WORDPRESS / ".claude" / "skills"
RUBRIC_DIR = ROOT / "evals" / "suites" / "wordpress-skill-candidate-eval" / "rubrics"

CONTRACT_HEADING_RE = re.compile(
    r"(Exact API (And|and) Verification Contract|<Exact_API_Contract>)"
)
REQUIRED_CONTRACT_TOKENS = (
    "current_user_can",
    "permission_callback",
    "$wpdb->prepare",
    "sanitize_key",
    "wp_kses_post",
    "block.json",
    "register_block_type",
    "theme.json",
    "register_post_type",
    "WP_Query",
    "wp_cache_get",
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
    "@wordpress/abilities",
    "wordpress/mcp-adapter",
    "mcp_adapter_init",
    "mcp-adapter-discover-abilities",
    "mcp-adapter-execute-ability",
    "Query Monitor",
    "Plugin Check",
    "PHPCS/WPCS",
    "PHPUnit",
    "Playwright",
)

BANNED_GENERIC_API_LABELS = {
    "activation/deactivation hooks",
    "block templates",
    "capabilities and rollout checkpoints",
    "deprecated",
    "object cache",
    "patterns",
    "plugin/theme/block boundary language",
    "redirect mapping",
    "style variations",
    "template parts",
    "transients",
    "wp-cli dry-run guidance",
    "wp-cron",
}

ALLOWED_NAMED_SURFACES = {
    "acf field groups",
    "action scheduler",
    "admin-ajax.php",
    "block.json",
    "deprecated block versions",
    "plugin check",
    "query monitor",
    "readme.txt stable tag",
    "theme.json",
    "uninstall.php",
    "wordpress/mcp-adapter",
    "mcp-adapter-discover-abilities",
    "mcp-adapter-execute-ability",
    "wp-cli",
    "wp ai client",
    "$wpdb->prepare",
}

SURFACE_PATTERNS = (
    re.compile(r"^[a-z][a-z0-9_]+$"),  # functions, hooks, args, callbacks
    re.compile(r"^[a-z][a-z0-9_]+/[a-z][a-z0-9_]+$"),  # paired APIs
    re.compile(r"^wp [a-z0-9:_-]+(?: [a-z0-9:_./*-]+)*$"),  # WP-CLI commands
    re.compile(r"^@[a-z0-9_-]+/[a-z0-9_-]+$"),  # npm packages
    re.compile(r"^[a-z0-9_./*-]+\.(php|json|html|txt)$"),  # files/globs
    re.compile(r"^[a-z0-9_]+(?: [a-z0-9_]+){1,3}$"),  # composed exact surfaces
)


@dataclass(frozen=True)
class Issue:
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.path.relative_to(ROOT)}: {self.message}"


def wordpress_agent_files() -> list[Path]:
    return sorted(AGENT_DIR.glob("wordpress-*.md"))


def wordpress_skill_files() -> list[Path]:
    return sorted(SKILL_DIR.glob("wordpress-*/SKILL.md"))


def normalized_surface(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def is_exact_surface(value: str) -> bool:
    text = normalized_surface(value)
    if text in ALLOWED_NAMED_SURFACES:
        return True
    if text in BANNED_GENERIC_API_LABELS:
        return False
    return any(pattern.match(text) for pattern in SURFACE_PATTERNS)


def validate_prompt_contract(path: Path) -> list[Issue]:
    text = path.read_text(encoding="utf-8")
    issues: list[Issue] = []
    if not CONTRACT_HEADING_RE.search(text):
        issues.append(Issue(path, "missing Exact API and Verification Contract heading"))
        return issues
    for token in REQUIRED_CONTRACT_TOKENS:
        if token not in text:
            issues.append(Issue(path, f"contract missing required token `{token}`"))
    if "If no exact WordPress API applies" not in text:
        issues.append(Issue(path, "contract missing no-exact-API fallback language"))
    return issues


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def validate_rubric(path: Path) -> list[Issue]:
    data = load_yaml(path)
    signals = data.get("domain_signals") or {}
    apis = signals.get("expected_wordpress_apis") or []
    issues: list[Issue] = []
    if not isinstance(apis, list) or not apis:
        issues.append(Issue(path, "domain_signals.expected_wordpress_apis must be a non-empty list"))
        return issues
    for api in apis:
        if not isinstance(api, str) or not api.strip():
            issues.append(Issue(path, "expected_wordpress_apis contains a blank or non-string entry"))
            continue
        if not is_exact_surface(api):
            issues.append(Issue(path, f"generic expected WordPress API/surface label `{api}`"))
    return issues


def validate_all() -> list[Issue]:
    issues: list[Issue] = []
    agent_files = wordpress_agent_files()
    skill_files = wordpress_skill_files()
    if len(agent_files) != 14:
        issues.append(Issue(AGENT_DIR, f"expected 14 WordPress agent files, found {len(agent_files)}"))
    if len(skill_files) != 14:
        issues.append(Issue(SKILL_DIR, f"expected 14 WordPress skill wrappers, found {len(skill_files)}"))
    for path in agent_files + skill_files:
        issues.extend(validate_prompt_contract(path))
    for path in sorted(RUBRIC_DIR.glob("*.rubric.yaml")):
        issues.extend(validate_rubric(path))
    return issues


def main() -> int:
    issues = validate_all()
    if issues:
        print("WordPress Exact API contract issues:")
        for issue in issues:
            print(f"  - {issue.render()}")
        return 1
    print("WordPress Exact API contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
