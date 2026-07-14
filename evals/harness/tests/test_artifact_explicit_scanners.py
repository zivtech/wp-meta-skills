"""Exact-file contracts for scanners consuming a trusted SCAN_HANDOFF."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import wp_api_lint
import wp_security_gate


def _handoff_files(tmp_path: Path) -> tuple[Path, list[Path]]:
    root = tmp_path / "scan-handoff"
    (root / "build").mkdir(parents=True)
    files = [
        root / "build" / "render.php",
        root / "legacy.inc",
        root / "payload.txt",
        root / "bootstrap",
    ]
    for file_path in files:
        file_path.write_text("<?php\n", encoding="utf-8")
    return root, files


def _api_toolchain(tmp_path: Path) -> wp_api_lint.Toolchain:
    symbols = tmp_path / "symbols.json"
    symbols.write_text(json.dumps({"symbols": {}}), encoding="utf-8")
    return wp_api_lint.Toolchain(
        php="/usr/bin/php",
        phpstan=tmp_path / "phpstan",
        stubs=tmp_path / "wordpress-stubs.php",
        wp_compat_neon=tmp_path / "wp-compat.neon",
        symbols_json=symbols,
        root=tmp_path,
    )


def test_api_explicit_files_reach_every_engine_once(tmp_path, monkeypatch):
    root, files = _handoff_files(tmp_path)
    expected = tuple(files)
    seen: dict[str, list[tuple[Path, ...]]] = {}

    def record(name, value):
        seen.setdefault(name, []).append(tuple(value))

    monkeypatch.setattr(wp_api_lint, "resolve_toolchain", lambda _root: (_api_toolchain(tmp_path), None))
    monkeypatch.setattr(wp_api_lint, "load_native_snapshot", lambda _path: {"wp_version": "7.0"})
    monkeypatch.setattr(wp_api_lint, "load_vendor_hooks", lambda _root: {})
    monkeypatch.setattr(wp_api_lint, "toolchain_versions", lambda _root: {})

    def declared(_path, explicit_files=None):
        record("headers", explicit_files)
        return "6.7"

    def prefixes(_path, _extra=None, explicit_files=None):
        record("dependencies", explicit_files)
        return []

    def native(_path, _snapshot, _declared, _prefixes, _range, include_existence, explicit_files=None):
        assert include_existence is False
        record("native", explicit_files)
        return []

    def hooks(_path, _hooks, _prefixes, explicit_files=None):
        record("hooks", explicit_files)
        return []

    def neon(_path, _toolchain, _tmp, _declared, explicit_files=None):
        record("phpstan", explicit_files)
        return "parameters:\n    level: 0\n"

    monkeypatch.setattr(wp_api_lint, "declared_requires_at_least", declared)
    monkeypatch.setattr(wp_api_lint, "allowlist_prefixes", prefixes)
    monkeypatch.setattr(wp_api_lint, "native_php_findings", native)
    monkeypatch.setattr(wp_api_lint, "hook_findings", hooks)
    monkeypatch.setattr(wp_api_lint, "build_neon", neon)
    process = SimpleNamespace(returncode=0, stdout=json.dumps({"files": {}, "errors": []}), stderr="")
    monkeypatch.setattr(wp_api_lint.subprocess, "run", lambda *_args, **_kwargs: process)

    report = wp_api_lint.run_api_lint(root, explicit_files=files)

    assert report["status"] == "pass"
    assert seen == {name: [expected] for name in ("headers", "dependencies", "native", "hooks", "phpstan")}


def test_api_explicit_headers_and_phpstan_paths_ignore_suffix_policy(tmp_path):
    root, files = _handoff_files(tmp_path)
    header = files[2]
    header.write_text(
        "<?php\n/**\n * Plugin Name: Exact files\n * Requires at least: 6.7\n"
        " * Requires Plugins: acme-crm\n */\n",
        encoding="utf-8",
    )
    toolchain = _api_toolchain(tmp_path)

    assert wp_api_lint.declared_requires_at_least(root) is None
    assert list(wp_api_lint._artifact_php_texts(root, explicit_files=files)) == files
    assert wp_api_lint.declared_requires_at_least(root, explicit_files=files) == "6.7"
    assert "acme_crm_" in wp_api_lint.allowlist_prefixes(root, explicit_files=files)

    neon = wp_api_lint.build_neon(root, toolchain, tmp_path / "cache", "6.7", explicit_files=files)
    for file_path in files:
        assert f'        - "{file_path}"' in neon
    assert f'        - "{root}"' not in neon


def test_security_gate_passes_one_exact_list_to_both_phpcs_runs(tmp_path, monkeypatch):
    root, files = _handoff_files(tmp_path)
    calls: list[list[Path]] = []
    toolchain = wp_security_gate.Toolchain(
        php="/usr/bin/php",
        phpcs=tmp_path / "phpcs",
        installed_paths="/wpcs",
        root=tmp_path,
    )
    monkeypatch.setattr(wp_security_gate, "resolve_toolchain", lambda _root: (toolchain, None))

    def run_phpcs(_toolchain, php_files, _basepath, ignore_annotations, timeout_sec):
        assert timeout_sec == 120
        assert ignore_annotations is bool(len(calls))
        calls.append(php_files)
        return 0, {"files": {}}, "", ["phpcs"]

    monkeypatch.setattr(wp_security_gate, "_run_phpcs", run_phpcs)

    report = wp_security_gate.run_security_gate(root, explicit_files=files)

    assert report["status"] == "pass"
    assert len(calls) == 2
    assert calls[0] is calls[1]
    assert calls[0] == files


@pytest.mark.parametrize("scanner", ["api", "security"])
@pytest.mark.parametrize("case", ["duplicate", "escape", "missing", "directory"])
def test_explicit_scanners_reject_invalid_lists(tmp_path, scanner, case):
    root = tmp_path / "scan-handoff"
    root.mkdir()
    regular = root / "code.php"
    regular.write_text("<?php\n", encoding="utf-8")
    directory = root / "nested"
    directory.mkdir()
    outside = tmp_path / "outside.php"
    outside.write_text("<?php\n", encoding="utf-8")
    candidates = {
        "duplicate": [regular, directory / ".." / regular.name],
        "escape": [outside],
        "missing": [root / "missing.php"],
        "directory": [directory],
    }[case]

    runner = wp_api_lint.run_api_lint if scanner == "api" else wp_security_gate.run_security_gate
    with pytest.raises(ValueError):
        runner(root, explicit_files=candidates)
