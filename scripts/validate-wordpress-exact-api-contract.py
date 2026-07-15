#!/usr/bin/env python3
"""Validate the WordPress Exact API and Verification Contract.

This is a cheap deterministic guard for the improvement surfaced by the
answer-key diagnostics: WordPress skills must name exact remediation APIs,
surfaces, packages, commands, or verification oracles, and the eval rubrics must
not drift back to generic category labels that make API coverage look better
than it is.
"""

from __future__ import annotations

import json
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
DATA_DIR = ROOT / "evals" / "harness" / "data"
REGISTRY_PATH = DATA_DIR / "wp-exact-surfaces.json"
SYMBOLS_PATH = DATA_DIR / "wp-symbols.json"

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

CATEGORY_NAMES = {
    "hooks": "hook",
    "argument_keys": "argument_key",
    "capabilities": "capability",
    "wp_cli_commands": "wp_cli_command",
    "packages": "package",
    "named_oracles": "named_oracle",
    "file_surfaces": "file_glob",
    "reviewed_composed": "reviewed_composed",
}
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+\.(?:php|json|html|txt)$")
SAFE_BASENAMES = {"block.json", "render.php", ".wp-env.json", "theme.json"}


@dataclass(frozen=True)
class Issue:
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.path.relative_to(ROOT)}: {self.message}"


@dataclass(frozen=True)
class SurfaceRegistry:
    wp_version: str
    categories: dict[str, str]
    wildcard_hooks: tuple[str, ...]


@dataclass(frozen=True)
class InventoryItem:
    surface: str
    category: str | None
    paths: tuple[Path, ...]


def wordpress_agent_files() -> list[Path]:
    return sorted(AGENT_DIR.glob("wordpress-*.md"))


def wordpress_skill_files() -> list[Path]:
    return sorted(SKILL_DIR.glob("wordpress-*/SKILL.md"))


def normalized_surface(value: str) -> str:
    text = " ".join(str(value).strip().lower().split())
    return re.sub(r"\s*\(\)\s*$", "", text)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is malformed") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain an object")
    return data


def _entry_values(item: Any) -> tuple[str, tuple[str, ...]]:
    if isinstance(item, str):
        return item, ()
    if not isinstance(item, dict) or set(item) != {"name", "aliases"}:
        raise ValueError("surface registry entry is malformed")
    aliases = item.get("aliases")
    if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias.strip() for alias in aliases):
        raise ValueError("surface registry aliases are malformed")
    return item.get("name"), tuple(aliases)


