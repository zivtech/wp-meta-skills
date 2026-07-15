"""Regression tests for the WordPress Exact API contract validator."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load_validator():
    path = ROOT / "scripts" / "validate-wordpress-exact-api-contract.py"
    spec = importlib.util.spec_from_file_location("wordpress_exact_api_contract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def wordpress_surface_root() -> Path:
    monorepo_wordpress = ROOT / "wordpress-skills"
    if (monorepo_wordpress / ".claude").exists():
        return monorepo_wordpress
    return ROOT


def test_wordpress_exact_api_contract_validator_passes():
    result = subprocess.run(
        [sys.executable, "scripts/validate-wordpress-exact-api-contract.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wordpress_performance_critic_names_query_cache_boundaries():
    surface = wordpress_surface_root()
    paths = [
        surface / ".claude" / "agents" / "wordpress-performance-critic.md",
        surface / ".claude" / "skills" / "wordpress-performance-critic" / "SKILL.md",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "measurement is required before claiming production impact" in text
        assert "custom tables require scale evidence" in text


def test_all_live_rubric_surfaces_have_typed_classification():
    validator = load_validator()

    inventory = validator.inventory_contract_surfaces()
    unclassified = [item for item in inventory if item.category is None]

    assert unclassified == []
    assert len(inventory) >= 70
    assert {item.category for item in inventory} == {
        "argument_key",
        "capability",
        "core_class",
        "core_function",
        "file_glob",
        "hook",
        "named_oracle",
        "package",
        "reviewed_composed",
        "wp_cli_command",
    }


@pytest.mark.parametrize(
    "surface",
    [
        "invented_wordpress_magic",
        "wp_invented_magic",
        "security best practices",
        "cache performance issues",
        "wordpress api usage",
        "made up verification surface",
    ],
)
def test_shape_only_and_generic_surfaces_are_rejected(surface):
    validator = load_validator()

    assert validator.classify_surface(surface) is None


@pytest.mark.parametrize(
    ("surface", "category"),
    [
        ("current_user_can", "core_function"),
        ("WP_Query", "core_class"),
        ("wp_abilities_api_init", "hook"),
        ("wp_ajax_*", "hook"),
        ("permission_callback", "argument_key"),
        ("promote_users", "capability"),
        ("wp search-replace --dry-run", "wp_cli_command"),
        ("@wordpress/abilities", "package"),
        ("Query Monitor", "named_oracle"),
        ("register_rest_route permission_callback", "reviewed_composed"),
        ("parts/*.html", "file_glob"),
        ("plugin/includes/class-report.php", "file_glob"),
    ],
)
def test_reviewed_surface_categories_are_accepted(surface, category):
    validator = load_validator()

    assert validator.classify_surface(surface) == category


def test_registry_validation_rejects_duplicates_and_version_drift(tmp_path):
    validator = load_validator()
    source = json.loads(validator.REGISTRY_PATH.read_text(encoding="utf-8"))

    duplicate = json.loads(json.dumps(source))
    duplicate["categories"]["argument_keys"].append("permission_callback")
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        validator.load_surface_registry(duplicate_path)

    wrong_version = json.loads(json.dumps(source))
    wrong_version["wp_version"] = "6.9"
    wrong_version_path = tmp_path / "wrong-version.json"
    wrong_version_path.write_text(json.dumps(wrong_version), encoding="utf-8")
    with pytest.raises(ValueError, match="WordPress version"):
        validator.load_surface_registry(wrong_version_path)

    with pytest.raises(ValueError, match="not found"):
        validator.load_surface_registry(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "surface",
    ["security best practices", "../outside.php", "*", "wp_ajax_evil*"],
)
def test_registry_rejects_unsafe_file_category_entries(tmp_path, surface):
    validator = load_validator()
    data = json.loads(validator.REGISTRY_PATH.read_text(encoding="utf-8"))
    data["categories"]["file_surfaces"].append(surface)
    path = tmp_path / "unsafe-file-surface.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="file_surfaces entry is invalid"):
        validator.load_surface_registry(path)


def test_registry_rejects_unsafe_wildcard_hook(tmp_path):
    validator = load_validator()
    data = json.loads(validator.REGISTRY_PATH.read_text(encoding="utf-8"))
    data["categories"]["wildcard_hooks"].append("wp_ajax_evil*")
    path = tmp_path / "unsafe-wildcard.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="wildcard hook is unsafe"):
        validator.load_surface_registry(path)


@pytest.mark.parametrize("field", ["boundary", "provenance"])
def test_registry_requires_boundary_and_provenance_metadata(tmp_path, field):
    validator = load_validator()
    data = json.loads(validator.REGISTRY_PATH.read_text(encoding="utf-8"))
    data.pop(field)
    path = tmp_path / "missing-metadata.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        validator.load_surface_registry(path)
