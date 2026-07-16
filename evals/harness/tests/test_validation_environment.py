"""Policy tests for the locked Python validation environment and CI corpus."""
from __future__ import annotations

import ast
import builtins
import importlib.util
import itertools
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/validate.yml"
GENERAL = "not docker_boundary and not live_provider"
SANDBOX = "docker_boundary and docker_sandbox and not live_provider"
GENERATED = "docker_boundary and docker_generated_runtime and not live_provider"
LIVE = "live_provider"
ACTION_PINS = {
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/cache": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "astral-sh/setup-uv": "37802adc94f370d6bfd71619e3f0bf239e1f3b78",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}
OPTIONAL_IMPORTS = {
    "anthropic": ("evals/harness/llm_judge.py", "LLM judge provider call"),
    "gepa": (
        "evals/harness/run_gepa_executor_optimization.py",
        "GEPA optimization CLI",
    ),
}
REQUIRED_EXTERNAL_IMPORTS = {"pytest", "yaml"}


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _workflow() -> tuple[str, dict]:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.load(source, Loader=yaml.BaseLoader)
    return source, parsed


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def _all_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def _external_import_inventory() -> dict[str, set[str]]:
    roots = (ROOT / "evals/harness", ROOT / "scripts")
    paths = [path for root in roots for path in root.rglob("*.py")]
    local = {path.stem for path in paths}
    local.update(path.name for root in roots for path in root.iterdir() if path.is_dir())
    inventory: dict[str, set[str]] = {}
    for path in paths:
        for name in _all_imports(path):
            if name in sys.stdlib_module_names or name in local or name == "__future__":
                continue
            inventory.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return inventory


def _collect(selector: str | None = None) -> set[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if selector:
        command.extend(("-m", selector))
    command.append("evals/harness/tests")
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("evals/harness/tests/") and "::" in line
    }


def _normalized_shell(source: str) -> str:
    return " ".join(source.replace("\\\n", " ").split())


def test_python_pin_and_direct_dependencies_match_green_baseline():
    project = _project()["project"]
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13.9"
    assert project["requires-python"] == "==3.13.*"
    assert project["dependencies"] == ["pyyaml==6.0.3"]
    assert project["optional-dependencies"]["test"] == ["pytest==9.1.0"]
    assert _project()["tool"]["uv"]["package"] is False


def test_lock_contains_project_and_resolved_direct_dependencies():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {item["name"]: item for item in lock["package"]}
    assert lock["requires-python"] == "==3.13.*"
    assert packages["wp-meta-skills-validation"]
    assert packages["pytest"]["version"] == "9.1.0"
    assert packages["pyyaml"]["version"] == "6.0.3"


def test_required_and_optional_import_inventories_are_complete():
    inventory = _external_import_inventory()
    assert set(inventory) == REQUIRED_EXTERNAL_IMPORTS | set(OPTIONAL_IMPORTS)
    for module, (owner, _purpose) in OPTIONAL_IMPORTS.items():
        assert inventory[module] == {owner}
    declared = {"yaml": "pyyaml", "pytest": "pytest"}
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert all(declared[module] in project_text for module in REQUIRED_EXTERNAL_IMPORTS)


def test_optional_provider_import_is_lazy_and_fails_before_network(monkeypatch):
    judge_path = ROOT / OPTIONAL_IMPORTS["anthropic"][0]
    assert "anthropic" not in _top_level_imports(judge_path)
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("blocked optional SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    spec = importlib.util.spec_from_file_location("locked_env_llm_judge", judge_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-not-a-secret")
    with pytest.raises(RuntimeError, match="optional anthropic SDK"):
        module.score_with_llm_judge("output", {}, "fixture", "candidate")


def test_optional_gepa_import_stays_owned_by_operator_cli():
    gepa_path = ROOT / OPTIONAL_IMPORTS["gepa"][0]
    assert "gepa" in _top_level_imports(gepa_path)
    this_test = Path(__file__).resolve()
    collected_imports = set().union(
        *(
            _all_imports(path)
            for path in (ROOT / "evals/harness/tests").glob("test_*.py")
            if path.resolve() != this_test
        )
    )
    assert "run_gepa_executor_optimization" not in collected_imports


def test_marker_registry_is_centralized_in_pyproject():
    markers = _project()["tool"]["pytest"]["ini_options"]["markers"]
    registered = {marker.split(":", 1)[0] for marker in markers}
    assert registered == {
        "docker_boundary",
        "docker_sandbox",
        "docker_generated_runtime",
        "live_provider",
        "real_api_lint",
        "real_security_gate",
    }
    assert not (ROOT / "pytest.ini").exists()


def test_collection_partitions_cover_all_nodes_exactly_once():
    partitions = {
        "general": _collect(GENERAL),
        "sandbox": _collect(SANDBOX),
        "generated": _collect(GENERATED),
        "live": _collect(LIVE),
    }
    assert len(partitions["sandbox"]) == 35
    assert len(partitions["generated"]) == 5
    assert len(partitions["live"]) == 1
    for left, right in itertools.combinations(partitions.values(), 2):
        assert left.isdisjoint(right)
    assert set().union(*partitions.values()) == _collect()
    assert partitions["sandbox"] | partitions["generated"] == _collect("docker_boundary")


def test_workflow_actions_are_immutable_and_bootstraps_are_bounded():
    source, workflow = _workflow()
    observed: dict[str, set[str]] = {}
    for action, revision in re.findall(r"uses:\s+([^@\s]+)@([^\s]+)", source):
        assert re.fullmatch(r"[0-9a-f]{40}", revision)
        observed.setdefault(action, set()).add(revision)
    assert observed == {action: {pin} for action, pin in ACTION_PINS.items()}
    for job_name in ("sandbox-feasibility", "generated-runtime-boundary"):
        job = workflow["jobs"][job_name]
        assert job["permissions"] == {}
        steps = {step.get("uses", "").split("@")[0]: step for step in job["steps"]}
        assert steps["actions/setup-python"]["with"]["token"] == ""
        assert steps["astral-sh/setup-uv"]["with"]["github-token"] == ""
        assert steps["astral-sh/setup-uv"]["with"]["enable-cache"] == "false"
        assert steps["astral-sh/setup-uv"]["with"]["version"] == "0.9.27"


def test_workflow_uses_locked_directory_wide_corpus_commands():
    source, workflow = _workflow()
    normalized = _normalized_shell(source)
    for selector in (GENERAL, SANDBOX, GENERATED):
        command = (
            "uv run --locked --extra test python -m pytest "
            f"-m '{selector}' evals/harness/tests -q"
        )
        assert normalized.count(command) == 1
    assert "pip install --upgrade pytest pyyaml" not in source.lower()
    assert source.count("uv lock --check") == 3
    assert source.count("uv sync --locked --extra test") == 3
    paths = workflow["on"]["pull_request"]["paths"]
    for required in (".python-version", "pyproject.toml", "uv.lock", "requirements-validation.txt"):
        assert required in paths
    assert "pytest.ini" not in paths


def test_every_actions_python_command_uses_locked_uv_runner():
    source, _workflow_data = _workflow()
    raw_python_commands = re.findall(
        r"(?m)^\s+(?:(?:[A-Z_][A-Z0-9_]*=[^\s]+)\s+)*python(?:\s|$)",
        source,
    )
    assert raw_python_commands == []
    for line in source.splitlines():
        if "python -m pytest" in line:
            assert "uv run --locked --extra test python -m pytest" in line


def test_contributor_and_security_docs_publish_canonical_commands():
    documents = [
        (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"),
        (ROOT / "SECURITY.md").read_text(encoding="utf-8"),
    ]
    for source in documents:
        assert "uv lock --check" in source
        assert "uv sync --locked --extra test" in source
        for selector in (GENERAL, SANDBOX, GENERATED):
            assert selector in source
            assert "uv run --locked --extra test python -m pytest" in source


def test_requirements_export_is_byte_identical(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv unavailable; hash-installed fallback does not regenerate its lock")
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, tmp_path / name)
    result = subprocess.run(
        [
            uv,
            "export",
            "--locked",
            "--extra",
            "test",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            "requirements-validation.txt",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "requirements-validation.txt").read_bytes() == (
        ROOT / "requirements-validation.txt"
    ).read_bytes()
