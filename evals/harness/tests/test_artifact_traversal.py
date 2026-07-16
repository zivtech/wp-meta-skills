"""Root-relative traversal regressions for legacy artifact scanners."""

from pathlib import Path

import validate_wordpress_artifact as oracle
import wp_api_lint


def _write_php(root: Path, relative: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("<?php\necho 'scanned';\n", encoding="utf-8")
    return target


def test_oracle_scans_artifact_beneath_external_build_ancestor(tmp_path):
    root = tmp_path / "build" / "artifact"
    expected = _write_php(root, "plugin.php")

    assert oracle.iter_files(root, {".php"}) == [expected]


def test_oracle_scans_explicit_root_named_build_or_dist(tmp_path):
    build_root = tmp_path / "build"
    dist_root = tmp_path / "dist"
    build_php = _write_php(build_root, "build.php")
    dist_php = _write_php(dist_root, "dist.php")

    assert oracle.iter_files(build_root, {".php"}) == [build_php]
    assert oracle.iter_files(dist_root, {".php"}) == [dist_php]


def test_oracle_keeps_nested_exclusions(tmp_path):
    root = tmp_path / "artifact"
    expected = _write_php(root, "plugin.php")
    for excluded in ("build", "dist", "node_modules", "vendor", ".git", ".wp-env", "coverage"):
        _write_php(root, f"{excluded}/hidden.php")

    assert oracle.iter_files(root, {".php"}) == [expected]


def test_api_lint_scans_artifact_beneath_external_build_ancestor(tmp_path):
    root = tmp_path / "build" / "artifact"
    expected = _write_php(root, "plugin.php")

    assert wp_api_lint.iter_php_files(root) == [expected]


def test_api_lint_scans_explicit_root_named_build_or_dist(tmp_path):
    build_root = tmp_path / "build"
    dist_root = tmp_path / "dist"
    build_php = _write_php(build_root, "build.php")
    dist_php = _write_php(dist_root, "dist.php")

    assert wp_api_lint.iter_php_files(build_root) == [build_php]
    assert wp_api_lint.iter_php_files(dist_root) == [dist_php]


def test_api_lint_keeps_nested_exclusions(tmp_path):
    root = tmp_path / "artifact"
    expected = _write_php(root, "plugin.php")
    for excluded in ("build", "dist", "node_modules", "vendor", ".git", ".wp-env", "coverage"):
        _write_php(root, f"{excluded}/hidden.php")

    assert wp_api_lint.iter_php_files(root) == [expected]
