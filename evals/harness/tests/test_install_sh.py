import os
import re
import shlex
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
    extra_env: dict[str, str] | None = None,
    script_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = _env(home)
    run_env.update(extra_env or {})
    run_args = list(args)
    manifest_modes = {"--no-verify", "--verify", "--generate-manifest", "--remove"}
    if not manifest_modes.intersection(run_args):
        # This fixture isolates link ownership with a deliberately minimal repo.
        # Distribution verification is exercised by test_distribution_parity.py.
        run_args.append("--no-verify")
    return subprocess.run(
        ["/bin/bash", str(script_path or repo / "install.sh"), *run_args],
        cwd=repo,
        env=run_env,
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
    git_home = repo.parent / "git-home"
    git_home.mkdir()
    git_env = _env(git_home) | {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    subprocess.run(
        ["git", "init", "-q", "--template=", str(sibling)],
        check=True,
        env=git_env,
    )
    subprocess.run(
        ["git", "-C", str(sibling), "remote", "add", "origin", f"https://github.com/zivtech/{name}.git"],
        check=True,
        env=git_env,
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


@pytest.mark.parametrize("kind", ["skill", "agent"])
def test_discovery_cannot_split_newline_path_into_external_source(
    tmp_path: Path,
    kind: str,
) -> None:
    repo, home = _make_repo(tmp_path)
    if kind == "skill":
        external = _write(tmp_path / "external-skill/SKILL.md")
        malicious = repo / ".claude/skills" / f"split\n{external}"
        destination = _skill_link(home, ".codex", "external-skill")
    else:
        external = _write(tmp_path / "external-agent.md")
        malicious = repo / ".claude/agents" / f"split\n{external}"
        destination = _agent_link(home, "external-agent.md")
    _write(malicious)

    _run(repo, home, "--no-verify")

    assert not destination.exists() and not destination.is_symlink()
    _assert_current_links(repo, home)


@pytest.mark.parametrize("kind", ["skill", "agent"])
def test_discovery_rejects_control_character_entry_name(
    tmp_path: Path,
    kind: str,
) -> None:
    repo, home = _make_repo(tmp_path)
    if kind == "skill":
        _write(repo / ".claude/skills/bad\tname/SKILL.md")
        destination = _skill_link(home, ".claude", "bad\tname")
    else:
        _write(repo / ".claude/agents/bad\tname.md")
        destination = _agent_link(home, "bad\tname.md")

    result = _run(repo, home, "--no-verify")

    assert "BLOCK unsafe" in result.stdout
    assert not destination.exists() and not destination.is_symlink()


def test_symlink_launcher_uses_physical_checkout_root(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)
    launcher = tmp_path / "launcher/install.sh"
    launcher.parent.mkdir()
    launcher.symlink_to(repo / "install.sh")
    _write(launcher.parent / ".claude/skills/not-from-checkout/SKILL.md")

    _run(repo, home, "--no-verify", script_path=launcher)

    _assert_current_links(repo, home)
    assert not _skill_link(home, ".claude", "not-from-checkout").exists()


def test_trailing_newline_checkout_fails_before_sibling_discovery(
    tmp_path: Path,
) -> None:
    original_root = tmp_path / "original"
    original_root.mkdir()
    original, home = _make_repo(original_root)
    repo = tmp_path / "checkout\n"
    original.rename(repo)
    sibling = tmp_path / "checkout"
    _write(sibling / ".claude/skills/fake/SKILL.md")

    result = _run(repo, home, "--no-verify", check=False)

    assert result.returncode != 0
    assert "control character" in result.stderr
    assert not _skill_link(home, ".codex", "fake").is_symlink()


def test_trailing_newline_raw_target_is_never_owned_or_forced(
    tmp_path: Path,
) -> None:
    repo, home = _make_repo(tmp_path)
    stripped = tmp_path / "alias"
    stripped.symlink_to(repo / ".claude/skills/current-skill")
    raw_target = _write(tmp_path / "alias\n")
    link = _skill_link(home, ".claude")
    link.parent.mkdir(parents=True)
    link.symlink_to(raw_target)

    install = _run(repo, home)
    remove = _run(repo, home, "--remove")
    forced = _run(repo, home, "--force")

    assert "PRESERVE" in install.stdout
    assert "Removed 3 symlinks" in remove.stdout
    assert "unsafe raw link target" in forced.stdout
    assert link.is_symlink()
    assert os.readlink(link) == str(raw_target)


def test_control_bearing_checkout_path_fails_closed(
    tmp_path: Path,
) -> None:
    controlled_root = tmp_path / "checkout\npath"
    controlled_root.mkdir()
    repo, home = _make_repo(controlled_root)

    result = _run(repo, home, "--no-verify", check=False)

    assert result.returncode != 0
    assert "control character" in result.stderr
    assert not (home / ".claude/install.log").exists()


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
    assert "Skipped 1 existing destinations." in result.stdout
    assert "non-symlink files/dirs" not in result.stdout


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
    target = _write(tmp_path / "outside/original target $value")
    link = _skill_link(home, ".claude")
    link.parent.mkdir(parents=True)
    raw = os.path.relpath(target, link.parent)
    link.symlink_to(raw)
    untouched_target = _write(tmp_path / "outside/untouched")
    untouched = _skill_link(home, ".codex")
    untouched.parent.mkdir(parents=True)
    untouched.symlink_to(untouched_target)
    wrapper_dir = tmp_path / "bin"
    wrapper = _write(
        wrapper_dir / "ln",
        "#!/bin/bash\n/bin/ln \"$@\"\nkill -TERM \"$PPID\"\n",
    )
    wrapper.chmod(0o755)

    result = _run(
        repo,
        home,
        "--force",
        check=False,
        extra_env={"PATH": f"{wrapper_dir}:{_env(home)['PATH']}"},
    )
    assert result.returncode == -15
    recovery_line = next(
        line for line in result.stdout.splitlines() if "FORCE replace" in line
    )
    recorded = shlex.split(recovery_line.split("prior-target=", 1)[1])[0]
    assert link.resolve() == (repo / ".claude/skills/current-skill").resolve()
    link.unlink()
    link.symlink_to(recorded)

    assert link.resolve() == target.resolve()
    assert untouched.is_symlink()
    assert untouched.resolve() == untouched_target.resolve()


def test_force_is_rejected_for_remove_mode(tmp_path: Path) -> None:
    repo, home = _make_repo(tmp_path)

    result = _run(repo, home, "--remove", "--force", check=False)

    assert result.returncode != 0
    assert "--force" in result.stderr


def test_installer_avoids_errexit_unsafe_postincrement(tmp_path: Path) -> None:
    repo, _home = _make_repo(tmp_path)
    source = (repo / "install.sh").read_text(encoding="utf-8")

    assert not re.search(r"\(\([A-Za-z_][A-Za-z0-9_]*\+\+\)\)", source)


def test_subprocess_environment_is_minimal_and_synthetic(tmp_path: Path) -> None:
    _repo, home = _make_repo(tmp_path)

    assert _env(home) == {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
    }
