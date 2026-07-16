import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = PROJECT_ROOT / "install.sh"


def _write(path: Path, content: str = "test\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "wp-meta-skills"
    home = tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    shutil.copy2(INSTALLER, repo / "install.sh")
    _write(repo / ".claude/skills/current-skill/SKILL.md")
    _write(repo / ".claude/agents/current-agent.md")
    return repo, home


def _env(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
    }


def _run(
    repo: Path,
    home: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(repo / "install.sh"), *args],
        cwd=repo,
        env=_env(home),
        text=True,
        capture_output=True,
        check=check,
    )


def _skill_link(home: Path, host: str, name: str = "current-skill") -> Path:
    return home / host / "skills" / name


def _agent_link(home: Path, name: str = "current-agent.md") -> Path:
    return home / ".claude/agents" / name


def _assert_current_links(repo: Path, home: Path) -> None:
    source = (repo / ".claude/skills/current-skill").resolve()
    for host in (".claude", ".codex", ".agents"):
        assert _skill_link(home, host).resolve() == source
    assert _agent_link(home).resolve() == (
        repo / ".claude/agents/current-agent.md"
    ).resolve()


def _make_sibling(repo: Path, name: str = "drupal-meta-skills") -> Path:
    sibling = repo.parent / name
    _write(sibling / ".claude/skills/sibling-skill/SKILL.md")
    _write(sibling / ".claude/agents/sibling-agent.md")
    subprocess.run(["git", "init", "-q", str(sibling)], check=True)
    subprocess.run(
        ["git", "-C", str(sibling), "remote", "add", "origin", f"https://github.com/zivtech/{name}.git"],
        check=True,
    )
    return sibling


