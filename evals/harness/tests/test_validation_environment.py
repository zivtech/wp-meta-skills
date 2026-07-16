"""Policy tests for the locked Python validation environment and CI corpus."""
from __future__ import annotations

import ast
import builtins
import copy
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
REQUIRED_VALIDATORS = {
    "measure-plan010-artifact-path.py",
    "validate-agent-frontmatter.py",
    "validate-distribution-parity.py",
    "validate-eval-suite-integrity.py",
    "validate-wordpress-exact-api-contract.py",
}
NO_SECRETS_ACTIONS = {"actions/setup-python", "astral-sh/setup-uv"}


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _workflow() -> tuple[str, dict]:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.load(source, Loader=yaml.BaseLoader)
    return source, parsed


class _ModuleImportVisitor(ast.NodeVisitor):
    """Visit imports executed at module load while skipping callable bodies."""

    def __init__(self):
        self.imports: set[str] = set()

    def visit_Import(self, node):
        self.imports.update(alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            self.imports.add(node.module.split(".")[0])

    def visit_FunctionDef(self, node):
        return None

    def visit_AsyncFunctionDef(self, node):
        return None

    def visit_ClassDef(self, node):
        self.generic_visit(node)


def _module_scope_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _ModuleImportVisitor()
    visitor.visit(tree)
    return visitor.imports


def _all_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def _python_paths() -> list[Path]:
    roots = (ROOT / "evals/harness", ROOT / "scripts")
    return [path for root in roots for path in root.rglob("*.py")]


def _local_module_index() -> dict[str, Path]:
    candidates: dict[str, list[Path]] = {}
    for path in _python_paths():
        candidates.setdefault(path.stem, []).append(path)
    duplicates = {name: paths for name, paths in candidates.items() if len(paths) != 1}
    assert not duplicates, f"ambiguous local module names: {duplicates}"
    return {name: paths[0] for name, paths in candidates.items()}


def _required_roots() -> set[Path]:
    tests = set((ROOT / "evals/harness/tests").glob("test_*.py"))
    tests.add(ROOT / "evals/harness/tests/conftest.py")
    validators = {ROOT / "scripts" / name for name in REQUIRED_VALIDATORS}
    assert all(path.is_file() for path in tests | validators)
    return tests | validators


def _required_import_closure() -> tuple[set[str], dict[str, set[str]]]:
    roots = _required_roots()
    local = _local_module_index()
    pending = list(roots)
    visited: set[Path] = set()
    external: dict[str, set[str]] = {}
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        imports = _all_imports(path) if path in roots else _module_scope_imports(path)
        for name in imports:
            if name in local:
                pending.append(local[name])
            elif name not in sys.stdlib_module_names and name != "__future__":
                external.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return {str(path.relative_to(ROOT)) for path in visited}, external


def _external_import_inventory() -> dict[str, set[str]]:
    paths = _python_paths()
    roots = (ROOT / "evals/harness", ROOT / "scripts")
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


def _without_heredoc_bodies(script: str) -> str:
    kept = []
    delimiter = None
    for line in script.splitlines():
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = re.search(r"<<-?['\"]?([A-Z][A-Z0-9_]*)['\"]?", line)
        if match:
            delimiter = match.group(1)
    return "\n".join(kept)


def _python_command_violations(workflow: dict) -> list[str]:
    allowed = re.compile(r"\buv\s+run\s+--locked\s+--extra\s+test\s+python\b")
    forbidden = re.compile(r"\bpython(?:3(?:\.\d+)*)?\b")
    violations = []
    for job_name, job in workflow["jobs"].items():
        for step in job["steps"]:
            script = step.get("run")
            if not script:
                continue
            shell_only = _without_heredoc_bodies(script)
            remainder = allowed.sub("", shell_only)
            if forbidden.search(remainder):
                violations.append(f"{job_name}: {step.get('name', '<unnamed>')}")
    return violations


def _string_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)
    elif isinstance(value, str):
        yield value


