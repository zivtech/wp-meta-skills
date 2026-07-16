"""Contracts for the isolated Plugin Check WP-CLI wrapper."""
from __future__ import annotations

import os
from pathlib import Path
import select
import shutil
import stat
import subprocess
from contextlib import contextmanager
from typing import Callable, Iterator

import pytest

import wp_plugin_check_runtime as plugin_check
import wp_runtime_oracles
from wp_runtime_evidence import RuntimeDeadline


def _run_php(
    payload: str, *arguments: str, pass_fds: tuple[int, ...] = (),
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["php", "-r", payload, *arguments], check=False, capture_output=True,
        text=True, timeout=timeout, pass_fds=pass_fds,
    )


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    plugins = tmp_path / "plugins"
    source = plugins / "plugin-check" / "drop-ins" / "object-cache.copy.php"
    source.parent.mkdir(parents=True)
    source.write_text("<?php // sealed drop-in\n", encoding="utf-8")
    return tmp_path / "plugin-check-content", plugins, source


def _setup(content: Path, plugins: Path) -> str:
    result = _run_php(plugin_check._setup_payload(content, plugins))
    assert result.returncode == 0, result.stderr
    return result.stdout


def _descriptor_path(content: Path, fd: int) -> tuple[str, bool]:
    if os.uname().sysname == "Linux":
        return f"/proc/self/fd/{fd}", True
    return str(content), False


@contextmanager
def _directory_anchor(content: Path) -> Iterator[tuple[int, str, bool]]:
    fd = os.open(content, os.O_RDONLY)
    try:
        descriptor, require_zero_links = _descriptor_path(content, fd)
        yield fd, descriptor, require_zero_links
    finally:
        os.close(fd)


