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


def _prompt_paths(identity: str) -> list[Path]:
    """Return the agent file and skill wrapper for a prompt identity."""
    surface = wordpress_surface_root()
    return [
        p
        for p in (
            surface / ".claude" / "agents" / f"{identity}.md",
            surface / ".claude" / "skills" / identity / "SKILL.md",
        )
        if p.is_file()
    ]


def test_prompt_specific_tokens_are_required_where_mapped():
    """The block and theme planners must carry their own extra surfaces."""
    validator = load_validator()

    for identity, tokens in validator.PROMPT_CONTRACT_TOKENS.items():
        paths = _prompt_paths(identity)
        assert paths, f"PROMPT_CONTRACT_TOKENS names a prompt with no files: {identity}"
        for path in paths:
            text = path.read_text(encoding="utf-8")
            missing = [token for token in tokens if token not in text]
            assert not missing, f"{path} is missing {missing}"


def test_prompt_specific_tokens_do_not_leak_into_unmapped_prompts():
    """The whole point of the per-prompt layer: it must not dilute the rest.

    A prompt absent from PROMPT_CONTRACT_TOKENS is held to the global list
    alone. Without this, the block editor's SlotFill and format-registration
    APIs would become a requirement on the migration planner and the security
    critic, which is the dilution the design exists to avoid.
    """
    validator = load_validator()

    mapped = set(validator.PROMPT_CONTRACT_TOKENS)
    unmapped = [
        path
        for path in validator.wordpress_agent_files() + validator.wordpress_skill_files()
        if validator._prompt_identity(path) not in mapped
        and validator._prompt_identity(path) not in validator.PROBER_PROMPTS
    ]
    assert len(unmapped) >= 10, "expected most prompts to be unmapped"

    for path in unmapped:
        issues = validator.validate_prompt_contract(path)
        leaked = [i for i in issues if "prompt-specific" in i.message]
        assert not leaked, f"{path} was held to a prompt-specific token: {leaked}"


def test_prompt_specific_requirement_is_live_not_decorative(monkeypatch):
    """Prove the mechanism fires: map an unmapped prompt, watch it fail."""
    validator = load_validator()

    victim = next(
        path
        for path in validator.wordpress_skill_files()
        if validator._prompt_identity(path) not in validator.PROMPT_CONTRACT_TOKENS
        and validator._prompt_identity(path) not in validator.PROBER_PROMPTS
    )
    identity = validator._prompt_identity(victim)

    assert not [
        i for i in validator.validate_prompt_contract(victim) if "prompt-specific" in i.message
    ]

    monkeypatch.setitem(
        validator.PROMPT_CONTRACT_TOKENS, identity, ("PluginDocumentSettingPanel",)
    )
    issues = [
        i for i in validator.validate_prompt_contract(victim) if "prompt-specific" in i.message
    ]
    assert len(issues) == 1, f"expected the mapped token to be required on {identity}"
    assert "PluginDocumentSettingPanel" in issues[0].message


@pytest.mark.parametrize(
    ("identity", "tokens", "expected"),
    [
        ("wordpress-planner.no-such-skill", ("theme.json",), "unknown prompt"),
        ("wordpress-planner.block", ("block editor best practices",), "not an exact surface"),
        ("wordpress-environment-probe", ("theme.json",), "prober prompt"),
        ("wordpress-planner.block", (), "is empty"),
    ],
)
def test_prompt_contract_mapping_rejects_bad_entries(monkeypatch, identity, tokens, expected):
    """A typo or a generic label must fail the gate, not silently disable it."""
    validator = load_validator()

    monkeypatch.setattr(validator, "PROMPT_CONTRACT_TOKENS", {identity: tokens})
    paths = validator.wordpress_agent_files() + validator.wordpress_skill_files()
    issues = validator.validate_prompt_contract_mapping(paths)

    assert any(expected in issue.message for issue in issues), [i.message for i in issues]


@pytest.mark.parametrize(
    ("surface", "category"),
    [
        ("allowed_block_types_all", "hook"),
        ("render_block_*", "hook"),
        ("render_block_navigation", "hook"),
        ("@wordpress/rich-text", "package"),
        ("@wordpress/plugins", "package"),
        ("@wordpress/hooks", "package"),
        ("templateLock", "reviewed_composed"),
        ("registerFormatType", "reviewed_composed"),
        ("registerPlugin", "reviewed_composed"),
        ("PluginDocumentSettingPanel", "reviewed_composed"),
        ("PluginSidebar", "reviewed_composed"),
        ("fontFamilies", "reviewed_composed"),
        ("fontFace", "reviewed_composed"),
        ("blocks.registerBlockType", "reviewed_composed"),
        ("editor.BlockEdit", "reviewed_composed"),
        ("core/navigation", "reviewed_composed"),
    ],
)
def test_block_editor_surfaces_classify(surface, category):
    validator = load_validator()

    assert validator.classify_surface(surface) == category


def test_registry_boundary_states_the_third_party_rule():
    """The boundary is where someone widening the registry will be reading.

    The recurring error this guards against: a rubric names a symbol that only
    exists in a third-party implementation of a WordPress API, the classifier
    correctly rejects it, and the tempting fix is to add it here. That converts
    a category error into a permanent false claim about what WordPress provides.
    The classifier already enforces this by construction; the boundary says so
    where the mistake would be made.
    """
    validator = load_validator()
    boundary = json.loads(validator.REGISTRY_PATH.read_text(encoding="utf-8"))["boundary"]

    assert "third-party implementation" in boundary
    assert "must not be added here" in boundary


def test_third_party_implementation_symbols_do_not_classify():
    """Names belonging to a library built on WordPress APIs are not surfaces."""
    validator = load_validator()

    for symbol in (
        "registerBlockExtension",   # @10up/block-components, not core
        "registerProvider",         # AI Client registry method, not a WordPress symbol
        "defaultRegistry",
        "ProviderAvailabilityInterface",
    ):
        assert validator.classify_surface(symbol) is None, symbol

    # The official surfaces those are reached through DO classify, which is the
    # point: name the WordPress API, not the implementation detail on top of it.
    assert validator.classify_surface("WordPress\\AiClient\\AiClient") == "core_class"
    assert validator.classify_surface("wp_ai_client_prompt") == "core_function"
