"""Contracts for the isolated Plugin Check WP-CLI wrapper."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

import wp_plugin_check_runtime as plugin_check
import wp_runtime_oracles
from wp_runtime_evidence import RuntimeDeadline


def _run_php(payload: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["php", "-r", payload, *arguments], check=False, capture_output=True,
        text=True, timeout=10,
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


def _cleanup(content: Path, plugins: Path, identity: str):
    return _run_php(plugin_check._cleanup_payload(content, plugins), "--", identity)


def _fake_runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "argv.log"
    fake_wp = fake_bin / "wp"
    fake_wp.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$#\" \"$@\" >> \"$ARGV_LOG\"\n"
        "if test \"${1:-}\" = plugin && test \"${2:-}\" = check; then "
        "exit \"${WP_CHECK_STATUS:-0}\"; fi\n",
        encoding="utf-8",
    )
    fake_wp.chmod(0o755)
    fake_php = fake_bin / "php"
    fake_php.write_text(
        "#!/bin/sh\nif test \"${3:-}\" = --; then "
        "exit \"${CLEANUP_STATUS:-0}\"; fi\n"
        "printf '1:2:0123456789abcdef0123456789abcdef'\n",
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


def test_setup_rejects_a_preexisting_content_directory(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    content.mkdir(mode=0o700)
    result = _run_php(plugin_check._setup_payload(content, plugins))
    assert result.returncode == plugin_check.SETUP_FAILURE_EXIT
    assert content.is_dir()
    assert "Plugin Check setup failed" in result.stderr


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


def test_cleanup_rejects_external_directory_replacement(tmp_path):
    content, plugins, _source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    content.rmdir()
    content.mkdir(mode=0o700)
    result = _cleanup(content, plugins, identity)
    assert result.returncode == plugin_check.CLEANUP_FAILURE_EXIT
    assert content.is_dir()


def test_cleanup_rejects_a_completed_external_directory_symlink(tmp_path):
    content, plugins, source = _fixture_paths(tmp_path)
    identity = _setup(content, plugins)
    victim = tmp_path / "victim"
    victim.mkdir()
    victim_dropin = victim / "object-cache.php"
    shutil.copyfile(source, victim_dropin)
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
    payloads = (
        plugin_check._setup_payload(plugin_check.CONTENT_DIR, plugin_check.PLUGIN_DIR),
        plugin_check.exec_payload(),
        plugin_check._cleanup_payload(plugin_check.CONTENT_DIR, plugin_check.PLUGIN_DIR),
    )
    assert all("safe-plugin" not in payload and "'" not in payload for payload in payloads)
    assert all("rm -" not in payload and "glob(" not in payload for payload in payloads)
    assert str(plugin_check.CONTENT_DIR) in "".join(payloads)
    assert str(plugin_check.PLUGIN_DIR) in "".join(payloads)
