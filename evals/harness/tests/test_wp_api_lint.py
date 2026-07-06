"""Tests for the WordPress API-existence and version-range lint (phase 1).

Unit tests run against recorded PHPStan JSON output and are hermetic. Tests
marked `real_api_lint` run the pinned PHPStan toolchain end-to-end and skip
(with the blocking reason) when `evals/harness/php-tools` has not been
composer-installed; CI installs the toolchain so they always run there.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import certify_wordpress_executor_artifact as certifier
import validate_wordpress_artifact as oracle
import wp_api_lint


HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wp_api_lint"

TOOLCHAIN, TOOLCHAIN_ERROR = wp_api_lint.resolve_toolchain()
needs_toolchain = pytest.mark.skipif(TOOLCHAIN is None, reason=f"pinned PHP toolchain unavailable: {TOOLCHAIN_ERROR}")


def oracle_args():
    return SimpleNamespace(
        profile="static",
        require_tool=[],
        timeout_sec=120,
        wp_root=None,
        wp_env_root=None,
        plugin_check_require=None,
    )


def certifier_args(packet, out_dir, result_dir):
    return SimpleNamespace(
        executor="plugin",
        packet=packet,
        out_dir=out_dir,
        overwrite=False,
        result_dir=result_dir,
        profile="static",
        require_tool=[],
        wp_root=None,
        wp_env_root=None,
        plugin_check_require=None,
        timeout_sec=120,
    )


# Recorded from `phpstan analyse --error-format=json` (phpstan 2.2.3,
# wordpress-stubs 7.0.0, wp-compat 1.5.0) over a probe plugin; shapes verified
# 2026-07-02.
RECORDED_MIXED_OUTPUT = {
    "totals": {"errors": 0, "file_errors": 3},
    "files": {
        "/work/artifact/probe-plugin.php": {
            "errors": 3,
            "messages": [
                {
                    "message": "get_template_hierarchy() is only available since WordPress version 6.1.0.",
                    "line": 14,
                    "ignorable": True,
                    "identifier": "WPCompat.functionNotAvailable",
                },
                {
                    "message": "Function wp_sanitize_email_address not found.",
                    "line": 15,
                    "ignorable": True,
                    "tip": "Learn more at https://phpstan.org/user-guide/discovering-symbols",
                    "identifier": "function.notFound",
                },
                {
                    "message": "Instantiated class Probe_Unknown_Class not found.",
                    "line": 29,
                    "ignorable": True,
                    "tip": "Learn more at https://phpstan.org/user-guide/discovering-symbols",
                    "identifier": "class.notFound",
                },
            ],
        }
    },
    "errors": [],
}

RECORDED_PARSE_ERROR_OUTPUT = {
    "totals": {"errors": 0, "file_errors": 1},
    "files": {
        "/work/artifact/broken.php": {
            "errors": 1,
            "messages": [
                {
                    "message": "Syntax error, unexpected '{', expecting T_VARIABLE on line 2",
                    "line": 2,
                    "ignorable": False,
                    "identifier": "phpstan.parse",
                }
            ],
        }
    },
    "errors": [],
}

SMALL_INDEX = wp_api_lint.SymbolIndex(
    functions=("get_template_hierarchy", "sanitize_email", "sanitize_text_field"),
    classes=("WP_Error", "WP_Query"),
)


def parse(output, prefixes=None, declared="6.0"):
    return wp_api_lint.parse_phpstan_output(
        output,
        Path("/work/artifact"),
        SMALL_INDEX,
        declared,
        "7.0.0",
        prefixes or [],
    )


def test_parse_phpstan_output_classifies_findings_and_suggests():
    findings, analysis_errors, advisory = parse(RECORDED_MIXED_OUTPUT)

    assert analysis_errors == []
    assert advisory == []
    assert [finding["class"] for finding in findings] == ["version_range", "unknown_function", "unknown_class"]

    range_finding, function_finding, class_finding = findings
    assert range_finding["symbol"] == "get_template_hierarchy"
    assert range_finding["introduced_in"] == "6.1.0"
    assert range_finding["declared_range"] == {"requires_at_least": "6.0", "snapshot": "7.0.0"}
    assert range_finding["confidence"] == "exact"

    assert function_finding["symbol"] == "wp_sanitize_email_address"
    assert function_finding["file"] == "probe-plugin.php"
    assert function_finding["line"] == 15
    assert "sanitize_email" in function_finding["suggestions"]
    assert function_finding["declared_range"] is None

    assert class_finding["symbol"] == "Probe_Unknown_Class"
    assert class_finding["symbol_kind"] == "class"


def test_parse_phpstan_output_routes_parse_errors_and_advisory():
    output = json.loads(json.dumps(RECORDED_PARSE_ERROR_OUTPUT))
    output["files"]["/work/artifact/broken.php"]["messages"].append(
        {"message": "Some future rule fired.", "line": 9, "ignorable": True, "identifier": "argument.type"}
    )
    findings, analysis_errors, advisory = parse(output)

    assert findings == []
    assert len(analysis_errors) == 1
    assert analysis_errors[0]["identifier"] == "phpstan.parse"
    assert len(advisory) == 1
    assert advisory[0]["identifier"] == "argument.type"


def test_parse_phpstan_output_maps_hook_version_range():
    output = {
        "totals": {"errors": 0, "file_errors": 1},
        "files": {
            "/work/artifact/hooks.php": {
                "errors": 1,
                "messages": [
                    {
                        "message": "Filter block_editor_settings_all is only available since WordPress version 5.8.0.",
                        "line": 4,
                        "ignorable": True,
                        "identifier": "WPCompat.filterNotAvailable.blockeditorsettingsall",
                    }
                ],
            }
        },
        "errors": [],
    }
    findings, _analysis_errors, advisory = parse(output, declared="5.5")

    assert advisory == []
    assert len(findings) == 1
    assert findings[0]["class"] == "version_range"
    assert findings[0]["symbol_kind"] == "hook"
    assert findings[0]["symbol"] == "block_editor_settings_all"
    assert findings[0]["introduced_in"] == "5.8.0"


def test_parse_phpstan_output_extracts_extended_unknown_class():
    # Recorded shape from a test file extending a class outside the stubs.
    output = {
        "totals": {"errors": 0, "file_errors": 2},
        "files": {
            "/work/artifact/includes/api.php": {
                "errors": 2,
                "messages": [
                    {
                        "message": "Class Acme_Endpoint extends unknown class WP_REST_Controller_V2.",
                        "line": 3,
                        "ignorable": True,
                        "identifier": "class.notFound",
                    },
                    {
                        "message": "Call to an undefined method Acme_Endpoint::register_routes_v2().",
                        "line": 11,
                        "ignorable": True,
                        "identifier": "method.notFound",
                    },
                ],
            }
        },
        "errors": [],
    }
    findings, _analysis_errors, _advisory = parse(output)

    assert findings[0]["class"] == "unknown_class"
    assert findings[0]["symbol"] == "WP_REST_Controller_V2"
    assert findings[1]["class"] == "unknown_method"
    assert findings[1]["symbol"] == "Acme_Endpoint::register_routes_v2"


def test_allowlisted_prefix_degrades_unknown_symbols_to_advisory():
    output = {
        "totals": {"errors": 0, "file_errors": 1},
        "files": {
            "/work/artifact/woo.php": {
                "errors": 1,
                "messages": [
                    {
                        "message": "Function wc_get_order not found.",
                        "line": 7,
                        "ignorable": True,
                        "identifier": "function.notFound",
                    }
                ],
            }
        },
        "errors": [],
    }
    findings, _analysis_errors, _advisory = parse(output, prefixes=["wc_"])

    assert len(findings) == 1
    assert findings[0]["allowlisted"] is True
    assert findings[0]["confidence"] == "advisory"


def test_declared_requires_at_least_reads_plugin_and_theme_headers(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.php").write_text(
        "<?php\n/**\n * Plugin Name: Sample\n * Requires at least: 6.2\n */\n",
        encoding="utf-8",
    )
    assert wp_api_lint.declared_requires_at_least(plugin_dir) == "6.2"

    theme_dir = tmp_path / "theme"
    theme_dir.mkdir()
    (theme_dir / "style.css").write_text(
        "/*\nTheme Name: Sample Theme\nRequires at least: 6.4\n*/\n",
        encoding="utf-8",
    )
    assert wp_api_lint.declared_requires_at_least(theme_dir) == "6.4"

    bare_dir = tmp_path / "bare"
    bare_dir.mkdir()
    (bare_dir / "code.php").write_text("<?php\n", encoding="utf-8")
    assert wp_api_lint.declared_requires_at_least(bare_dir) is None


def test_requires_plugins_header_extends_allowlist(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.php").write_text(
        "<?php\n/**\n * Plugin Name: Sample\n * Requires Plugins: woocommerce, acme-crm\n */\n",
        encoding="utf-8",
    )
    prefixes = wp_api_lint.allowlist_prefixes(plugin_dir, ["custom_"])

    assert "custom_" in prefixes
    assert "wc_" in prefixes
    assert "woocommerce_" in prefixes
    assert "acme_crm_" in prefixes


def test_build_neon_includes_wp_compat_only_with_declared_minimum(tmp_path):
    toolchain = wp_api_lint.Toolchain(
        php="/usr/bin/php",
        phpstan=tmp_path / "vendor" / "bin" / "phpstan",
        stubs=tmp_path / "stubs.php",
        wp_compat_neon=tmp_path / "extension.neon",
        symbols_json=tmp_path / "symbols.json",
        root=tmp_path,
    )
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    with_range = wp_api_lint.build_neon(artifact, toolchain, tmp_path / "tmp", "6.0")
    without_range = wp_api_lint.build_neon(artifact, toolchain, tmp_path / "tmp", None)

    assert "extension.neon" in with_range
    assert 'requiresAtLeast: "6.0"' in with_range
    assert "extension.neon" not in without_range
    assert "WPCompat" not in without_range
    assert "level: 0" in without_range
    # Excludes are artifact-scoped so artifacts living under a tests/ directory
    # are still analyzed while their own test dirs are not.
    assert f'"{artifact}/tests/*"' in with_range
    assert f'"{artifact}/*/tests/*"' in with_range
    assert f'"{artifact}/vendor/*"' in with_range
    assert '"*/tests/*"' not in with_range


def test_run_api_lint_blocked_only_without_toolchain_and_snapshot(tmp_path):
    """Phase 2: no toolchain degrades to the native snapshot engine; blocked
    now requires the committed snapshot to be missing as well."""
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "plugin.php").write_text("<?php\n/**\n * Plugin Name: Sample\n */\n", encoding="utf-8")

    report = wp_api_lint.run_api_lint(
        artifact,
        php_tools_root=tmp_path / "empty-tools",
        snapshot_path=tmp_path / "missing-snapshot.json",
    )

    assert report["status"] == "blocked"
    assert report["findings"] == []
    reason = report["blocked_reason"]
    assert "composer install" in reason or "php executable" in reason
    assert "snapshot also missing" in reason
    assert wp_api_lint.summarize_report(report) == reason


def test_run_api_lint_degrades_to_native_engine_without_toolchain(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "plugin.php").write_text(
        "<?php\n/**\n * Plugin Name: Sample\n * Requires at least: 6.0\n */\n"
        "function sample_run() { wp_sanitize_email_address( 'a@example.com' ); }\n",
        encoding="utf-8",
    )

    report = wp_api_lint.run_api_lint(artifact, php_tools_root=tmp_path / "empty-tools")

    assert report["status"] == "fail"
    assert report["engines"]["native_symbols"] == "ran"
    assert report["engines"]["phpstan"].startswith("unavailable")
    symbols = [finding["symbol"] for finding in report["findings"]]
    assert "wp_sanitize_email_address" in symbols
    assert any("native fallback" in line for line in report["negative_space"])


def test_summarize_report_phrases_pass_fail_and_blocked():
    passing = {
        "status": "pass",
        "declared_requires_at_least": "6.0",
        "version_range_checked": True,
        "findings": [],
        "analysis_errors": [],
    }
    assert "no unknown core symbols" in wp_api_lint.summarize_report(passing)
    assert "Requires at least: 6.0" in wp_api_lint.summarize_report(passing)

    unchecked = dict(passing, version_range_checked=False, declared_requires_at_least=None)
    assert "version range not evaluated" in wp_api_lint.summarize_report(unchecked)

    failing = {
        "status": "fail",
        "findings": [
            {
                "class": "unknown_function",
                "symbol": "wp_sanitize_email_address",
                "symbol_kind": "function",
                "file": "plugin.php",
                "line": 15,
                "confidence": "exact",
                "allowlisted": False,
                "declared_range": None,
                "introduced_in": None,
                "deprecated_in": None,
                "replacement": None,
                "suggestions": ["sanitize_email"],
                "evidence": "Function wp_sanitize_email_address not found.",
            }
        ],
        "analysis_errors": [],
    }
    summary = wp_api_lint.summarize_report(failing)
    assert "1 API finding(s)" in summary
    assert "wp_sanitize_email_address" in summary
    assert "did you mean sanitize_email?" in summary


@pytest.mark.real_api_lint
def test_check_api_existence_skips_without_php_files(tmp_path):
    check, report = oracle.check_api_existence(tmp_path)

    assert check.status == "skip"
    assert report is None


@pytest.mark.real_api_lint
@needs_toolchain
def test_hallucination_bait_fails_api_existence_with_function_and_hook():
    result = oracle.validate_artifact("plugin", FIXTURES / "api-hallucination-bait", oracle_args())

    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}
    assert result["status"] == "fail"
    assert failed == {"api_existence"}

    api_check = next(check for check in result["checks"] if check["id"] == "api_existence")
    assert "did you mean sanitize_email?" in api_check["detail"]

    findings = result["api_lint"]["findings"]
    assert len(findings) == 2

    by_class = {finding["class"]: finding for finding in findings}
    assert by_class["unknown_function"]["symbol"] == "wp_sanitize_email_address"
    assert by_class["unknown_function"]["confidence"] == "exact"
    assert "sanitize_email" in by_class["unknown_function"]["suggestions"]

    assert by_class["unknown_hook"]["symbol"] == "wp_enqueue_script_loader"
    assert by_class["unknown_hook"]["confidence"] == "exact"
    assert "wp_enqueue_scripts" in by_class["unknown_hook"]["suggestions"]


@pytest.mark.real_api_lint
@needs_toolchain
def test_version_range_bait_flags_and_guard_flips_green():
    bait = oracle.validate_artifact("plugin", FIXTURES / "version-range-bait", oracle_args())
    assert bait["status"] == "fail"
    findings = bait["api_lint"]["findings"]
    assert len(findings) == 1
    assert findings[0]["class"] == "version_range"
    assert findings[0]["symbol"] == "get_template_hierarchy"
    assert findings[0]["introduced_in"] == "6.1.0"
    assert findings[0]["declared_range"]["requires_at_least"] == "6.0"

    guarded = oracle.validate_artifact("plugin", FIXTURES / "version-range-guarded", oracle_args())
    assert guarded["status"] == "pass"
    assert guarded["api_lint"]["findings"] == []


@pytest.mark.real_api_lint
@needs_toolchain
def test_clean_control_passes_with_zero_findings():
    result = oracle.validate_artifact("plugin", FIXTURES / "clean-control", oracle_args())

    assert result["status"] == "pass"
    assert result["api_lint"]["status"] == "pass"
    assert result["api_lint"]["findings"] == []
    assert result["api_lint"]["version_range_checked"] is True
    assert result["api_lint"]["negative_space"]


@pytest.mark.real_api_lint
@needs_toolchain
def test_repository_golden_plugin_packet_passes_real_api_lint(tmp_path):
    packet = REPO / "evals" / "suites" / "wordpress-plugin-executor" / "examples" / "smoke-wordpress-v1.materializable-packet.md"
    result_dir = tmp_path / "result"
    result = certifier.certify_executor_artifact(certifier_args(packet, tmp_path / "generated", result_dir))

    assert result["status"] == "pass"
    assert result["artifact_gate"]["api_lint"]["status"] == "pass"
    api_lint_path = result_dir / "api-lint.json"
    assert api_lint_path.exists()
    written = json.loads(api_lint_path.read_text(encoding="utf-8"))
    assert written["schema"] == wp_api_lint.SCHEMA
    assert written["schema_version"] == wp_api_lint.SCHEMA_VERSION


@pytest.mark.real_api_lint
@needs_toolchain
def test_cli_reports_bait_and_writes_out_file(tmp_path, capsys):
    out_path = tmp_path / "api-lint.json"
    exit_code = wp_api_lint.main(
        ["--path", str(FIXTURES / "api-hallucination-bait"), "--out", str(out_path)]
    )

    assert exit_code == 1
    assert out_path.exists()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["status"] == "fail"
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "fail"


# ---------------------------------------------------------------------------
# Phase-2 native engines: MIT snapshot deprecations + vendor-hooks existence.
# These are hermetic: the native snapshot is committed and the hooks data is
# written into a throwaway php-tools root, so no Composer toolchain is needed.
# ---------------------------------------------------------------------------

def _fake_hooks_root(tmp_path, actions=None, filters=None):
    hooks_dir = tmp_path / "php-tools" / "vendor" / "wp-hooks" / "wordpress-core" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "actions.json").write_text(
        json.dumps({"hooks": [{"name": name} for name in (actions or [])]}), encoding="utf-8"
    )
    (hooks_dir / "filters.json").write_text(
        json.dumps({"hooks": [{"name": name} for name in (filters or [])]}), encoding="utf-8"
    )
    return tmp_path / "php-tools"


def test_version_gt_pads_segments():
    assert wp_api_lint.version_gt("6.9.0", "6.2")
    assert not wp_api_lint.version_gt("6.9.0", "6.9")
    assert not wp_api_lint.version_gt("6.9", "6.9.0")
    assert wp_api_lint.version_gt("7.0", "6.9.1")


def test_deprecation_bait_names_successors():
    report = wp_api_lint.run_api_lint(FIXTURES / "deprecation-bait")

    assert report["status"] == "fail"
    deprecated = {f["symbol"]: f for f in report["findings"] if f["class"] == "deprecated_api"}
    assert deprecated["wp_login"]["deprecated_in"] == "2.5.0"
    assert deprecated["wp_login"]["replacement"] == "wp_signon()"
    assert deprecated["get_all_category_ids"]["deprecated_in"] == "4.0.0"
    assert deprecated["get_all_category_ids"]["replacement"] == "get_terms()"
    sentence = wp_api_lint.summarize_report(report)
    assert "wp_signon()" in sentence


def test_deprecation_clean_control_passes():
    report = wp_api_lint.run_api_lint(FIXTURES / "deprecation-clean")

    assert report["status"] == "pass"
    assert not [f for f in report["findings"] if f["class"] == "deprecated_api"]


def test_unknown_hook_fails_with_suggestion(tmp_path):
    tools = _fake_hooks_root(tmp_path, actions=["init", "wp_enqueue_scripts", "admin_menu"])
    artifact = tmp_path / "acme-hooks"
    artifact.mkdir()
    (artifact / "acme-hooks.php").write_text(
        "<?php\n/**\n * Plugin Name: Acme Hooks\n * Requires at least: 6.0\n */\n"
        "add_action( 'wp_enqueue_script_loader', 'acme_hooks_assets' );\n"
        "function acme_hooks_assets() {}\n",
        encoding="utf-8",
    )

    report = wp_api_lint.run_api_lint(artifact, php_tools_root=tools)

    assert report["engines"]["hooks"] == "ran"
    hooks = [f for f in report["findings"] if f["class"] == "unknown_hook"]
    assert [f["symbol"] for f in hooks] == ["wp_enqueue_script_loader"]
    assert hooks[0]["confidence"] == "exact"
    assert "wp_enqueue_scripts" in hooks[0]["suggestions"]
    assert report["status"] == "fail"


def test_dynamic_and_generic_pattern_hooks_stay_advisory(tmp_path):
    tools = _fake_hooks_root(
        tmp_path,
        actions=["init", "save_post_{$post->post_type}", "edit_{$taxonomy}", "wp_{$field}"],
    )
    artifact = tmp_path / "acme-dynamic"
    artifact.mkdir()
    (artifact / "acme-dynamic.php").write_text(
        "<?php\n/**\n * Plugin Name: Acme Dynamic\n * Requires at least: 6.0\n */\n"
        "add_filter( 'save_post_' . $type, 'acme_dynamic_cb' );\n"
        "add_action( 'edit_category', 'acme_dynamic_cb' );\n"
        "add_action( 'save_post_product', 'acme_dynamic_cb' );\n"
        "function acme_dynamic_cb() {}\n",
        encoding="utf-8",
    )

    report = wp_api_lint.run_api_lint(artifact, php_tools_root=tools)

    assert report["status"] == "pass"
    advisories = {f["symbol"]: f for f in report["findings"] if f["class"] == "unknown_hook"}
    # Concatenated name -> advisory; edit_category matches only the generic
    # edit_{$taxonomy} pattern -> advisory; save_post_product matches the
    # specific save_post_{...} pattern -> silently allowed. The bare
    # wp_{$field} catch-all carries no information and never allows.
    assert set(advisories) == {"save_post_", "edit_category"}
    assert all(f["confidence"] == "advisory" for f in advisories.values())


def test_artifact_defined_hooks_and_allow_prefix(tmp_path):
    tools = _fake_hooks_root(tmp_path, actions=["init"])
    artifact = tmp_path / "acme-custom"
    artifact.mkdir()
    (artifact / "acme-custom.php").write_text(
        "<?php\n/**\n * Plugin Name: Acme Custom\n * Requires at least: 6.0\n */\n"
        "add_action( 'acme_custom_ready', 'acme_custom_on_ready' );\n"
        "add_action( 'woocommerce_checkout_create_order', 'acme_custom_woo' );\n"
        "function acme_custom_boot() { do_action( 'acme_custom_ready' ); }\n"
        "function acme_custom_on_ready() {}\n"
        "function acme_custom_woo() {}\n",
        encoding="utf-8",
    )

    strict = wp_api_lint.run_api_lint(artifact, php_tools_root=tools)
    assert strict["status"] == "fail"
    assert [f["symbol"] for f in strict["findings"] if f["confidence"] == "exact"] == [
        "woocommerce_checkout_create_order"
    ]

    allowed = wp_api_lint.run_api_lint(
        artifact, php_tools_root=tools, extra_allow_prefixes=["woocommerce_"]
    )
    assert allowed["status"] == "pass"


def test_native_engine_skips_methods_and_namespaced_calls(tmp_path):
    artifact = tmp_path / "acme-oop"
    artifact.mkdir()
    (artifact / "acme-oop.php").write_text(
        "<?php\n/**\n * Plugin Name: Acme OOP\n * Requires at least: 6.0\n */\n"
        "function acme_oop_run( $client ) {\n"
        "    $client->totally_made_up_method();\n"
        "    Acme\\Vendor\\made_up_namespaced();\n"
        "    $result = \\wp_signon( array() );\n"
        "    return $result;\n"
        "}\n",
        encoding="utf-8",
    )

    report = wp_api_lint.run_api_lint(artifact, php_tools_root=tmp_path / "empty-tools")

    # Method calls and namespace-qualified calls are out of native scope; the
    # fully-qualified global \wp_signon() resolves against the snapshot.
    assert report["status"] == "pass"
    assert not [f for f in report["findings"] if f["confidence"] == "exact"]