def test_install_links_only_current_repo_entries(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    _make_sibling(repo)

    _run(repo, home)

    _assert_current_links(repo, home)
    assert not _skill_link(home, ".claude", "sibling-skill").exists()
    assert not _agent_link(home, "sibling-agent.md").exists()


def test_no_verify_does_not_discover_sibling_repo(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    _make_sibling(repo)

    _run(repo, home, "--no-verify")

    assert not _skill_link(home, ".codex", "sibling-skill").exists()


def test_remove_deletes_current_repo_links(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    _run(repo, home)

    result = _run(repo, home, "--remove")

    assert "Removed 4 symlinks" in result.stdout
    assert not _skill_link(home, ".claude").exists()
    assert not _skill_link(home, ".codex").exists()
    assert not _skill_link(home, ".agents").exists()
    assert not _agent_link(home).exists()


@pytest.mark.parametrize("kind", ["skill", "agent"])
def test_remove_preserves_sibling_and_unrelated_links(
    tmp_path: Path,
    kind: str,
) -> None:
    repo, home = _make_repo(tmp_path)
    sibling = _make_sibling(repo)
    outside = _write(tmp_path / "unrelated/target")
    destination = (
        _skill_link(home, ".claude", "foreign")
        if kind == "skill"
        else _agent_link(home, "foreign.md")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sibling_target = (
        sibling / ".claude/skills/sibling-skill"
        if kind == "skill"
        else sibling / ".claude/agents/sibling-agent.md"
    )
    destination.symlink_to(sibling_target)
    other = destination.with_name(f"other-{destination.name}")
    other.symlink_to(outside)

    _run(repo, home, "--remove")

    assert destination.is_symlink()
    assert other.is_symlink()


def test_remove_rejects_repo_name_prefix_lookalike(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    lookalike = _write(tmp_path / "wp-meta-skills-lookalike/item")
    link = _skill_link(home, ".claude", "lookalike")
    link.parent.mkdir(parents=True)
    link.symlink_to(lookalike)

    _run(repo, home, "--remove")

    assert link.is_symlink()


def test_remove_rejects_normalized_escape_target(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    outside = _write(tmp_path / "outside/item")
    link = _skill_link(home, ".claude", "escaped")
    link.parent.mkdir(parents=True)
    raw = repo / ".." / "outside/item"
    link.symlink_to(raw)
    assert link.resolve() == outside

    _run(repo, home, "--remove")

    assert link.is_symlink()


def test_remove_rejects_target_through_escaping_symlink(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    outside = _write(tmp_path / "outside/item")
    escape = repo / "escape"
    escape.symlink_to(outside.parent, target_is_directory=True)
    link = _skill_link(home, ".claude", "escaped")
    link.parent.mkdir(parents=True)
    link.symlink_to(escape / "item")

    _run(repo, home, "--remove")

    assert link.is_symlink()


def test_remove_accepts_relative_current_repo_link_from_link_dir(
    tmp_path: Path,
) -> None:
    repo, home = _make_repo(tmp_path)
    link = _skill_link(home, ".claude")
    link.parent.mkdir(parents=True)
    raw = os.path.relpath(repo / ".claude/skills/current-skill", link.parent)
    link.symlink_to(raw)

    _run(repo, home, "--remove")

    assert not link.exists() and not link.is_symlink()


@pytest.mark.parametrize("kind", ["skill", "agent"])
@pytest.mark.parametrize("dangling", [False, True])
def test_install_preserves_unowned_symlink_by_default(
    tmp_path: Path,
    kind: str,
    dangling: bool,
) -> None:
    repo, home = _make_repo(tmp_path)
    target = tmp_path / "outside" / "missing"
    if not dangling:
        target = _write(target)
    link = _skill_link(home, ".claude") if kind == "skill" else _agent_link(home)
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    raw = os.readlink(link)

    result = _run(repo, home)

    assert link.is_symlink()
    assert os.readlink(link) == raw
    assert "PRESERVE" in result.stdout


@pytest.mark.parametrize("kind", ["skill", "agent"])
def test_install_refreshes_current_repo_link(tmp_path: Path, kind: str) -> None:
    repo, home = _make_repo(tmp_path)
    source = (
        repo / ".claude/skills/current-skill"
        if kind == "skill"
        else repo / ".claude/agents/current-agent.md"
    )
    link = _skill_link(home, ".claude") if kind == "skill" else _agent_link(home)
    link.parent.mkdir(parents=True)
    raw = os.path.relpath(source, link.parent)
    link.symlink_to(raw)

    _run(repo, home)

    assert link.resolve() == source.resolve()


@pytest.mark.parametrize("dangling", [False, True])
def test_force_replaces_only_unowned_symlink_and_reports_raw_target(
    tmp_path: Path,
    dangling: bool,
) -> None:
    repo, home = _make_repo(tmp_path)
    target = tmp_path / "outside/missing"
    if not dangling:
        target = _write(target)
    link = _skill_link(home, ".claude")
    link.parent.mkdir(parents=True)
    raw = os.path.relpath(target, link.parent)
    link.symlink_to(raw)

    result = _run(repo, home, "--force")

    assert link.resolve() == (repo / ".claude/skills/current-skill").resolve()
    assert str(link) in result.stdout
    assert raw in result.stdout


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_force_never_replaces_regular_destination(tmp_path: Path, kind: str) -> None:
    repo, home = _make_repo(tmp_path)
    link = _skill_link(home, ".claude")
    if kind == "file":
        _write(link, "keep\n")
    else:
        link.mkdir(parents=True)
        _write(link / "keep")

    result = _run(repo, home, "--force")

    assert "SKIP" in result.stdout
    assert not link.is_symlink()
    if kind == "file":
        assert link.read_text(encoding="utf-8") == "keep\n"
    else:
        assert (link / "keep").is_file()


def test_force_output_supports_interrupted_recovery(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    target = _write(tmp_path / "outside/original")
    link = _skill_link(home, ".claude")
    link.parent.mkdir(parents=True)
    raw = os.path.relpath(target, link.parent)
    link.symlink_to(raw)

    result = _run(repo, home, "--force")
    recovery_line = next(
        line for line in result.stdout.splitlines() if "FORCE replace" in line
    )
    recorded = recovery_line.split("prior-target=", 1)[1]
    link.unlink()
    link.symlink_to(recorded)

    assert link.resolve() == target.resolve()


def test_force_is_rejected_for_remove_mode(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)

    result = _run(repo, home, "--remove", "--force", check=False)

    assert result.returncode != 0
    assert "--force" in result.stderr


def test_subprocess_home_is_synthetic(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    real_home_link = Path.home() / ".codex/skills/current-skill"
    before = real_home_link.lstat() if real_home_link.exists() else None

    _run(repo, home)

    after = real_home_link.lstat() if real_home_link.exists() else None
    assert before == after
