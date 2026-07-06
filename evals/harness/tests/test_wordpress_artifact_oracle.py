"""Tests for the deterministic WordPress artifact oracle."""

from types import SimpleNamespace

import validate_wordpress_artifact as oracle


def args(profile="static", require_tool=None):
    return SimpleNamespace(
        profile=profile,
        require_tool=require_tool or [],
        timeout_sec=5,
        wp_root=None,
        wp_env_root=None,
        plugin_check_require=None,
    )


def write_good_plugin(root):
    plugin_dir = root / "acme-members"
    plugin_dir.mkdir()
    (plugin_dir / "acme-members.php").write_text(
        """<?php
/**
 * Plugin Name: Acme Members
 *
 * @package AcmeMembers
 */
add_action( 'init', 'acme_members_register' );
function acme_members_register() {
    register_setting( 'acme_members', 'acme_members_mode' );
}
""",
        encoding="utf-8",
    )
    return plugin_dir


def test_good_plugin_static_artifact_passes(tmp_path):
    plugin_dir = write_good_plugin(tmp_path)

    result = oracle.validate_artifact("plugin", plugin_dir, args())

    assert result["status"] == "pass"
    assert result["pass"] is True


def test_plugin_static_artifact_fails_missing_package_and_short_arrays(tmp_path):
    plugin_dir = tmp_path / "wpcs-shape-gap"
    plugin_dir.mkdir()
    (plugin_dir / "wpcs-shape-gap.php").write_text(
        """<?php
/**
 * Plugin Name: WPCS Shape Gap
 */
function acme_wpcs_shape_gap() {
    $settings = [
        'mode' => 'safe',
    ];
    return [
        'settings' => $settings,
    ];
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())
    style_check = next(check for check in result["checks"] if check["id"] == "php_wpcs_shape_heuristics")

    assert result["status"] == "fail"
    assert style_check["status"] == "fail"
    assert "@package" in style_check["detail"]
    assert "short array syntax" in style_check["detail"]


def test_bad_plugin_static_artifact_fails_security_heuristics(tmp_path):
    plugin_dir = tmp_path / "unsafe-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "unsafe-plugin.php").write_text(
        """<?php
add_action( 'admin_post_acme_delete', 'acme_delete_everything' );
function acme_delete_everything() {
    global $wpdb;
    $wpdb->query( "DELETE FROM {$wpdb->posts}" );
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}

    assert result["status"] == "fail"
    assert {"plugin_header", "plugin_security_heuristics", "unsafe_commands"} <= failed


def test_abilities_plugin_requires_schemas_permissions_and_version_boundary(tmp_path):
    plugin_dir = tmp_path / "abilities-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "abilities-plugin.php").write_text(
        """<?php
/**
 * Plugin Name: Abilities Plugin
 * Requires at least: 6.9
 *
 * @package AbilitiesPlugin
 */
add_action( 'wp_abilities_api_init', 'acme_register_ability' );
function acme_register_ability() {
    wp_register_ability(
        'acme/get-status',
        array(
            'label'               => __( 'Get status', 'acme' ),
            'description'         => __( 'Returns status data.', 'acme' ),
            'category'            => 'site-information',
            'input_schema'        => array(),
            'output_schema'       => array( 'type' => 'object' ),
            'execute_callback'    => 'acme_get_status',
            'permission_callback' => function() {
                return current_user_can( 'manage_options' );
            },
        )
    );
}
function acme_get_status() {
    return array( 'ok' => true );
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())

    assert result["status"] == "pass"
    assert any(check["id"] == "plugin_ai_surface_heuristics" and check["status"] == "pass" for check in result["checks"])


def test_abilities_plugin_fails_without_permissions_or_version_boundary(tmp_path):
    plugin_dir = tmp_path / "unsafe-abilities"
    plugin_dir.mkdir()
    (plugin_dir / "unsafe-abilities.php").write_text(
        """<?php
/**
 * Plugin Name: Unsafe Abilities
 * Requires at least: 6.8
 */
function acme_register_ability() {
    wp_register_ability(
        'acme/update-post',
        array(
            'label'            => 'Update post',
            'description'      => 'Updates a post.',
            'category'         => 'data-modification',
            'execute_callback' => 'acme_update_post',
        )
    );
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}

    assert result["status"] == "fail"
    assert "plugin_ai_surface_heuristics" in failed


def test_abilities_plugin_fails_without_label_description_or_category(tmp_path):
    plugin_dir = tmp_path / "incomplete-abilities"
    plugin_dir.mkdir()
    (plugin_dir / "incomplete-abilities.php").write_text(
        """<?php
/**
 * Plugin Name: Incomplete Abilities
 * Requires at least: 6.9
 *
 * @package IncompleteAbilities
 */
add_action( 'wp_abilities_api_init', 'acme_register_ability' );
function acme_register_ability() {
    wp_register_ability(
        'acme/get-status',
        array(
            'input_schema'        => array(),
            'output_schema'       => array( 'type' => 'object' ),
            'execute_callback'    => 'acme_get_status',
            'permission_callback' => function() {
                return current_user_can( 'manage_options' );
            },
        )
    );
}
function acme_get_status() {
    return array( 'ok' => true );
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}
    ai_check = next(check for check in result["checks"] if check["id"] == "plugin_ai_surface_heuristics")

    assert result["status"] == "fail"
    assert "plugin_ai_surface_heuristics" in failed
    assert "label" in ai_check["detail"]
    assert "description" in ai_check["detail"]
    assert "category" in ai_check["detail"]


def test_ai_client_plugin_requires_error_handling_and_capability_boundary(tmp_path):
    plugin_dir = tmp_path / "ai-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ai-plugin.php").write_text(
        """<?php
/**
 * Plugin Name: AI Plugin
 * Requires at least: 7.0
 *
 * @package AIPlugin
 */
function acme_generate_summary() {
    if ( ! current_user_can( 'edit_posts' ) ) {
        return new WP_Error( 'forbidden' );
    }
    $summary = wp_ai_client_prompt( 'Summarize this post.' )->generate_text();
    if ( is_wp_error( $summary ) ) {
        return $summary;
    }
    return wp_kses_post( $summary );
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())

    assert result["status"] == "pass"


def test_mcp_adapter_readme_boundary_does_not_require_adapter_initialization(tmp_path):
    plugin_dir = tmp_path / "mcp-readme-boundary"
    plugin_dir.mkdir()
    (plugin_dir / "mcp-readme-boundary.php").write_text(
        """<?php
/**
 * Plugin Name: MCP Readme Boundary
 * Requires at least: 6.9
 *
 * @package MCPReadmeBoundary
 */
add_action( 'wp_abilities_api_init', 'acme_register_ability' );
function acme_register_ability() {
    wp_register_ability(
        'acme/get-status',
        array(
            'label'               => 'Get status',
            'description'         => 'Returns status data.',
            'category'            => 'site-information',
            'input_schema'        => array(),
            'output_schema'       => array( 'type' => 'object' ),
            'execute_callback'    => 'acme_get_status',
            'permission_callback' => function() {
                return current_user_can( 'manage_options' );
            },
        )
    );
}
function acme_get_status() {
    return array( 'ok' => true );
}
""",
        encoding="utf-8",
    )
    (plugin_dir / "readme.txt").write_text(
        "Mention wordpress/mcp-adapter discovery as a verification boundary only.\n",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())

    assert result["status"] == "pass"


def test_ai_client_plugin_fails_without_error_handling_or_capability_boundary(tmp_path):
    plugin_dir = tmp_path / "unsafe-ai"
    plugin_dir.mkdir()
    (plugin_dir / "unsafe-ai.php").write_text(
        """<?php
/**
 * Plugin Name: Unsafe AI
 * Requires at least: 6.9
 */
function acme_generate_summary() {
    return wp_ai_client_prompt( $_POST['prompt'] )->generate_text();
}
""",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("plugin", plugin_dir, args())
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}

    assert result["status"] == "fail"
    assert "plugin_ai_surface_heuristics" in failed


def test_good_block_static_artifact_passes(tmp_path):
    block_dir = tmp_path / "hero-block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        '{"apiVersion":3,"name":"acme/hero","title":"Hero","category":"widgets"}',
        encoding="utf-8",
    )
    (block_dir / "package.json").write_text(
        '{"scripts":{"build":"wp-scripts build"},"devDependencies":{"@wordpress/scripts":"latest"}}',
        encoding="utf-8",
    )

    result = oracle.validate_artifact("block", block_dir, args())

    assert result["status"] == "pass"


def test_block_npm_build_fails_when_wp_scripts_reports_missing_default_src(tmp_path, monkeypatch):
    block_dir = tmp_path / "hero-block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        '{"apiVersion":3,"name":"acme/hero","title":"Hero","category":"widgets"}',
        encoding="utf-8",
    )
    (block_dir / "package.json").write_text(
        '{"scripts":{"build":"wp-scripts build"},"devDependencies":{"@wordpress/scripts":"latest"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "npm" else None)

    def fake_run(command, cwd, _timeout):
        assert command == ["/usr/bin/npm", "run", "build"]
        assert cwd == block_dir.resolve()
        return oracle.CommandResult(0, 'Source directory "src" was not found.', "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("block", block_dir, args(require_tool=["npm-build"]))
    npm_check = next(check for check in result["checks"] if check["id"] == "npm_build")

    assert result["status"] == "fail"
    assert npm_check["status"] == "fail"
    assert 'Source directory "src" was not found' in npm_check["detail"]


def test_block_npm_build_passes_with_custom_entry(tmp_path, monkeypatch):
    block_dir = tmp_path / "hero-block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text(
        '{"apiVersion":3,"name":"acme/hero","title":"Hero","category":"widgets"}',
        encoding="utf-8",
    )
    (block_dir / "package.json").write_text(
        '{"scripts":{"build":"wp-scripts build blocks/hero/index.js --output-path=blocks/hero/build"},"devDependencies":{"@wordpress/scripts":"latest"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "npm" else None)

    def fake_run(command, cwd, _timeout):
        assert command == ["/usr/bin/npm", "run", "build"]
        assert cwd == block_dir.resolve()
        return oracle.CommandResult(0, "webpack compiled successfully", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("block", block_dir, args(require_tool=["npm-build"]))
    npm_check = next(check for check in result["checks"] if check["id"] == "npm_build")

    assert result["status"] == "pass"
    assert npm_check["status"] == "pass"


def test_bad_block_static_artifact_fails_invalid_block_json(tmp_path):
    block_dir = tmp_path / "bad-block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text('{"name":"acme/bad"', encoding="utf-8")

    result = oracle.validate_artifact("block", block_dir, args())
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}

    assert result["status"] == "fail"
    assert "block_metadata" in failed


def test_runtime_profile_blocks_when_required_tools_are_missing(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    monkeypatch.setattr(oracle.shutil, "which", lambda _name: None)

    result = oracle.validate_artifact("plugin", plugin_dir, args(profile="runtime"))
    blocked = {check["id"] for check in result["checks"] if check["status"] == "blocked"}

    assert result["status"] == "blocked"
    assert {"php_lint", "phpcs_wpcs", "plugin_check"} <= blocked


def test_runtime_profile_passes_when_required_tools_pass(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}")
    seen_commands = []

    def fake_run(command, _cwd, _timeout):
        seen_commands.append(command)
        if command[0].endswith("phpcs") and command[1] == "-i":
            return oracle.CommandResult(0, "The installed coding standards are WordPress", "")
        return oracle.CommandResult(0, "ok", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("plugin", plugin_dir, args(profile="runtime"))

    assert result["status"] == "pass"
    assert result["pass"] is True
    phpcs_run = next(command for command in seen_commands if command[0].endswith("phpcs") and "--standard=WordPress" in command)
    assert f"--ignore={','.join(oracle.PHPCS_IGNORE_PATTERNS)}" in phpcs_run


def test_runtime_profile_phpcs_ignores_dependency_directories(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    dependency_php = plugin_dir / "node_modules" / "flatted" / "php" / "flatted.php"
    dependency_php.parent.mkdir(parents=True)
    dependency_php.write_text(
        "<?php\nfunction third_party_style_we_do_not_grade(){ return array(); }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "phpcs" else None)
    seen_commands = []

    def fake_run(command, _cwd, _timeout):
        seen_commands.append(command)
        if command[0].endswith("phpcs") and command[1] == "-i":
            return oracle.CommandResult(0, "The installed coding standards are WordPress", "")
        ignore_arg = next((part for part in command if part.startswith("--ignore=")), "")
        assert "*/node_modules/*" in ignore_arg
        assert "*/vendor/*" in ignore_arg
        return oracle.CommandResult(0, "ok", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    check = oracle.check_phpcs(plugin_dir, args(), required=True)

    assert check.status == "pass"
    assert any("--standard=WordPress" in command for command in seen_commands)


def test_runtime_profile_finds_phpcs_in_wp_env_root_vendor_bin(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    env_root = tmp_path / "wp-env-project"
    phpcs = env_root / "vendor" / "bin" / "phpcs"
    phpcs.parent.mkdir(parents=True)
    phpcs.write_text("#!/bin/sh\n", encoding="utf-8")
    test_args = args(profile="runtime")
    test_args.wp_env_root = str(env_root)

    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}" if name != "phpcs" else None)

    def fake_run(command, _cwd, _timeout):
        if command[0] == str(phpcs) and command[1] == "-i":
            return oracle.CommandResult(0, "The installed coding standards are WordPress", "")
        return oracle.CommandResult(0, "ok", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("plugin", plugin_dir, test_args)

    assert result["status"] == "pass"


def test_phpunit_required_tool_uses_artifact_vendor_bin(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    (plugin_dir / "phpunit.xml").write_text("<phpunit />\n", encoding="utf-8")
    phpunit = plugin_dir / "vendor" / "bin" / "phpunit"
    phpunit.parent.mkdir(parents=True)
    phpunit.write_text("#!/bin/sh\n", encoding="utf-8")
    seen = {}

    monkeypatch.setattr(oracle.shutil, "which", lambda _name: None)

    def fake_run(command, cwd, _timeout):
        seen["command"] = command
        seen["cwd"] = cwd
        return oracle.CommandResult(0, "OK (2 tests, 4 assertions)", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("plugin", plugin_dir, args(require_tool=["phpunit"]))

    assert result["status"] == "pass"
    assert seen["command"] == [str(phpunit)]
    assert seen["cwd"] == plugin_dir.resolve()


def test_phpunit_required_tool_blocks_when_suite_exists_but_phpunit_missing(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    (plugin_dir / "phpunit.xml").write_text("<phpunit />\n", encoding="utf-8")

    monkeypatch.setattr(oracle.shutil, "which", lambda _name: None)

    result = oracle.validate_artifact("plugin", plugin_dir, args(require_tool=["phpunit"]))
    phpunit_check = next(check for check in result["checks"] if check["id"] == "phpunit")

    assert result["status"] == "blocked"
    assert phpunit_check["status"] == "blocked"
    assert "phpunit executable not found" in phpunit_check["detail"]


def test_plugin_check_fails_when_wp_cli_reports_error_rows(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "wp" else None)

    def fake_run(_command, _cwd, _timeout):
        return oracle.CommandResult(0, "line\tcolumn\ttype\tcode\tmessage\n0\t0\tERROR\tmissing_readme\tNo readme\n", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("plugin", plugin_dir, args(require_tool=["plugin-check"]))
    failed = {check["id"] for check in result["checks"] if check["status"] == "fail"}

    assert result["status"] == "fail"
    assert "plugin_check" in failed


def test_plugin_check_uses_wp_env_fallback_when_wp_is_missing(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    env_root = tmp_path / "wp-env-project"
    env_root.mkdir()
    seen = {}
    test_args = args(require_tool=["plugin-check"])
    test_args.wp_env_root = str(env_root)

    def fake_which(name):
        if name == "npx":
            return "/usr/bin/npx"
        return None

    monkeypatch.setattr(oracle.shutil, "which", fake_which)

    def fake_run(command, cwd, _timeout):
        seen["command"] = command
        seen["cwd"] = cwd
        return oracle.CommandResult(0, "Success: Checks complete. No errors found.", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("plugin", plugin_dir, test_args)

    assert result["status"] == "pass"
    assert seen["cwd"] == env_root.resolve()
    assert seen["command"][:3] == ["/usr/bin/npx", "--yes", "@wordpress/env"]
    assert seen["command"][-1] == "--require=./wp-content/plugins/plugin-check/cli.php"


def test_wp_env_required_tool_uses_explicit_environment_root(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    env_root = tmp_path / "wp-env-project"
    env_root.mkdir()
    seen = {}
    test_args = args(require_tool=["wp-env"])
    test_args.wp_env_root = str(env_root)

    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, cwd, _timeout):
        seen["command"] = command
        seen["cwd"] = cwd
        return oracle.CommandResult(0, "6.5.0", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.validate_artifact("plugin", plugin_dir, test_args)

    assert result["status"] == "pass"
    assert result["required_tools"] == ["wp-env"]
    assert result["runtime_roots"]["wp_env_root"] == str(env_root)
    assert seen["cwd"] == env_root.resolve()
    assert seen["command"][:3] == ["/usr/bin/npx", "--yes", "@wordpress/env"]