def _cleanup(
    content: Path, plugins: Path, identity: str,
    anchor: tuple[int, str, bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    if anchor is None:
        with _directory_anchor(content) as opened:
            return _cleanup(content, plugins, identity, opened)
    fd, descriptor, require_zero_links = anchor
    payload = plugin_check._cleanup_payload(
        content, plugins, descriptor, require_zero_links,
    )
    return _run_php(payload, "--", identity, pass_fds=(fd,))


def _fake_runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "argv.log"
    fake_wp = fake_bin / "wp"
    fake_wp.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$#\" \"$@\" >> \"$ARGV_LOG\"\n"
        "if test -n \"${FD_LOG:-}\"; then "
        "test -r /dev/fd/9 && printf 'open\\n' >> \"$FD_LOG\" || "
        "printf 'closed\\n' >> \"$FD_LOG\"; fi\n"
        "if test \"${CLOSE_CHILD_FD:-0}\" = 1; then exec 9<&-; fi\n"
        "if test \"${1:-}\" = plugin && test \"${2:-}\" = check; then "
        "exit \"${WP_CHECK_STATUS:-0}\"; fi\n",
        encoding="utf-8",
    )
    fake_wp.chmod(0o755)
    fake_php = fake_bin / "php"
    fake_php.write_text(
        "#!/bin/sh\nif test \"$#\" -eq 2; then "
        f"mkdir -p {plugin_check.CONTENT_DIR}; "
        "printf '1:2:3:4:5:6:7:8:0123456789abcdef0123456789abcdef'; "
        "exit 0; fi\ncase \"${2:-}\" in\n"
        "*'cleanup failed'*) if test -n \"${FD_LOG:-}\"; then "
        "test -r /dev/fd/9 && printf 'cleanup-open\\n' >> \"$FD_LOG\" || "
        "printf 'cleanup-closed\\n' >> \"$FD_LOG\"; fi; "
        f"rmdir {plugin_check.CONTENT_DIR}; "
        "exit \"${CLEANUP_STATUS:-0}\" ;;\n"
        "*'setup failed'*) if test -n \"${FD_LOG:-}\"; then "
        "test -r /dev/fd/9 && printf 'anchor-open\\n' >> \"$FD_LOG\" || "
        "printf 'anchor-closed\\n' >> \"$FD_LOG\"; fi; "
        "exit \"${ANCHOR_STATUS:-0}\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_php.chmod(0o755)
    return fake_bin, log, fake_wp


def _run_shell(command, fake_bin, log, **values):
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
           "ARGV_LOG": str(log), **values}
    return subprocess.run(
        ["sh", "-c", command[-3], command[-2], command[-1]], check=False,
        capture_output=True, text=True, timeout=10, env=env,
    )


def _identity_parts(identity: str) -> list[str]:
    parts = identity.split(":")
    assert len(parts) == 9
    return parts


def _quarantine(content: Path, identity: str) -> Path:
    nonce = _identity_parts(identity)[-1]
    return content.parent / f"{plugin_check.QUARANTINE_PREFIX}{nonce}"


def _replace_identity_stat(
    identity: str, path: Path, offset: int,
) -> str:
    parts = _identity_parts(identity)
    details = path.lstat()
    parts[offset:offset + 4] = [
        str(details.st_dev), str(details.st_ino),
        str(details.st_uid), str(details.st_gid),
    ]
    return ":".join(parts)


def _race_cleanup(
    content: Path, plugins: Path, identity: str, point: str,
    mutate: Callable[[Path], None], tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    ready = tmp_path / f"{point}.ready"
    release = tmp_path / f"{point}.release"
    os.mkfifo(ready)
    os.mkfifo(release)
    ready_fd = os.open(ready, os.O_RDONLY | os.O_NONBLOCK)
    release_fd = os.open(release, os.O_RDWR | os.O_NONBLOCK)
    try:
        return _run_synchronized_cleanup(
            content, plugins, identity, point, mutate,
            (ready, release), (ready_fd, release_fd),
        )
    finally:
        os.close(ready_fd)
        os.close(release_fd)


def _run_synchronized_cleanup(
    content: Path, plugins: Path, identity: str, point: str,
    mutate: Callable[[Path], None], fifos: tuple[Path, Path],
    fifo_fds: tuple[int, int],
) -> subprocess.CompletedProcess[str]:
    ready, release = fifos
    ready_fd, release_fd = fifo_fds
    with _directory_anchor(content) as anchor:
        fd, descriptor, require_zero_links = anchor
        payload = plugin_check._cleanup_payload(
            content, plugins, descriptor, require_zero_links,
            (point, ready, release),
        )
        args = ["php", "-r", payload, "--", identity]
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, pass_fds=(fd,),
        )
        readable, _, _ = select.select([ready_fd], [], [], 10)
        assert readable, f"cleanup did not reach synchronization point {point}"
        observed = os.read(ready_fd, 128).decode()
        assert observed == point
        mutate(_quarantine(content, identity))
        assert os.write(release_fd, b"1") == 1
        stdout, stderr = process.communicate(timeout=10)
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _assert_darwin_structural_race(point: str) -> None:
    assert os.uname().sysname == "Darwin", "expected Darwin structural branch"
    test_payload = plugin_check._cleanup_payload(
        Path("/tmp/direct"), Path("/tmp/plugins"), "/tmp/direct", False,
        (point, Path("/tmp/ready"), Path("/tmp/release")),
    )
    production = plugin_check._cleanup_payload(
        plugin_check.CONTENT_DIR, plugin_check.PLUGIN_DIR,
    )
    assert point in test_payload and "/tmp/ready" in test_payload
    assert "/tmp/ready" not in production and "/tmp/release" not in production
    assert "$sync" not in production and "$fd=$quarantine" not in production
    assert plugin_check.PRODUCTION_DESCRIPTOR in production


def test_command_keeps_plugin_check_slug_at_wp_cli_argv_one_to_three(tmp_path):
    command = plugin_check.build_command(["docker", "compose"], "safe-plugin")
    shell, shell_name, slug = command[-3:]
    assert shell_name == "plugin-check-wrapper"
    assert slug == "safe-plugin"
    assert "safe-plugin" not in shell
    assert 'wp plugin check "$1"' in shell
    assert shell.index('wp plugin check "$1"') < shell.index("--exec=")

    fake_bin, log, _fake_wp = _fake_runtime(tmp_path)
    result = _run_shell(command, fake_bin, log)
    assert result.returncode == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    first_count = int(lines[0])
    second = lines[1 + first_count:]
    argv = second[1:1 + int(second[0])]
    assert argv[:3] == ["plugin", "check", "safe-plugin"]
    assert next(i for i, item in enumerate(argv) if item.startswith("--exec=")) > 2


def test_outer_shell_preserves_primary_status_unless_cleanup_fails(tmp_path):
    command = plugin_check.build_command(["docker", "compose"], "safe-plugin")
    fake_bin, log, _fake_wp = _fake_runtime(tmp_path)
    primary = _run_shell(command, fake_bin, log, WP_CHECK_STATUS="17")
    assert primary.returncode == 17

    log.unlink()
    cleanup = _run_shell(
        command, fake_bin, log, WP_CHECK_STATUS="17", CLEANUP_STATUS="43",
    )
    assert cleanup.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert "primary rc=17" in cleanup.stderr


def test_parent_fd_survives_children_that_close_their_inherited_copy(tmp_path):
    command = plugin_check.build_command(["docker", "compose"], "safe-plugin")
    fake_bin, log, _fake_wp = _fake_runtime(tmp_path)
    fd_log = tmp_path / "fd.log"
    result = _run_shell(
        command, fake_bin, log, FD_LOG=str(fd_log), CLOSE_CHILD_FD="1",
    )
    assert result.returncode == 0
    assert fd_log.read_text(encoding="utf-8").splitlines() == [
        "closed", "anchor-open", "open", "cleanup-open",
    ]


def test_setup_records_exact_directory_and_sentinel_identity(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    owner = content / plugin_check.OWNER_FILENAME
    directory_stat = content.lstat()
    owner_stat = owner.lstat()
    parts = _identity_parts(identity)
    assert stat.S_IMODE(directory_stat.st_mode) == 0o700
    assert stat.S_ISREG(owner_stat.st_mode)
    assert stat.S_IMODE(owner_stat.st_mode) == 0o600
    assert owner_stat.st_nlink == 1
    assert {entry.name for entry in content.iterdir()} == {
        plugin_check.OWNER_FILENAME,
    }
    assert owner.read_text(encoding="ascii") == parts[-1]
    assert len(parts[-1]) == 32 and set(parts[-1]) <= set("0123456789abcdef")
    assert parts[:4] == [
        str(directory_stat.st_dev), str(directory_stat.st_ino),
        str(directory_stat.st_uid), str(directory_stat.st_gid),
    ]
    assert parts[4:8] == [
        str(owner_stat.st_dev), str(owner_stat.st_ino),
        str(owner_stat.st_uid), str(owner_stat.st_gid),
    ]


def test_setup_rejects_a_preexisting_content_directory(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    content.mkdir(mode=0o700)
    result = _run_php(plugin_check._setup_payload(content, plugins))
    assert result.returncode == plugin_check.SETUP_FAILURE_EXIT
    assert content.is_dir()
    assert "Plugin Check setup failed" in result.stderr


@pytest.mark.parametrize("nonce_variant", ("wrong", "prefixed", "suffixed"))
def test_cleanup_rejects_every_nonexact_nonce_without_rename(
    tmp_path, nonce_variant,
):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    parts = _identity_parts(identity)
    replacements = {
        "wrong": "0" * 32 if parts[-1] != "0" * 32 else "1" * 32,
        "prefixed": f"0{parts[-1]}",
        "suffixed": f"{parts[-1]}0",
    }
    parts[-1] = replacements[nonce_variant]
    result = _cleanup(content, plugins, ":".join(parts))
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir()
    assert not list(tmp_path.glob(f"{plugin_check.QUARANTINE_PREFIX}*"))


@pytest.mark.parametrize("replacement", ("absent", "symlink", "fifo"))
def test_cleanup_rejects_missing_or_nonregular_sentinel(tmp_path, replacement):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    owner = content / plugin_check.OWNER_FILENAME
    nonce = _identity_parts(identity)[-1]
    owner.unlink()
    external = tmp_path / "external-owner"
    external.write_text(nonce, encoding="ascii")
    if replacement == "symlink":
        owner.symlink_to(external)
    elif replacement == "fifo":
        os.mkfifo(owner, 0o600)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert external.read_text(encoding="ascii") == nonce
    assert content.is_dir()


def test_cleanup_rejects_wrong_sentinel_mode_and_link_count(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    owner = content / plugin_check.OWNER_FILENAME
    owner.chmod(0o644)
    assert _cleanup(content, plugins, identity).returncode == 43
    owner.chmod(0o600)
    alias = tmp_path / "owner-alias"
    os.link(owner, alias)
    assert _cleanup(content, plugins, identity).returncode == 43
    assert alias.read_text(encoding="ascii") == _identity_parts(identity)[-1]


def test_cleanup_rejects_wrong_directory_mode_without_rename(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    content.chmod(0o755)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir() and not _quarantine(content, identity).exists()


@pytest.mark.parametrize("offset", (0, 4))
def test_cleanup_rejects_wrong_directory_or_sentinel_identity(tmp_path, offset):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    parts = _identity_parts(identity)
    parts[offset] = str(int(parts[offset]) + 1)
    result = _cleanup(content, plugins, ":".join(parts))
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir()


def test_cleanup_rejects_an_ordinary_copied_sentinel(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    owner = content / plugin_check.OWNER_FILENAME
    copy = tmp_path / "owner-copy"
    shutil.copyfile(owner, copy)
    owner.unlink()
    shutil.copyfile(copy, owner)
    owner.chmod(0o600)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir()


@pytest.mark.parametrize("collision", ("directory", "symlink"))
def test_cleanup_rejects_directory_and_symlink_quarantine_collisions(
    tmp_path, collision,
):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    quarantine = _quarantine(content, identity)
    external = tmp_path / "external-quarantine"
    external.mkdir()
    if collision == "directory":
        quarantine.mkdir()
    else:
        quarantine.symlink_to(external, target_is_directory=True)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir() and external.is_dir()


def test_cleanup_accepts_absent_or_exact_dropin_and_proves_absence(tmp_path):
    content, plugins, source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    absent = _cleanup(content, plugins, identity)
    assert absent.returncode == 0
    assert not content.exists()

    identity = _setup(content, plugins)
    shutil.copyfile(source, content / "object-cache.php")
    exact = _cleanup(content, plugins, identity)
    assert exact.returncode == 0
    assert not content.exists()


@pytest.mark.parametrize("filename", ("object-cache.php", "extra"))
def test_cleanup_fails_closed_without_broad_deletion(tmp_path, filename):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    (content / filename).write_text("unexpected", encoding="utf-8")
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert list(tmp_path.glob(f"{plugin_check.QUARANTINE_PREFIX}*"))
    assert "Plugin Check cleanup failed" in result.stderr


@pytest.mark.parametrize("fifo_path", ("source", "target"))
def test_cleanup_rejects_stable_fifo_without_blocking(tmp_path, fifo_path):
    content, plugins, source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    target = content / "object-cache.php"
    if fifo_path == "source":
        source.unlink()
        os.mkfifo(source)
    else:
        os.mkfifo(target)
    with _directory_anchor(content) as anchor:
        fd, descriptor, require_zero_links = anchor
        payload = plugin_check._cleanup_payload(
            content, plugins, descriptor, require_zero_links,
        )
        result = _run_php(
            payload, "--", identity, pass_fds=(fd,), timeout=1,
        )
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert _quarantine(content, identity).is_dir()


def test_cleanup_rejects_external_directory_replacement(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    owner = content / plugin_check.OWNER_FILENAME
    retained = tmp_path / "retained-owner"
    owner.rename(retained)
    content.rmdir()
    content.mkdir(mode=0o700)
    shutil.copyfile(retained, owner)
    owner.chmod(0o600)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir()


def test_linux_behavioral_or_darwin_structural_anchor_replacement(tmp_path):
    if os.uname().sysname != "Linux":
        _assert_darwin_structural_race("before_rename")
        command = plugin_check.build_command(["docker", "compose"], "plugin")[-3]
        assert command.index("exec 9<") < command.index("wp plugin check")
        assert command.index("wp plugin check") < command.rindex("exec 9<&-")
        return

    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    with _directory_anchor(content) as anchor:
        owner = content / plugin_check.OWNER_FILENAME
        retained = tmp_path / "retained-owner"
        owner.rename(retained)
        content.rmdir()
        content.mkdir(mode=0o700)
        retained.rename(owner)
        forged = _replace_identity_stat(identity, content, 0)
        result = _cleanup(content, plugins, forged, anchor)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir(), "Linux retained descriptor must reject replacement"


def test_pre_rename_mismatch_and_post_rename_mismatch_have_distinct_disposition(
    tmp_path,
):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    owner = content / plugin_check.OWNER_FILENAME
    owner.chmod(0o644)
    before = _cleanup(content, plugins, identity)
    assert before.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir() and not _quarantine(content, identity).exists()

    owner.chmod(0o600)
    after = _race_cleanup(
        content, plugins, identity, "after_rename",
        lambda quarantine: (
            quarantine / plugin_check.OWNER_FILENAME
        ).chmod(0o644),
        tmp_path,
    )
    assert after.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert not content.exists() and _quarantine(content, identity).is_dir()


def test_linux_behavioral_or_darwin_structural_last_moment_sentinel_link(
    tmp_path,
):
    if os.uname().sysname != "Linux":
        _assert_darwin_structural_race("before_unlink_sentinel")
        return
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    retained = tmp_path / "retained-sentinel"

    def replace(quarantine: Path) -> None:
        owner = quarantine / plugin_check.OWNER_FILENAME
        owner.rename(retained)
        owner.write_text(_identity_parts(identity)[-1], encoding="ascii")
        owner.chmod(0o600)

    result = _race_cleanup(
        content, plugins, identity, "before_unlink_sentinel", replace, tmp_path,
    )
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert retained.is_file() and retained.stat().st_nlink == 1


def test_linux_behavioral_or_darwin_structural_last_moment_object_link(tmp_path):
    if os.uname().sysname != "Linux":
        _assert_darwin_structural_race("before_unlink_object")
        return
    content, plugins, source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    target = content / "object-cache.php"
    shutil.copyfile(source, target)
    retained = tmp_path / "retained-object-cache.php"

    def replace(quarantine: Path) -> None:
        anchored_target = quarantine / "object-cache.php"
        anchored_target.rename(retained)
        shutil.copyfile(source, anchored_target)

    result = _race_cleanup(
        content, plugins, identity, "before_unlink_object", replace, tmp_path,
    )
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert retained.is_file() and retained.stat().st_nlink == 1


@pytest.mark.parametrize("basename", (plugin_check.OWNER_FILENAME, "object-cache.php"))
def test_linux_behavioral_or_darwin_structural_unlinked_first_file_boundary(
    tmp_path, basename,
):
    point = (
        "before_unlink_sentinel" if basename == plugin_check.OWNER_FILENAME
        else "before_unlink_object"
    )
    if os.uname().sysname != "Linux":
        _assert_darwin_structural_race(point)
        return
    content, plugins, source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    if basename == "object-cache.php":
        shutil.copyfile(source, content / basename)
    outside = tmp_path / "outside"
    outside.write_text("preserve", encoding="utf-8")

    def replace(quarantine: Path) -> None:
        target = quarantine / basename
        target.unlink()
        if basename == plugin_check.OWNER_FILENAME:
            target.write_text(_identity_parts(identity)[-1], encoding="ascii")
            target.chmod(0o600)
        else:
            shutil.copyfile(source, target)

    result = _race_cleanup(
        content, plugins, identity, point, replace, tmp_path,
    )
    assert result.returncode == 0
    assert outside.read_text(encoding="utf-8") == "preserve"
    assert not content.exists() and not _quarantine(content, identity).exists()


def test_linux_behavioral_or_darwin_structural_last_moment_directory_link(
    tmp_path,
):
    if os.uname().sysname != "Linux":
        _assert_darwin_structural_race("before_rmdir")
        production = plugin_check._cleanup_payload(
            plugin_check.CONTENT_DIR, plugin_check.PLUGIN_DIR,
        )
        assert '$removed["nlink"]!==0' in production
        return
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    retained = tmp_path / "retained-quarantine"

    def replace(quarantine: Path) -> None:
        quarantine.rename(retained)
        quarantine.mkdir(mode=0o700)

    result = _race_cleanup(
        content, plugins, identity, "before_rmdir", replace, tmp_path,
    )
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert retained.is_dir(), "Linux link oracle must retain the anchored original"


def test_linux_behavioral_or_darwin_structural_unlinked_first_directory_boundary(
    tmp_path,
):
    if os.uname().sysname != "Linux":
        _assert_darwin_structural_race("before_rmdir")
        return
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    outside = tmp_path / "outside"
    outside.write_text("preserve", encoding="utf-8")

    def replace(quarantine: Path) -> None:
        quarantine.rmdir()
        quarantine.mkdir(mode=0o700)

    result = _race_cleanup(
        content, plugins, identity, "before_rmdir", replace, tmp_path,
    )
    assert result.returncode == 0
    assert outside.read_text(encoding="utf-8") == "preserve"
    assert not content.exists() and not _quarantine(content, identity).exists()


def test_cleanup_rejects_a_completed_external_directory_symlink(tmp_path):
    content, plugins, source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    victim = tmp_path / "victim"
    victim.mkdir()
    victim_dropin = victim / "object-cache.php"
    shutil.copyfile(source, victim_dropin)
    (content / plugin_check.OWNER_FILENAME).unlink()
    content.rmdir()
    content.symlink_to(victim, target_is_directory=True)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert victim_dropin.is_file()


def test_post_process_cleanup_detects_late_shutdown_recreation(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    child = plugin_check._exec_payload(content, plugins) + (
        'register_shutdown_function(static function():void{'
        'file_put_contents(WP_CONTENT_DIR."/late","unexpected");});'
    )
    assert _run_php(child).returncode == 0
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert list(tmp_path.glob(f"{plugin_check.QUARANTINE_PREFIX}*"))


def test_absence_probe_rejects_content_and_quarantine_paths(tmp_path):
    content = tmp_path / "plugin-check-content"
    payload = plugin_check._absence_payload(content)
    assert _run_php(payload).returncode == 0
    content.mkdir()
    assert _run_php(payload).returncode == plugin_check.CLEANUP_FAILURE_EXIT
    content.rmdir()
    (tmp_path / f"{plugin_check.QUARANTINE_PREFIX}retained").mkdir()
    assert _run_php(payload).returncode == plugin_check.CLEANUP_FAILURE_EXIT


def test_oracle_proves_absence_after_a_transport_failure(monkeypatch):
    base = ["docker", "compose"]
    probes = []

    def fail(*_args):
        raise RuntimeError("transport failed")

    def prove(command, *_args):
        probes.append(command)
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(wp_runtime_oracles, "_run", fail)
    monkeypatch.setattr(wp_runtime_oracles, "_cleanup_raw", prove)
    with pytest.raises(RuntimeError, match="transport failed"):
        wp_runtime_oracles._plugin_check(
            base, "safe-plugin", RuntimeDeadline.start(30),
        )
    assert probes == [plugin_check.absence_command(base)]


def test_oracle_retains_primary_reason_when_absence_is_not_proved(monkeypatch):
    monkeypatch.setattr(
        wp_runtime_oracles, "_run",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("primary failed")),
    )
    monkeypatch.setattr(
        wp_runtime_oracles, "_cleanup_raw",
        lambda *_args: {"returncode": 43, "stdout": "", "stderr": "retained"},
    )
    with pytest.raises(RuntimeError, match="final absence proof failed.*primary failed"):
        wp_runtime_oracles._plugin_check(
            ["docker", "compose"], "safe-plugin", RuntimeDeadline.start(30),
        )


def test_production_payloads_are_static_and_exact():
    anchor = plugin_check._anchor_payload(
        plugin_check.CONTENT_DIR, plugin_check.PRODUCTION_DESCRIPTOR,
    )
    cleanup = plugin_check._cleanup_payload(
        plugin_check.CONTENT_DIR, plugin_check.PLUGIN_DIR,
    )
    payloads = (
        plugin_check._setup_payload(plugin_check.CONTENT_DIR, plugin_check.PLUGIN_DIR),
        plugin_check.exec_payload(), anchor, cleanup,
    )
    assert all("safe-plugin" not in payload and "'" not in payload for payload in payloads)
    assert all("rm -" not in payload and "glob(" not in payload for payload in payloads)
    assert str(plugin_check.CONTENT_DIR) in "".join(payloads)
    assert str(plugin_check.PLUGIN_DIR) in "".join(payloads)
    assert plugin_check.PRODUCTION_DESCRIPTOR in anchor
    assert plugin_check.PRODUCTION_DESCRIPTOR in cleanup
    assert "/dev/fd/" not in "".join(payloads)
    assert '$removed["nlink"]!==0' in cleanup
    assert cleanup.count("@unlink(") == 2
    assert '$fd."/object-cache.php"' in cleanup
    assert '$fd."/".$owner' in cleanup
    assert "/tmp/ready" not in cleanup and "/tmp/release" not in cleanup
    assert "$sync" not in cleanup and "$fd=$quarantine" not in cleanup
    shell = plugin_check.build_command(["docker", "compose"], "safe-plugin")[-3]
    assert shell.index("identity=$(php") < shell.index("exec 9<")
    assert shell.index("exec 9<") < shell.index("wp plugin check")
    assert shell.index("wp plugin check") < shell.rindex("exec 9<&-")
