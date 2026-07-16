"""Contracts for tracked public evidence and current-control documents."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "scripts/validate-public-docs.py"
EVIDENCE_FIXTURE = """# Evidence

## Current Proof Surfaces

| Claim | Source evidence | Proven | Not proven |
|---|---|---|---|
| Sample | `evidence/proof.md` | Narrow proof. | Broader proof. |
| Extraction | `docs/wordpress/standalone-extraction-readiness-2026-06-21.md` | Package. | Release. |

## Bundled Evidence Files

- `evidence/*.md`

## Validation Bundle

```bash
python scripts/check.py
python -m pytest evals/harness/tests/test_sample.py
```
"""
INVENTORY_FIXTURE = """# Harness

## Shipped WordPress Tool Inventory

### Repair and certification

- `evals/harness/tool.py` — fixture tool.

### Internal helpers

- `evals/harness/helper.py` — imported helper, not a public CLI.
"""
STATUS_LINK = "[Current status](docs/wordpress/project-status-current.md)\n"


def _write(root: Path, relative: str, content: str = "fixture\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=False,
        capture_output=True, text=True, timeout=10,
    )


def _write_controls(root: Path) -> None:
    _write(root, "EVIDENCE.md", EVIDENCE_FIXTURE)
    _write(root, "evals/harness/README.md", INVENTORY_FIXTURE)
    _write(root, "README.md", f"# Repo\n\n{STATUS_LINK}")
    for name in (
        "PUBLICATION-CHECKLIST.md", "CUTOVER.md", "PACKAGE-BUILD.md",
        "PROVENANCE.md",
    ):
        _write(root, name, f"# Control\n\n{STATUS_LINK}")
    _write(root, "CONTRIBUTING.md", "# Contributing\n\n## Validation\n\n`python scripts/check.py`\n")
    _write(root, "SECURITY.md", "# Security\n\n## Validation Expectations\n\n`python scripts/check.py`\n")


def _write_status_controls(root: Path) -> None:
    _write(root, "docs/wordpress/standalone-extraction-readiness-2026-06-21.md")
    _write(
        root, "docs/wordpress/project-status-current.md",
        "# Current Project Status\n\nStatus date: `2026-07-15`\n\n"
        "[Project status for 2026-07-15](project-status-2026-07-15.md)\n",
    )
    _write(root, "docs/wordpress/project-status-2026-07-15.md", "# Status\n")
    _write(
        root, "docs/wordpress/project-status-2026-07-06.md",
        "> **Superseded:** See [current project status](project-status-current.md).\n\n"
        "# Historical Status\n",
    )


def _valid_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    assert _git(root, "init", "-q").returncode == 0
    _write_controls(root)
    _write_status_controls(root)
    _write(root, "scripts/check.py")
    _write(root, "evals/harness/tests/test_sample.py")
    _write(root, "evals/harness/tool.py")
    _write(root, "evals/harness/helper.py")
    _write(root, "evidence/proof.md")
    assert _git(root, "add", "-A").returncode == 0
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        check=False, capture_output=True, text=True, timeout=10,
    )


def _replace(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    assert old in source
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    assert _git(root, "add", relative).returncode == 0


def _assert_failure(root: Path, *needles: str) -> None:
    result = _run(root)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    for needle in needles:
        assert needle in output


def test_tracked_public_controls_pass(tmp_path: Path) -> None:
    result = _run(_valid_repo(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Public documentation validation passed" in result.stdout


def test_non_git_root_fails(tmp_path: Path) -> None:
    root = tmp_path / "not-git"
    root.mkdir()
    _assert_failure(root, "Git worktree")


def test_missing_current_proof_path_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(root, "EVIDENCE.md", "evidence/proof.md", "evidence/missing.md")
    _assert_failure(root, "Current Proof Surfaces", "evidence/missing.md")


def test_untracked_lookalike_cannot_satisfy_proof(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    assert _git(root, "rm", "--cached", "evidence/proof.md").returncode == 0
    assert (root / "evidence/proof.md").is_file()
    _assert_failure(root, "not tracked", "evidence/proof.md")


def test_symlinked_tracked_proof_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    proof = root / "evidence/proof.md"
    target = _write(root, "evidence/real.md")
    proof.unlink()
    proof.symlink_to(target.name)
    assert _git(root, "add", "-A").returncode == 0
    _assert_failure(root, "symlink", "evidence/proof.md")


def test_repository_escape_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(root, "EVIDENCE.md", "evidence/proof.md", "../outside.md")
    _assert_failure(root, "traversal", "../outside.md")


def test_unmatched_bundled_glob_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(root, "EVIDENCE.md", "evidence/*.md", "evidence/*.json")
    _assert_failure(root, "Bundled Evidence Files", "matched no tracked")


def test_absent_harness_inventory_entry_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(root, "evals/harness/README.md", "tool.py", "missing.py")
    _assert_failure(root, "Shipped WordPress Tool Inventory", "missing.py")


def test_invalid_validation_command_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(root, "EVIDENCE.md", "scripts/check.py", "scripts/missing.py")
    _assert_failure(root, "Validation Bundle", "scripts/missing.py")


def test_json_reference_is_not_misparsed_as_javascript(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    path = root / "CONTRIBUTING.md"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("Recorded inventory: `evals/harness/data/wp-symbols.json`.\n")
    assert _git(root, "add", str(path.relative_to(root))).returncode == 0
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_current_status_target_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    target = "docs/wordpress/project-status-2026-07-15.md"
    assert _git(root, "rm", "-f", target).returncode == 0
    _assert_failure(root, "current status target", "not tracked")


def test_multiple_current_status_targets_fail(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _write(root, "docs/wordpress/project-status-2026-07-14.md")
    pointer = root / "docs/wordpress/project-status-current.md"
    with pointer.open("a", encoding="utf-8") as stream:
        stream.write("[Other](project-status-2026-07-14.md)\n")
    assert _git(root, "add", "-A").returncode == 0
    _assert_failure(root, "exactly one relative link")


def test_untracked_current_status_target_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    target = "docs/wordpress/project-status-2026-07-15.md"
    assert _git(root, "rm", "--cached", target).returncode == 0
    assert (root / target).is_file()
    _assert_failure(root, "current status target", "not tracked")


def test_current_status_date_must_match_filename(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(
        root, "docs/wordpress/project-status-current.md",
        "Status date: `2026-07-15`", "Status date: `2026-07-14`",
    )
    _assert_failure(root, "declared date", "target filename")


def test_readme_must_use_stable_status_pointer(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(root, "README.md", "project-status-current.md", "project-status-2026-07-15.md")
    _assert_failure(root, "README.md", "stable status pointer")


def test_supersession_banner_must_use_stable_pointer(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    _replace(
        root, "docs/wordpress/project-status-2026-07-06.md",
        "project-status-current.md", "project-status-2026-07-15.md",
    )
    _assert_failure(root, "supersession banner", "project-status-current.md")


def test_redundant_extraction_copy_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    canonical = root / "docs/wordpress/standalone-extraction-readiness-2026-06-21.md"
    duplicate = root / "docs/standalone-extraction-readiness-2026-06-21.md"
    duplicate.parent.mkdir(exist_ok=True)
    shutil.copyfile(canonical, duplicate)
    assert _git(root, "add", "-A").returncode == 0
    _assert_failure(root, "redundant extraction document")


def test_stale_active_control_phrase_fails(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    path = root / "evals/harness/README.md"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("run_design_smoke.py\n")
    assert _git(root, "add", str(path.relative_to(root))).returncode == 0
    _assert_failure(root, "stale active-control phrase", "run_design_smoke")


def test_untracked_validator_input_is_not_a_fallback(tmp_path: Path) -> None:
    root = _valid_repo(tmp_path)
    untracked = _write(root, "evidence/only-untracked.json")
    assert os.path.isfile(untracked)
    _replace(root, "EVIDENCE.md", "evidence/*.md", "evidence/*.json")
    _assert_failure(root, "matched no tracked")
