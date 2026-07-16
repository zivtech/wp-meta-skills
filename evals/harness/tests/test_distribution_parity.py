import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = PROJECT_ROOT / "scripts/validate-distribution-parity.py"
SURFACES = (
    ".claude/skills",
    ".agents/skills",
    ".claude/agents",
    ".codex/agents",
)
AGENT_NAMES = (
    "wordpress-block-executor",
    "wordpress-block-planner",
    "wordpress-blueprint-executor",
    "wordpress-content-model-planner",
    "wordpress-critic",
    "wordpress-migration-planner",
    "wordpress-performance-critic",
    "wordpress-planner",
    "wordpress-plugin-executor",
    "wordpress-plugin-planner",
    "wordpress-security-critic",
    "wordpress-theme-critic",
    "wordpress-theme-executor",
    "wordpress-theme-planner",
)


def _copy_surfaces(tmp_path: Path) -> Path:
    root = tmp_path / "distribution"
    root.mkdir()
    for relative in SURFACES:
        shutil.copytree(PROJECT_ROOT / relative, root / relative)
    shutil.copy2(PROJECT_ROOT / "skills.sh.json", root / "skills.sh.json")
    return root


def _copy_install_tree(tmp_path: Path) -> Path:
    root = _copy_surfaces(tmp_path)
    (root / "scripts").mkdir()
    shutil.copy2(VALIDATOR, root / "scripts/validate-distribution-parity.py")
    shutil.copy2(PROJECT_ROOT / "install.sh", root / "install.sh")
    shutil.copy2(PROJECT_ROOT / "MANIFEST.sha256", root / "MANIFEST.sha256")
    return root