def _no_secrets_job_violations(job: dict) -> list[str]:
    violations = []
    actions = [step["uses"].split("@")[0] for step in job["steps"] if "uses" in step]
    if len(actions) != 2 or set(actions) != NO_SECRETS_ACTIONS:
        violations.append(f"unexpected actions: {actions}")
    if job.get("permissions") != {}:
        violations.append("permissions must be empty")
    if "container" in job or "services" in job:
        violations.append("job-level helper container or service is forbidden")
    credential = re.compile(
        r"\$\{\{[^}]*?(?:\bsecrets\b|\bgithub\s*(?:\.|\[\s*['\"]?)\s*token\b)",
        re.IGNORECASE,
    )
    if any(credential.search(value) for value in _string_values(job)):
        violations.append("credential expression is forbidden")
    return violations


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


def test_required_import_closure_is_recursive_and_operator_bounded():
    closure, external = _required_import_closure()
    assert set(external) == REQUIRED_EXTERNAL_IMPORTS
    assert OPTIONAL_IMPORTS["anthropic"][0] in closure
    assert OPTIONAL_IMPORTS["gepa"][0] not in closure


def test_optional_provider_import_is_lazy_and_fails_before_network(monkeypatch):
    judge_path = ROOT / OPTIONAL_IMPORTS["anthropic"][0]
    assert "anthropic" not in _module_scope_imports(judge_path)
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
    assert "gepa" in _module_scope_imports(gepa_path)
    closure, _external = _required_import_closure()
    assert str(gepa_path.relative_to(ROOT)) not in closure


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
        assert _no_secrets_job_violations(job) == []
        steps = {step.get("uses", "").split("@")[0]: step for step in job["steps"]}
        assert steps["actions/setup-python"]["with"]["token"] == ""
        assert steps["astral-sh/setup-uv"]["with"]["github-token"] == ""
        assert steps["astral-sh/setup-uv"]["with"]["enable-cache"] == "false"
        assert steps["astral-sh/setup-uv"]["with"]["version"] == "0.9.27"


@pytest.mark.parametrize(
    "addition",
    [
        {"name": "checkout", "uses": f"actions/checkout@{ACTION_PINS['actions/checkout']}"},
        {"name": "cache", "uses": f"actions/cache@{ACTION_PINS['actions/cache']}"},
        {"name": "secret", "run": "echo '${{ secrets.UNSAFE }}'"},
    ],
)
def test_no_secrets_job_policy_rejects_action_and_credential_regressions(addition):
    _source, workflow = _workflow()
    job = copy.deepcopy(workflow["jobs"]["sandbox-feasibility"])
    job["steps"].append(addition)
    assert _no_secrets_job_violations(job)


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
    _source, workflow = _workflow()
    assert _python_command_violations(workflow) == []


@pytest.mark.parametrize(
    "command",
    [
        "python3 scripts/check.py",
        "env SAFE=1 python scripts/check.py",
        "timeout 30s python -m pytest -q",
        "uv run python scripts/check.py",
        "uv run --locked python scripts/check.py",
    ],
)
def test_actions_python_policy_rejects_unlocked_wrapped_commands(command):
    workflow = {"jobs": {"test": {"steps": [{"name": "bad", "run": command}]}}}
    assert _python_command_violations(workflow) == ["test: bad"]


def test_actions_python_policy_accepts_exact_locked_runner():
    workflow = {
        "jobs": {
            "test": {
                "steps": [
                    {
                        "name": "good",
                        "run": "env SAFE=1 uv run --locked --extra test python -m pytest -q",
                    }
                ]
            }
        }
    }
    assert _python_command_violations(workflow) == []


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
        assert 'mktemp -d "${TMPDIR:-/tmp}/wp-meta-skills-validation.XXXXXX"' in source
        assert 'trap \'rm -rf "$validation_venv"\' EXIT' in source
        assert '"$validation_venv/bin/python" -m pip install --require-hashes' in source


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