def _safe_registry_file(value: str) -> bool:
    if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/"):
        return False
    if "*" in value:
        return bool(re.fullmatch(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*/\*\.(?:php|json|html|txt)", value))
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*\.(?:php|json|html|txt)", value))


def _valid_category_value(key: str, value: str) -> bool:
    if key == "file_surfaces":
        return _safe_registry_file(value)
    if key in {"hooks", "argument_keys", "capabilities"}:
        return bool(re.fullmatch(r"[a-z][a-z0-9_]+", value))
    if key == "packages":
        return bool(re.fullmatch(r"(?:@[a-z0-9_-]+|[a-z0-9_-]+)/[a-z0-9_-]+", value))
    if key == "wp_cli_commands":
        return value == "WP-CLI" or bool(re.fullmatch(r"wp [a-z0-9_-]+(?: [a-z0-9_.*:/-]+)*", value))
    return bool(value.isprintable() and len(value) <= 120 and ".." not in value)


def _registry_categories(data: dict[str, Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    categories = data.get("categories")
    expected = set(CATEGORY_NAMES) | {"wildcard_hooks"}
    if not isinstance(categories, dict) or set(categories) != expected:
        raise ValueError("surface registry categories are malformed")
    classified: dict[str, str] = {}
    for key, category in CATEGORY_NAMES.items():
        items = categories[key]
        if not isinstance(items, list):
            raise ValueError(f"surface registry category {key} is malformed")
        for item in items:
            name, aliases = _entry_values(item)
            if not isinstance(name, str) or not name.strip():
                raise ValueError("surface registry entry is malformed")
            for value in (name, *aliases):
                if not _valid_category_value(key, value):
                    raise ValueError(f"surface registry {key} entry is invalid: {value}")
                normalized = normalized_surface(value)
                if normalized in classified:
                    raise ValueError(f"duplicate surface registry entry: {value}")
                classified[normalized] = category
    wildcards = categories["wildcard_hooks"]
    if not isinstance(wildcards, list):
        raise ValueError("surface registry wildcard hooks are malformed")
    normalized_wildcards = tuple(normalized_surface(value) for value in wildcards if isinstance(value, str))
    if len(normalized_wildcards) != len(wildcards) or len(set(normalized_wildcards)) != len(wildcards):
        raise ValueError("duplicate or malformed wildcard hook")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*_\*", value) for value in normalized_wildcards):
        raise ValueError("surface registry wildcard hook is unsafe")
    return classified, normalized_wildcards


def load_surface_registry(path: Path = REGISTRY_PATH) -> SurfaceRegistry:
    data = _load_json(path, "surface registry")
    if data.get("schema_version") != 1:
        raise ValueError("unsupported surface registry schema")
    provenance = data.get("provenance")
    if not isinstance(data.get("boundary"), str) or not data["boundary"].strip():
        raise ValueError("surface registry boundary metadata is missing")
    if not isinstance(provenance, dict) or set(provenance) != {"reviewed_for", "reviewed_at"} or not all(
        isinstance(value, str) and value.strip() for value in provenance.values()
    ):
        raise ValueError("surface registry provenance metadata is malformed")
    symbols = _load_json(SYMBOLS_PATH, "WordPress symbol snapshot")
    if data.get("wp_version") != symbols.get("wp_version"):
        raise ValueError("surface registry WordPress version does not match symbol snapshot")
    categories, wildcards = _registry_categories(data)
    return SurfaceRegistry(data["wp_version"], categories, wildcards)


def _load_symbols() -> dict[str, Any]:
    symbols = _load_json(SYMBOLS_PATH, "WordPress symbol snapshot")
    if symbols.get("wp_version") != "7.0":
        raise ValueError("WordPress symbol snapshot version must be 7.0")
    if not isinstance(symbols.get("functions"), dict) or not isinstance(symbols.get("classes"), dict):
        raise ValueError("WordPress symbol snapshot is malformed")
    return symbols


def _safe_file_surface(text: str) -> bool:
    if "*" in text:
        return False
    if text in SAFE_BASENAMES:
        return True
    return bool(SAFE_PATH_RE.fullmatch(text) and ".." not in text.split("/"))


def classify_surface(
    value: str,
    registry: SurfaceRegistry | None = None,
    symbols: dict[str, Any] | None = None,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = normalized_surface(value)
    selected_registry = registry or load_surface_registry()
    selected_symbols = symbols or _load_symbols()
    if text in selected_symbols["functions"]:
        return "core_function"
    if text in selected_symbols["classes"]:
        return "core_class"
    if text in selected_registry.categories:
        return selected_registry.categories[text]
    for pattern in selected_registry.wildcard_hooks:
        prefix = pattern[:-1]
        if text == pattern or (text.startswith(prefix) and re.fullmatch(r"[a-z][a-z0-9_]+", text)):
            return "hook"
    return "file_glob" if _safe_file_surface(text) else None


def is_exact_surface(value: str) -> bool:
    return classify_surface(value) is not None


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


def validate_rubric(
    path: Path,
    registry: SurfaceRegistry | None = None,
    symbols: dict[str, Any] | None = None,
) -> list[Issue]:
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
        if classify_surface(api, registry, symbols) is None:
            issues.append(Issue(path, f"unclassified expected WordPress API/surface `{api}`"))
    return issues


def inventory_contract_surfaces() -> list[InventoryItem]:
    registry = load_surface_registry()
    symbols = _load_symbols()
    grouped: dict[str, list[Path]] = {}
    display: dict[str, str] = {}
    prompt_paths = tuple(wordpress_agent_files() + wordpress_skill_files())
    for surface in REQUIRED_CONTRACT_TOKENS:
        key = normalized_surface(surface)
        display.setdefault(key, surface)
        grouped.setdefault(key, []).extend(prompt_paths)
    for path in sorted(RUBRIC_DIR.glob("*.rubric.yaml")):
        signals = (load_yaml(path).get("domain_signals") or {})
        for surface in signals.get("expected_wordpress_apis") or []:
            if not isinstance(surface, str):
                continue
            key = normalized_surface(surface)
            display.setdefault(key, surface)
            grouped.setdefault(key, []).append(path)
    return [
        InventoryItem(display[key], classify_surface(display[key], registry, symbols), tuple(grouped[key]))
        for key in sorted(grouped)
    ]


def inventory_rubric_surfaces() -> list[InventoryItem]:
    """Backward-compatible name for the complete exact-surface inventory."""
    return inventory_contract_surfaces()


def validate_all() -> list[Issue]:
    issues: list[Issue] = []
    try:
        registry = load_surface_registry()
        symbols = _load_symbols()
    except ValueError as exc:
        return [Issue(REGISTRY_PATH, str(exc))]
    agent_files = wordpress_agent_files()
    skill_files = wordpress_skill_files()
    if len(agent_files) != 14:
        issues.append(Issue(AGENT_DIR, f"expected 14 WordPress agent files, found {len(agent_files)}"))
    if len(skill_files) != 14:
        issues.append(Issue(SKILL_DIR, f"expected 14 WordPress skill wrappers, found {len(skill_files)}"))
    for path in agent_files + skill_files:
        issues.extend(validate_prompt_contract(path))
    for token in REQUIRED_CONTRACT_TOKENS:
        if classify_surface(token, registry, symbols) is None:
            issues.append(Issue(REGISTRY_PATH, f"unclassified required contract surface `{token}`"))
    for path in sorted(RUBRIC_DIR.glob("*.rubric.yaml")):
        issues.extend(validate_rubric(path, registry, symbols))
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