def _install(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    home = root.parent / "synthetic-home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        ["/bin/bash", str(root / "install.sh"), *args],
        cwd=root,
        env={
            "HOME": str(home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LC_ALL": "C",
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _load_validator():
    spec = importlib.util.spec_from_file_location("distribution_parity", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_failure(root: Path, *needles: str) -> str:
    result = _run(root)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    for needle in needles:
        assert needle in output
    return output


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _skill_paths(root: Path, name: str) -> tuple[Path, Path]:
    relative = Path(name) / "SKILL.md"
    return root / ".claude/skills" / relative, root / ".agents/skills" / relative


def _agent_paths(root: Path, name: str) -> tuple[Path, Path]:
    return (
        root / ".claude/agents" / f"{name}.md",
        root / ".codex/agents" / f"{name}.toml",
    )


def test_live_distribution_is_connected_and_exact() -> None:
    result = _run(PROJECT_ROOT)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "14 skill pairs" in result.stdout
    assert "14 agent pairs" in result.stdout
    assert "14 skills.sh entries" in result.stdout


@pytest.mark.parametrize("surface", [".claude/skills", ".agents/skills"])
def test_missing_skill_fails(tmp_path: Path, surface: str) -> None:
    root = _copy_surfaces(tmp_path)
    shutil.rmtree(root / surface / "wordpress-planner")

    _assert_failure(root, surface, "inventory")


@pytest.mark.parametrize("surface", [".claude/agents", ".codex/agents"])
def test_extra_agent_fails(tmp_path: Path, surface: str) -> None:
    root = _copy_surfaces(tmp_path)
    suffix = ".md" if surface == ".claude/agents" else ".toml"
    source = root / surface / f"wordpress-critic{suffix}"
    shutil.copy2(source, root / surface / f"wordpress-extra{suffix}")

    _assert_failure(root, surface, "inventory")


def test_skill_body_drift_fails(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    path = root / ".agents/skills/wordpress-planner/SKILL.md"
    _replace(path, "# WordPress Planner", "# Drifted WordPress Planner")

    _assert_failure(root, str(path.relative_to(root)), "body")


def test_lone_carriage_returns_are_not_normalized_as_newlines(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    for path in _skill_paths(root, "wordpress-planner"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r"))

    _assert_failure(root, "wordpress-planner", "parse")


def test_inner_lone_carriage_return_drift_fails(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    for path in _skill_paths(root, "wordpress-planner"):
        encoded = path.read_bytes()
        old = b"\n    Phase 1 - Repository and runtime triage"
        assert old in encoded
        path.write_bytes(encoded.replace(old, old.replace(b"\n", b"\r"), 1))

    _assert_failure(root, "wordpress-planner", "Protocol")


def test_inner_blank_shared_record_fails(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    for path in _skill_paths(root, "wordpress-planner"):
        _replace(
            path,
            "\n    Phase 1 - Repository and runtime triage",
            "\n\n    Phase 1 - Repository and runtime triage",
        )

    _assert_failure(root, "wordpress-planner", "Protocol")


def test_model_family_drift_fails(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    path = root / ".agents/skills/wordpress-planner/SKILL.md"
    _replace(path, "Codex-fable-5", "Codex-sonnet-4-6")

    _assert_failure(root, str(path.relative_to(root)), "model")


@pytest.mark.parametrize("field", ["description", "developer_instructions"])
def test_codex_agent_drift_fails(tmp_path: Path, field: str) -> None:
    root = _copy_surfaces(tmp_path)
    path = root / ".codex/agents/wordpress-planner.toml"
    old = "WordPress" if field == "description" else "<Role>"
    new = "Drifted WordPress" if field == "description" else "<Drifted_Role>"
    _replace(path, old, new)

    _assert_failure(root, str(path.relative_to(root)), field)


def test_paired_agent_name_must_match_inventory(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    for path in _agent_paths(root, "wordpress-planner"):
        _replace(path, "wordpress-planner", "wrong-agent")

    _assert_failure(root, "wordpress-planner.md", "name does not match inventory")


@pytest.mark.parametrize("mutation", ["duplicate", "omitted", "wrong_group"])
def test_skills_sh_membership_and_group_fails(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = _copy_surfaces(tmp_path)
    path = root / "skills.sh.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    planning = data["groupings"][0]["skills"]
    if mutation == "duplicate":
        planning.append(planning[0])
    elif mutation == "omitted":
        planning.pop()
    else:
        data["groupings"][1]["skills"].append(planning.pop())
    path.write_text(json.dumps(data), encoding="utf-8")

    _assert_failure(root, "skills.sh.json", "group")


@pytest.mark.parametrize("kind", ["yaml", "toml", "json"])
def test_parser_invalid_surface_fails(tmp_path: Path, kind: str) -> None:
    root = _copy_surfaces(tmp_path)
    if kind == "yaml":
        path = root / ".claude/skills/wordpress-planner/SKILL.md"
        path.write_text("---\nname: [\n---\nbody\n", encoding="utf-8")
    elif kind == "toml":
        path = root / ".codex/agents/wordpress-planner.toml"
        path.write_text("name = [\n", encoding="utf-8")
    else:
        path = root / "skills.sh.json"
        path.write_text("{", encoding="utf-8")

    _assert_failure(root, str(path.relative_to(root)), "parse")


@pytest.mark.parametrize("surface", ["skill", "claude_agent", "codex_agent"])
def test_added_host_field_fails(tmp_path: Path, surface: str) -> None:
    root = _copy_surfaces(tmp_path)
    if surface == "skill":
        path = root / ".claude/skills/wordpress-planner/SKILL.md"
        _replace(path, "---\n\n#", "extra_field: forbidden\n---\n\n#")
    elif surface == "claude_agent":
        path = root / ".claude/agents/wordpress-planner.md"
        _replace(path, "---\n\n<", "extra_field: forbidden\n---\n\n<")
    else:
        path = root / ".codex/agents/wordpress-planner.toml"
        path.write_text(path.read_text(encoding="utf-8") + "extra_field = 'forbidden'\n")

    _assert_failure(root, str(path.relative_to(root)), "field")


@pytest.mark.parametrize("name", AGENT_NAMES)
@pytest.mark.parametrize("mutation", ["added", "removed"])
def test_claude_agent_requires_exactly_one_separator_newline(
    tmp_path: Path,
    name: str,
    mutation: str,
) -> None:
    root = _copy_surfaces(tmp_path)
    path = root / ".claude/agents" / f"{name}.md"
    old = "---\n\n<Agent_Prompt>"
    new = "---\n\n\n<Agent_Prompt>" if mutation == "added" else "---\n<Agent_Prompt>"
    _replace(path, old, new)

    _assert_failure(root, str(path.relative_to(root)), "separator")


@pytest.mark.parametrize(
    ("section", "old", "new"),
    [
        ("Protocol", "Phase 0 - Intake boundary", "Phase 0 - Drifted boundary"),
        ("Hard Gates", "- Do not recommend custom code", "- Always recommend custom code"),
        ("Exact API", "Every recommendation", "Every vague recommendation"),
        ("Output", "`## Scope Summary`", "`## Drifted Scope Summary`"),
    ],
)
def test_skill_side_shared_contract_drift_fails(
    tmp_path: Path,
    section: str,
    old: str,
    new: str,
) -> None:
    root = _copy_surfaces(tmp_path)
    for path in _skill_paths(root, "wordpress-planner"):
        _replace(path, old, new)

    _assert_failure(root, "wordpress-planner", section)


@pytest.mark.parametrize(
    ("section", "old", "new"),
    [
        ("Protocol", "Phase 0 - Intake boundary", "Phase 0 - Drifted boundary"),
        ("Hard Gates", "- Do not recommend custom code", "- Always recommend custom code"),
        ("Exact API", "Every recommendation", "Every vague recommendation"),
        ("Output", "## Scope Summary", "## Drifted Scope Summary"),
    ],
)
def test_agent_side_shared_contract_drift_fails(
    tmp_path: Path,
    section: str,
    old: str,
    new: str,
) -> None:
    root = _copy_surfaces(tmp_path)
    for path in _agent_paths(root, "wordpress-planner"):
        _replace(path, old, new)

    _assert_failure(root, "wordpress-planner", section)


@pytest.mark.parametrize(
    ("section", "skill_old", "agent_old"),
    [
        (
            "Protocol",
            "    Phase 1 - Repository and runtime triage",
            "    Phase 1 - Repository and runtime triage",
        ),
        (
            "Hard Gates",
            "    - Do not store secrets",
            "    - Do not store secrets",
        ),
        (
            "Exact API",
            "Every recommendation, decision, remediation",
            "    Every recommendation, decision, remediation",
        ),
        ("Output", "- `## Scope Summary`", "    ## Scope Summary"),
    ],
)
@pytest.mark.parametrize("side", ["skill", "agent"])
def test_shared_contract_whitespace_drift_fails(
    tmp_path: Path,
    section: str,
    skill_old: str,
    agent_old: str,
    side: str,
) -> None:
    root = _copy_surfaces(tmp_path)
    paths = _skill_paths(root, "wordpress-planner") if side == "skill" else _agent_paths(
        root, "wordpress-planner"
    )
    old = skill_old if side == "skill" else agent_old
    for path in paths:
        _replace(path, old, f"    {old}")

    _assert_failure(root, "wordpress-planner", section)


@pytest.mark.parametrize("side", ["skill", "agent"])
def test_new_unclassified_section_fails(tmp_path: Path, side: str) -> None:
    root = _copy_surfaces(tmp_path)
    if side == "skill":
        for path in _skill_paths(root, "wordpress-planner"):
            _replace(path, "## Provenance", "## Unclassified\n\nNew policy.\n\n## Provenance")
    else:
        for path in _agent_paths(root, "wordpress-planner"):
            _replace(
                path,
                "  <Output_Format>",
                "  <Unclassified>\n    New policy.\n  </Unclassified>\n\n  <Output_Format>",
            )

    _assert_failure(root, "wordpress-planner", "unclassified")


@pytest.mark.parametrize(
    "heading",
    [
        "**VERDICT: [DECLINE / REVISE / ACCEPT-WITH-RESERVATIONS / ACCEPT]**",
        "**VERDICT: [REJECT, REVISE, ACCEPT-WITH-RESERVATIONS, ACCEPT]**",
        "**VERDICT: (REJECT / REVISE / ACCEPT-WITH-RESERVATIONS / ACCEPT)**",
        "**VERDICT: ...**",
    ],
)
def test_verdict_heading_content_is_not_normalized_away(
    tmp_path: Path,
    heading: str,
) -> None:
    root = _copy_surfaces(tmp_path)
    canonical = "**VERDICT: [REJECT / REVISE / ACCEPT-WITH-RESERVATIONS / ACCEPT]**"
    for path in _skill_paths(root, "wordpress-security-critic"):
        _replace(path, canonical, heading)

    _assert_failure(root, "wordpress-security-critic", "Output")


def test_manifest_generation_is_deterministic_and_verifies(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)

    first = _install(root, "--generate-manifest")
    first_bytes = (root / "MANIFEST.sha256").read_bytes()
    second = _install(root, "--generate-manifest")
    second_bytes = (root / "MANIFEST.sha256").read_bytes()
    verified = _install(root, "--verify")

    assert first.returncode == second.returncode == verified.returncode == 0
    assert first_bytes == second_bytes
    assert len(first_bytes.splitlines()) == 57


def test_manifest_verifies_in_relocated_checkout(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)
    relocated = tmp_path / "relocated checkout"
    root.rename(relocated)

    result = _install(relocated, "--verify")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["missing", "symlink", "directory"])
def test_manifest_control_must_be_regular(tmp_path: Path, kind: str) -> None:
    root = _copy_install_tree(tmp_path)
    manifest = root / "MANIFEST.sha256"
    original = manifest.read_bytes()
    manifest.unlink()
    if kind == "symlink":
        target = root / "manifest-target"
        target.write_bytes(original)
        manifest.symlink_to(target)
    elif kind == "directory":
        manifest.mkdir()

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert "control file" in result.stdout


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("duplicate", "duplicate"),
        ("missing", "missing"),
        ("extra", "extra"),
        ("absolute", "malformed"),
        ("traversal", "extra"),
    ],
)
def test_manifest_record_policy_fails(
    tmp_path: Path,
    mutation: str,
    needle: str,
) -> None:
    root = _copy_install_tree(tmp_path)
    path = root / "MANIFEST.sha256"
    lines = path.read_text(encoding="utf-8").splitlines()
    digest, relative = lines[0].split("  ", 1)
    if mutation == "duplicate":
        lines.append(lines[0])
    elif mutation == "missing":
        lines.pop()
    elif mutation == "extra":
        lines.append(f"{digest}  docs/not-distributed.md")
    elif mutation == "absolute":
        lines[0] = f"{digest}  /absolute/path"
    else:
        lines[0] = f"{digest}  ../{relative}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert needle in result.stdout


def test_manifest_lone_carriage_return_separator_fails(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)
    path = root / "MANIFEST.sha256"
    encoded = path.read_bytes()
    assert b"\n" in encoded
    path.write_bytes(encoded.replace(b"\n", b"\r", 1))

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert "malformed" in result.stdout


@pytest.mark.parametrize(
    "relative",
    [
        ".claude/agents/wordpress-planner.md",
        ".claude/skills/wordpress-planner/SKILL.md",
        ".agents/skills/wordpress-planner/SKILL.md",
        ".codex/agents/wordpress-planner.toml",
        "skills.sh.json",
    ],
)
def test_manifest_detects_each_surface_mutation(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _copy_install_tree(tmp_path)
    path = root / relative
    path.write_bytes(path.read_bytes() + b"\n")

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert relative in result.stdout
    assert "checksum mismatch" in result.stdout


def test_manifest_rejects_symlinked_distributed_file(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)
    path = root / ".codex/agents/wordpress-planner.toml"
    target = root.parent / "outside-agent.toml"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert "unsafe" in result.stdout


@pytest.mark.parametrize(
    "relative",
    [".codex/agents", ".claude/skills/wordpress-planner"],
)
def test_manifest_rejects_symlinked_distribution_parent(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _copy_install_tree(tmp_path)
    path = root / relative
    outside = root.parent / f"outside-{path.name}"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=True)

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert "distribution parent" in result.stdout or "unsafe" in result.stdout


def test_direct_parity_rejects_symlinked_skill_parent(tmp_path: Path) -> None:
    root = _copy_surfaces(tmp_path)
    path = root / ".claude/skills/wordpress-planner"
    outside = root.parent / "outside-wordpress-planner"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=True)

    _assert_failure(root, "wordpress-planner/SKILL.md", "unavailable or unsafe")


def test_default_install_accepts_complete_verified_distribution(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)

    result = _install(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root.parent / "synthetic-home/.claude/skills/wordpress-planner").is_symlink()


@pytest.mark.parametrize("kind", ["missing", "corrupt", "symlink"])
def test_default_install_aborts_before_links_on_unsafe_manifest(
    tmp_path: Path,
    kind: str,
) -> None:
    root = _copy_install_tree(tmp_path)
    manifest = root / "MANIFEST.sha256"
    if kind == "missing":
        manifest.unlink()
    elif kind == "corrupt":
        manifest.write_bytes(manifest.read_bytes() + b"corrupt\n")
    else:
        target = root.parent / "outside-manifest"
        manifest.rename(target)
        manifest.symlink_to(target)

    result = _install(root)

    assert result.returncode != 0
    assert "failed" in result.stdout.lower() or "mismatch" in result.stdout.lower()
    home = root.parent / "synthetic-home"
    assert not any(path.is_symlink() for path in home.rglob("*"))


def test_manifest_rejects_unexpected_distribution_entry(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)
    extra = root / ".claude/agents/wordpress-extra.md"
    extra.write_text("extra\n", encoding="utf-8")

    result = _install(root, "--verify")

    assert result.returncode != 0
    assert "distribution inventory extra" in result.stdout


def test_interrupted_manifest_replace_preserves_prior_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_install_tree(tmp_path)
    module = _load_validator()
    original = (root / "MANIFEST.sha256").read_bytes()

    def interrupt(_source: Path, _destination: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        module.generate_manifest(root)

    assert (root / "MANIFEST.sha256").read_bytes() == original
    assert not list(root.glob(".MANIFEST.sha256.*"))


def test_manifest_mode_does_not_require_pyyaml(tmp_path: Path) -> None:
    root = _copy_install_tree(tmp_path)
    script = root / "scripts/validate-distribution-parity.py"

    result = subprocess.run(
        [sys.executable, "-S", str(script), "--root", str(root), "--verify-manifest"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
