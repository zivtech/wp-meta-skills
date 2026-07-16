"""Tests for the deterministic WordPress artifact oracle."""

import ast
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import artifact_staging
import artifact_execution
import materialize_wordpress_executor_packet as materializer
import sandboxed_package_runner
import validate_wordpress_artifact as oracle
import workspace_lease


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


def import_sandbox_output(source, parent):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive:
        archive.add(source,arcname=".")
    stream.seek(0)
    return artifact_staging.import_tar_stream(stream,parent,dependency_policy="strict")


def test_good_plugin_static_artifact_passes(tmp_path):
    plugin_dir = write_good_plugin(tmp_path)

    result = oracle.validate_artifact("plugin", plugin_dir, args())

    assert result["status"] == "pass"
    assert result["pass"] is True


def test_standalone_validation_scans_fresh_stage_and_cleans_without_mutating_caller(tmp_path, monkeypatch):
    plugin_dir=write_good_plugin(tmp_path); before=artifact_staging.digest_regular_tree(plugin_dir); seen={}
    def structural(artifact_type,path,timeout_sec=120,extras=None):
        seen["view"]=path
        assert artifact_type=="plugin" and isinstance(path, oracle.artifact_snapshot_scan.ArtifactSnapshotView)
        assert [entry.path.as_posix() for entry in path.entries] == ["acme-members.php"]
        return [oracle.pass_check("staged_static","staged root scanned")]
    monkeypatch.setattr(oracle,"structural_checks",structural); monkeypatch.setattr(oracle,"runtime_checks",lambda *_args,**_kwargs:[])
    result=oracle.validate_artifact("plugin",plugin_dir,args())
    assert result["source_path"]==str(plugin_dir.resolve()) and result["artifact_path"]==oracle.repo_relative(plugin_dir.resolve())
    assert not Path(result["execution_copy"]).exists() and Path(result["execution_copy"]) != plugin_dir.resolve()
    assert result["execution_retained"] is False and len(result["manifest_sha256"])==64
    assert result["artifact_retention"]["retained"] is False
    assert result["artifact_retention"]["components"]["input_copy"]["state"] == "removed"
    assert result["artifact_retention"]["components"]["sandbox_output"]["state"] == "not_created"
    assert result["sandbox_posture"]=={"generated_execution":"not_requested","host_fallback":False,"static_scan_root":"fd_snapshot_and_trusted_scan_handoff"}
    assert artifact_staging.digest_regular_tree(plugin_dir)==before
    assert ".workspace-lease" not in json.dumps(result) and "lease_id" not in result


def test_standalone_debug_retain_reports_actual_copy_without_exposing_lease_token(tmp_path, monkeypatch):
    plugin_dir=write_good_plugin(tmp_path); test_args=args(); test_args.debug_retain=True
    monkeypatch.setattr(oracle,"structural_checks",lambda *_args,**_kwargs:[oracle.pass_check("staged_static","ok")]); monkeypatch.setattr(oracle,"runtime_checks",lambda *_args,**_kwargs:[])
    result=oracle.validate_artifact("plugin",plugin_dir,test_args); copy=Path(result["execution_copy"])
    try:
        assert result["execution_retained"] is True and copy.exists() and copy!=plugin_dir.resolve()
        assert result["artifact_retention"]["components"]["input_copy"]["state"] == "retained"
        assert ".workspace-lease" not in json.dumps(result) and "lease_id" not in result
    finally:
        lease=next(value for value in workspace_lease._LIVE_LEASES.values() if value.root==copy.parent)
        workspace_lease.cleanup(lease)


def test_standalone_staging_dual_failure_reports_retained_input_copy(tmp_path,monkeypatch):
    plugin_dir=write_good_plugin(tmp_path); original_cleanup=workspace_lease.cleanup
    monkeypatch.setattr(artifact_staging,"_manifest_from_fd",lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("staging verification failed")))
    monkeypatch.setattr(artifact_staging.workspace_lease,"cleanup",lambda _lease:(_ for _ in ()).throw(workspace_lease.WorkspaceCleanupError("cleanup failed")))
    result=oracle.validate_artifact("plugin",plugin_dir,args())
    component=result["artifact_retention"]["components"]["input_copy"]
    assert result["status"]=="blocked" and result["execution_retained"] is True
    assert result["execution_copy"]==component["recovery_path"]==component["resource_path"]
    assert component["state"]=="retained" and component["exists"] and component["live"]
    assert component["error"]=="WorkspaceCleanupError: cleanup did not complete normally"
    assert any(check["id"]=="artifact_cleanup" and check["status"]=="blocked" for check in result["checks"])
    retained=next(
        lease for lease in workspace_lease._LIVE_LEASES.values()
        if lease.root/"artifact"==Path(result["execution_copy"])
    )
    monkeypatch.setattr(artifact_staging.workspace_lease,"cleanup",original_cleanup)
    original_cleanup(retained)
    live_before=set(workspace_lease._LIVE_LEASES)
    ordinary=oracle.validate_artifact("plugin",plugin_dir,args())
    assert ordinary["execution_retained"] is False and ordinary["execution_copy"] is None
    assert ordinary["artifact_retention"]["components"]["input_copy"]["state"]=="not_created"
    assert set(workspace_lease._LIVE_LEASES)==live_before


def test_approved_npm_build_routes_exact_staged_capability_to_sandbox(tmp_path, monkeypatch):
    packet=oracle.ROOT/"evals/suites/wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md"; source=tmp_path/"source"
    assert materializer.materialize_packet("block",packet.read_text(),source)["pass"]
    staged=artifact_staging.stage_tree(source); seen={}
    def run(request):
        seen["request"]=request
        return sandboxed_package_runner.SandboxResult("blocked",None,"","",None,"bounded","container")
    monkeypatch.setattr(artifact_execution.sandboxed_package_runner,"run_sandbox",run)
    try:
        outcome=artifact_execution.run_generated(staged,"npm-build",5)
        assert outcome.status=="blocked" and seen["request"].staged is staged
        assert seen["request"].argv==("npm","run","build") and seen["request"].acquisition=="block-scripts-32.4.1-smoke"
        assert seen["request"].environment==(("HOME","/home/sandbox"),)
    finally: workspace_lease.cleanup(staged.lease)


@pytest.mark.parametrize(
    "phase,image,argv",
    [
        ("npm-build", "node", ("npm", "run", "build")),
        ("phpunit", "composer", ("php", "vendor/bin/phpunit")),
    ],
)
def test_generated_phases_bind_exact_private_home(
    tmp_path, monkeypatch, phase, image, argv
):
    source=tmp_path/"source"; source.mkdir(); (source/"manifest.json").write_text("{}")
    staged=artifact_staging.stage_tree(source); seen={}
    monkeypatch.setattr(artifact_execution,"_profile",lambda *_args:"approved")
    monkeypatch.setattr(
        artifact_execution,"_image",lambda kind:f"{image}@sha256:"+"a"*64
    )
    def run(request):
        seen["request"]=request
        return sandboxed_package_runner.SandboxResult(
            "blocked",None,"","",None,"bounded","container"
        )
    monkeypatch.setattr(artifact_execution.sandboxed_package_runner,"run_sandbox",run)
    try:
        outcome=artifact_execution.run_generated(staged,phase,5)
        assert outcome.status=="blocked"
        assert seen["request"].argv==argv
        assert seen["request"].environment==(("HOME","/home/sandbox"),)
    finally: workspace_lease.cleanup(staged.lease)


@pytest.mark.parametrize(
    "environment",
    [
        (),
        (("HOME","/tmp"),),
        (("HOME","/home/sandbox/child"),),
        (("HOME","/home/sandbox"),("HOME","/home/sandbox")),
        (("HOME","/home/sandbox"),("TMPDIR","/tmp")),
        (("HOME","/home/sandbox"),("XDG_CACHE_HOME","/cache")),
    ],
)
def test_generated_adapter_rejects_private_home_contract_drift(environment):
    with pytest.raises(ValueError,match="generated environment contract drift"):
        artifact_execution._generated_environment(environment)


def test_oracle_retains_typed_sandbox_import_cleanup_evidence_end_to_end(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"package.json").write_text("{}")
    retained=import_sandbox_output(source,tmp_path/"retained-output")
    error="WorkspaceCleanupError: cleanup did not complete normally"
    receipt=artifact_staging.StagingCleanupReceipt(
        "sandbox_output",artifact_staging.StageRole.SANDBOX_OUTPUT,retained.lease,retained.root,
        "retained",True,True,str(retained.root),error,
    )
    sandbox=sandboxed_package_runner.SandboxResult(
        "blocked",None,"","",None,"import blocked","container",staging_cleanup_receipts=(receipt,)
    )
    monkeypatch.setattr(artifact_execution,"_profile",lambda *_args:"approved")
    monkeypatch.setattr(artifact_execution,"_image",lambda _kind:"node@sha256:"+"a"*64)
    monkeypatch.setattr(artifact_execution.sandboxed_package_runner,"run_sandbox",lambda _request:sandbox)
    monkeypatch.setattr(oracle,"structural_checks",lambda *_args,**_kwargs:[oracle.pass_check("static","ok")])
    monkeypatch.setattr(oracle,"trusted_external_checks",lambda *_args,**_kwargs:[])
    try:
        result=oracle.validate_artifact("block",source,args(require_tool=["npm-build"]))
        component=result["artifact_retention"]["components"]["sandbox_output"]
        assert result["status"]=="blocked" and component["state"]=="retained"
        assert component["recovery_path"]==str(retained.root) and component["error"]==error
        assert component["exists"] is True and component["live"] is True
        assert [item["resource_path"] for item in component["resources"]]==[str(retained.root)]
    finally: workspace_lease.cleanup(retained.lease)


def test_generated_output_cleanup_failure_blocks_gate(tmp_path, monkeypatch):
    source = tmp_path / "source"
    output_source = tmp_path / "output"
    source.mkdir()
    output_source.mkdir()
    (source / "package.json").write_text("{}\n", encoding="utf-8")
    (output_source / "built.js").write_text("built\n", encoding="utf-8")
    staged = artifact_staging.stage_tree(source)
    output = import_sandbox_output(output_source,tmp_path/"sandbox-output")
    original_cleanup = workspace_lease.cleanup

    def cleanup(lease):
        if lease is output.lease:
            raise workspace_lease.WorkspaceCleanupError("retained output")
        return original_cleanup(lease)

    outcome = artifact_execution.ExecutionOutcome("pass", "sandbox passed", ("npm", "run", "build"), output)
    monkeypatch.setattr(artifact_execution, "run_generated", lambda *_args: outcome)
    monkeypatch.setattr(oracle.runtime_artifact_pipeline.workspace_lease, "cleanup", cleanup)
    receipts = []
    try:
        check = oracle._sandbox_check(staged, "npm-build", 5, receipts)
        assert check.status == "blocked"
        assert "cleanup" in check.detail
        assert receipts[0].component == "sandbox_output" and receipts[0].state == "retained"
    finally:
        original_cleanup(output.lease)
        original_cleanup(staged.lease)


def test_cleanup_error_after_removal_reports_removed_without_false_retention(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    original = workspace_lease.cleanup
    monkeypatch.setattr(oracle, "structural_checks", lambda *_args, **_kwargs: [oracle.pass_check("static", "ok")])
    monkeypatch.setattr(oracle, "runtime_checks", lambda *_args, **_kwargs: [])

    def remove_then_raise(lease):
        original(lease)
        raise workspace_lease.WorkspaceCleanupError("after removal")

    monkeypatch.setattr(oracle.runtime_artifact_pipeline.workspace_lease, "cleanup", remove_then_raise)
    result = oracle.validate_artifact("plugin", plugin_dir, args())

    receipt = result["artifact_retention"]["components"]["input_copy"]
    assert result["status"] == "pass" and result["execution_retained"] is False
    assert receipt["state"] == "removed" and receipt["error"].startswith("WorkspaceCleanupError")


def generated_host_tokens(tokens):
    joined=" ".join(tokens)
    npm="npm" in tokens and bool(tokens & {"install","ci","run","build","test"})
    composer="composer" in tokens and bool(tokens & {"install","update","exec"})
    phpunit="phpunit" in joined or "vendor/bin/phpunit" in joined
    return npm or composer or phpunit


def test_generic_host_detector_covers_composer_and_artifact_phpunit():
    assert generated_host_tokens({"composer","install"})
    assert generated_host_tokens({"composer","update"})
    assert generated_host_tokens({"composer","exec","phpunit"})
    assert generated_host_tokens({"php","vendor/bin/phpunit"})


def test_generated_execution_callsites_do_not_use_generic_host_runner():
    files = (
        "artifact_execution.py",
        "runtime_artifact_pipeline.py",
        "validate_wordpress_artifact.py",
        "run_wordpress_runtime_smoke.py",
    )
    generic = {"run_command", "run_command_with_input", "command_check", "subprocess.run", "subprocess.Popen"}
    violations = []
    for filename in files:
        tree = ast.parse((oracle.ROOT / "evals" / "harness" / filename).read_text())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            values = {}
            for _pass in range(3):
                for assignment in (node for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.AnnAssign))):
                    value = assignment.value
                    tokens = {item.value.lower() for item in ast.walk(value) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                    for name in (item.id for item in ast.walk(value) if isinstance(item, ast.Name)):
                        tokens.update(values.get(name, set()))
                    targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            values[target.id] = tokens
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                symbol = ast.unparse(call.func)
                if symbol not in generic:
                    continue
                tokens = {item.value.lower() for item in ast.walk(call) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                for name in (item.id for item in ast.walk(call) if isinstance(item, ast.Name)):
                    tokens.update(values.get(name, set()))
                generated = generated_host_tokens(tokens)
                current = call
                while current in parents and not isinstance(parents[current], ast.Assign):
                    current = parents[current]
                target = ast.unparse(parents[current].targets[0]) if current in parents and isinstance(parents[current], ast.Assign) else ""
                command_arg=ast.unparse(call.args[0]) if call.args else ""
                cwd_arg=ast.unparse(call.args[1]) if len(call.args)>1 else ""
                exact_wpcs="[composer, 'install', '--no-interaction', '--no-progress', '--quiet']"
                allowed_wpcs = filename=="run_wordpress_runtime_smoke.py" and target=="provisioning['composer_install']" and command_arg==exact_wpcs and cwd_arg=="temp_root"
                if generated and not allowed_wpcs:
                    violations.append((filename, call.lineno, symbol, sorted(tokens)))
    assert violations == []


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
    entrypoint = next(
        check for check in result["checks"] if check["id"] == "block_registration"
    )
    assert "registration is not statically proven" in entrypoint["detail"]


def write_block_contract(root, metadata, build="wp-scripts build"):
    root.mkdir()
    (root / "block.json").write_text(json.dumps(metadata), encoding="utf-8")
    if build is not None:
        (root / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"build": build},
                    "devDependencies": {"@wordpress/scripts": "latest"},
                }
            ),
            encoding="utf-8",
        )
    return root


def block_contract_statuses(path):
    return {
        check.id: check.status
        for check in oracle.structural_checks("block", path)
    }


def valid_block_metadata(**updates):
    metadata = {
        "apiVersion": 3,
        "name": "acme/card",
        "title": "Card",
        "category": "widgets",
    }
    return {**metadata, **updates}


def test_block_metadata_name_gate_requires_wordpress_namespace(tmp_path):
    block = write_block_contract(
        tmp_path / "invalid-name",
        valid_block_metadata(name="card"),
    )

    statuses = block_contract_statuses(block)

    assert statuses["block_metadata_name"] == "fail"
    assert statuses["block_metadata_types"] == "pass"
    assert statuses["block_metadata_api_version"] == "pass"
    assert statuses["unsafe_commands"] == "pass"
    assert statuses["hardcoded_secrets"] == "pass"


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ["Card"]),
        ("category", {"slug": "widgets"}),
        ("attributes", []),
        ("supports", []),
    ],
)
def test_block_metadata_types_gate_rejects_wrong_field_shapes(
    tmp_path, field, value
):
    block = write_block_contract(
        tmp_path / field,
        valid_block_metadata(**{field: value}),
    )

    statuses = block_contract_statuses(block)

    assert statuses["block_metadata_types"] == "fail"
    assert statuses["block_metadata_name"] == "pass"
    assert statuses["block_metadata_api_version"] == "pass"
    assert statuses["unsafe_commands"] == "pass"


@pytest.mark.parametrize("api_version", [True, 0, -1, 65_536, 3.0])
def test_block_metadata_api_version_gate_is_positive_and_bounded(
    tmp_path, api_version
):
    block = write_block_contract(
        tmp_path / f"api-{str(api_version).replace('.', '-')}",
        valid_block_metadata(apiVersion=api_version),
    )

    statuses = block_contract_statuses(block)

    assert statuses["block_metadata_api_version"] == "fail"
    assert statuses["block_metadata_name"] == "pass"
    assert statuses["block_metadata_types"] == "pass"
    assert statuses["unsafe_commands"] == "pass"


def test_block_metadata_file_gate_accepts_handles_and_local_file_arrays(tmp_path):
    block = write_block_contract(
        tmp_path / "valid-assets",
        valid_block_metadata(
            editorScript=["file:./index.js", "wp-element", "@wordpress/interactivity"],
            style=["wp-components", "file:./style.css"],
            render="file:./render.php",
        ),
    )
    (block / "index.js").write_text("export default {};", encoding="utf-8")
    (block / "style.css").write_text(".card {}", encoding="utf-8")
    (block / "render.php").write_text("<?php return '';", encoding="utf-8")

    statuses = block_contract_statuses(block)

    assert statuses["block_metadata_file_references"] == "pass"


@pytest.mark.parametrize(
    "handle",
    ["./missing.js", "../outside.js", "blocks/card/index.js", "https//cdn.example/x.js", "index.js"],
)
def test_block_metadata_file_gate_rejects_path_like_registered_handles(
    tmp_path, handle
):
    block = write_block_contract(
        tmp_path / "path-like-handle",
        valid_block_metadata(editorScript=handle),
    )

    result = oracle.validate_artifact("block", block, args())
    references = next(
        check for check in result["checks"]
        if check["id"] == "block_metadata_file_references"
    )

    assert references["status"] == "fail"
    assert result["status"] == "fail"


def test_block_metadata_count_limit_fails_before_json_parsing(monkeypatch):
    validator = oracle.block_metadata_validator
    monkeypatch.setattr(validator, "MAX_BLOCK_METADATA_FILES", 2)
    files = {
        f"blocks/card-{index}/block.json": b"not-json"
        for index in range(3)
    }

    checks = validator.validate_block_artifact(files)
    metadata = next(check for check in checks if check.id == "block_metadata")

    assert metadata.status == "fail"
    assert "count exceeds 2 files" in metadata.detail


def test_block_metadata_aggregate_limit_fails_before_json_parsing(monkeypatch):
    validator = oracle.block_metadata_validator
    monkeypatch.setattr(validator, "MAX_BLOCK_METADATA_TOTAL_BYTES", 10)
    files = {
        "blocks/one/block.json": b"not-json-one",
        "blocks/two/block.json": b"not-json-two",
    }

    checks = validator.validate_block_artifact(files)
    metadata = next(check for check in checks if check.id == "block_metadata")

    assert metadata.status == "fail"
    assert "aggregate limit" in metadata.detail


def test_block_metadata_deep_json_fails_across_shared_and_full_paths(tmp_path):
    block = tmp_path / "deep-json"
    block.mkdir()
    deep = (
        '{"apiVersion":3,"name":"acme/deep","title":"Deep",'
        '"category":"widgets","extra":'
        + "[" * 10_000
        + "0"
        + "]" * 10_000
        + "}"
    )
    (block / "block.json").write_text(deep, encoding="utf-8")
    (block / "package.json").write_text(
        '{"scripts":{"build":"wp-scripts build"},'
        '"devDependencies":{"@wordpress/scripts":"latest"}}',
        encoding="utf-8",
    )

    direct = oracle.check_block_contract(block)
    snapshot = artifact_staging.snapshot_regular_tree(block)
    view = oracle.artifact_snapshot_scan.from_snapshot(snapshot)
    captured = oracle.artifact_snapshot_scan.structural_checks("block", view)
    result = oracle.validate_artifact("block", block, args())

    assert next(check for check in direct if check.id == "block_metadata").status == "fail"
    assert next(check for check in captured if check.id == "block_metadata").status == "fail"
    assert result["status"] == "fail"


def test_block_metadata_rejects_escaped_lone_surrogate_across_full_path(tmp_path):
    block = write_block_contract(
        tmp_path / "surrogate",
        valid_block_metadata(editorScript="placeholder"),
    )
    metadata = (block / "block.json").read_text(encoding="utf-8")
    (block / "block.json").write_text(
        metadata.replace('"placeholder"', '"\\ud800"'), encoding="utf-8"
    )

    result = oracle.validate_artifact("block", block, args())
    block_metadata = next(
        check for check in result["checks"] if check["id"] == "block_metadata"
    )

    assert block_metadata["status"] == "fail"
    assert "Unicode scalar values" in block_metadata["detail"]
    assert result["status"] == "fail"


@pytest.mark.parametrize(
    "reference",
    ["file:./missing.js", "file:../../outside.js"],
)
def test_block_metadata_file_gate_rejects_missing_or_escaping_targets(
    tmp_path, reference
):
    (tmp_path / "outside.js").write_text("outside", encoding="utf-8")
    block = write_block_contract(
        tmp_path / "invalid-assets",
        valid_block_metadata(editorScript=["wp-element", reference]),
    )

    statuses = block_contract_statuses(block)

    assert statuses["block_metadata_file_references"] == "fail"
    assert statuses["block_metadata_name"] == "pass"
    assert statuses["unsafe_commands"] == "pass"


@pytest.mark.parametrize(
    "build",
    [
        "wp-scripts lint-js",
        "wp-scripts test-unit-js",
        "echo build complete",
        "wp-scripts build && echo complete",
        "wp-scripts build --help",
        "wp-scripts build -h",
        "wp-scripts build --version",
        "wp-scripts build -v",
        "wp-scripts build -V",
        "wp-scripts build --output-path=../../outside",
        "wp-scripts build\nid",
        "wp-scripts build\rwhoami",
        "wp-scripts build\t--help",
    ],
)
def test_block_registration_gate_rejects_non_build_package_scripts(
    tmp_path, build
):
    block = write_block_contract(
        tmp_path / f"fake-{build.split()[0].replace('/', '-')}",
        valid_block_metadata(),
        build=build,
    )

    statuses = block_contract_statuses(block)

    assert statuses["block_registration"] == "fail"
    assert statuses["block_metadata"] == "pass"
    assert statuses["unsafe_commands"] == "pass"
    result = oracle.validate_artifact("block", block, args())
    assert result["status"] == "fail"


@pytest.mark.parametrize(
    "build",
    [
        "wp-scripts build",
        "wp-scripts build blocks/card/index.js --output-path=blocks/card/build",
        "wp-scripts build --source-path=blocks/card --output-path=blocks/card/build",
        "wp-scripts build --experimental-modules",
        "wp-scripts build --webpack-copy-php",
        "wp-scripts build --webpack-no-externals",
        "wp-scripts build --blocks-manifest",
        "wp-scripts build --webpack-bundle-analyzer",
    ],
)
def test_block_registration_gate_accepts_pinned_wp_scripts_build_grammar(
    tmp_path, build
):
    block = write_block_contract(
        tmp_path / "admitted-build",
        valid_block_metadata(),
        build=build,
    )

    result = oracle.validate_artifact("block", block, args())

    assert result["status"] == "pass"


def test_block_registration_gate_accepts_concrete_php_registration(tmp_path):
    block = write_block_contract(
        tmp_path / "php-registration",
        valid_block_metadata(),
        build=None,
    )
    (block / "register.php").write_text(
        "<?php\nregister_block_type( __DIR__ );\n",
        encoding="utf-8",
    )

    legacy = oracle.check_block_registration(block)
    snapshot = artifact_staging.snapshot_regular_tree(block)
    view = oracle.artifact_snapshot_scan.from_snapshot(snapshot)
    observed = next(
        check
        for check in oracle.artifact_snapshot_scan.structural_checks("block", view)
        if check.id == "block_registration"
    )

    assert legacy.status == "pass"
    assert observed.status == "pass"


@pytest.mark.parametrize(
    "decoy",
    [
        "<?php\n$decoy = <<<'PHP'\nregister_block_type(\nPHP;\n",
        "<?php\n$decoy = <<<PHP\nregister_block_type(\nPHP;\n",
    ],
    ids=("nowdoc", "heredoc"),
)
def test_block_registration_rejects_heredoc_decoys_across_all_paths(
    tmp_path, decoy
):
    block = write_block_contract(
        tmp_path / "php-registration-decoy",
        valid_block_metadata(),
        build=None,
    )
    (block / "decoy.php").write_text(decoy, encoding="utf-8")

    legacy = oracle.check_block_registration(block)
    snapshot = artifact_staging.snapshot_regular_tree(block)
    view = oracle.artifact_snapshot_scan.from_snapshot(snapshot)
    observed = next(
        check
        for check in oracle.artifact_snapshot_scan.structural_checks("block", view)
        if check.id == "block_registration"
    )
    result = oracle.validate_artifact("block", block, args())
    full = next(
        check for check in result["checks"] if check["id"] == "block_registration"
    )

    assert legacy.status == "fail"
    assert observed.status == "fail"
    assert full["status"] == "fail"
    assert result["status"] == "fail"


@pytest.mark.parametrize(
    "decoy",
    [
        "<?php\nnamespace Acme; function register_block_type( $path ) {} register_block_type( __DIR__ );\n",
        "<?php\nnamespace Acme; use function Vendor\\fake as register_block_type; register_block_type( __DIR__ );\n",
        "<?php // ?>\nregister_block_type( __DIR__ );\n",
        "<?php\n$callback = register_block_type(...);\n",
        "<?php\nclass register_block_type {} new register_block_type();\n",
        "<?php\nfunction &register_block_type( $path ) {}\n",
        "<?php\n$object->register_block_type( __DIR__ );\n",
        "<?php\nThing::register_block_type( __DIR__ );\n",
        "<?php\n$register_block_type( __DIR__ );\n",
    ],
    ids=(
        "namespace-shadow",
        "function-alias",
        "comment-close-tag",
        "first-class-callable",
        "class-construction",
        "by-reference-declaration",
        "method-call",
        "static-method-call",
        "variable-function",
    ),
)
def test_block_registration_rejects_non_core_call_shapes_full_oracle(
    tmp_path, decoy
):
    block = write_block_contract(
        tmp_path / "non-core-call",
        valid_block_metadata(),
        build=None,
    )
    (block / "decoy.php").write_text(decoy, encoding="utf-8")

    result = oracle.validate_artifact("block", block, args())
    registration = next(
        check for check in result["checks"] if check["id"] == "block_registration"
    )

    assert registration["status"] == "fail"
    assert result["status"] == "fail"


def test_block_registration_accepts_explicit_global_call_in_namespace(tmp_path):
    block = write_block_contract(
        tmp_path / "qualified-core-call",
        valid_block_metadata(),
        build=None,
    )
    (block / "register.php").write_text(
        "<?php\nnamespace Acme; \\register_block_type( __DIR__ );\n",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("block", block, args())

    assert result["status"] == "pass"


def test_block_registration_scan_rejects_oversized_php_before_tokenization(tmp_path):
    block = write_block_contract(
        tmp_path / "oversized-registration",
        valid_block_metadata(),
        build=None,
    )
    (block / "oversized.php").write_bytes(
        b"<?php\n" + b"a " * (512 * 1024)
    )

    check = oracle.check_block_registration(block)

    assert check.status == "fail"
    assert "exceeds the 1 MiB PHP registration scan limit" in check.detail


def test_block_registration_rejects_cross_file_global_shadow(tmp_path):
    block = write_block_contract(
        tmp_path / "cross-file-shadow",
        valid_block_metadata(),
        build=None,
    )
    (block / "a-shadow.php").write_text(
        "<?php\nfunction register_block_type( $path ) { return false; }\n",
        encoding="utf-8",
    )
    (block / "b-call.php").write_text(
        "<?php\nregister_block_type( __DIR__ );\n",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("block", block, args())
    registration = next(
        check for check in result["checks"] if check["id"] == "block_registration"
    )

    assert registration["status"] == "fail"
    assert "global register_block_type() shadow" in registration["detail"]
    assert result["status"] == "fail"


def test_explicit_global_registration_survives_unrelated_namespaced_shadow(tmp_path):
    block = write_block_contract(
        tmp_path / "qualified-with-namespaced-shadow",
        valid_block_metadata(),
        build=None,
    )
    (block / "a-shadow.php").write_text(
        "<?php\nnamespace Acme; function register_block_type( $path ) { return false; }\n",
        encoding="utf-8",
    )
    (block / "b-call.php").write_text(
        "<?php\nnamespace Other; \\register_block_type( __DIR__ );\n",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("block", block, args())

    assert result["status"] == "pass"


def test_block_registration_ignores_data_after_halt_compiler(tmp_path):
    block = write_block_contract(
        tmp_path / "halted-compiler-data",
        valid_block_metadata(),
        build=None,
    )
    (block / "halt.php").write_text(
        "<?php\n__halt_compiler(); register_block_type( __DIR__ );\n",
        encoding="utf-8",
    )

    result = oracle.validate_artifact("block", block, args())
    registration = next(
        check for check in result["checks"] if check["id"] == "block_registration"
    )

    assert registration["status"] == "fail"
    assert result["status"] == "fail"


def test_block_metadata_rejects_duplicate_names_across_all_paths(tmp_path):
    block = write_block_contract(
        tmp_path / "duplicate-names",
        valid_block_metadata(),
    )
    duplicate = block / "nested"
    duplicate.mkdir()
    (duplicate / "block.json").write_text(
        json.dumps(valid_block_metadata()), encoding="utf-8"
    )

    direct = {
        check.id: (check.status, check.detail)
        for check in oracle.check_block_contract(block)
    }
    snapshot = artifact_staging.snapshot_regular_tree(block)
    view = oracle.artifact_snapshot_scan.from_snapshot(snapshot)
    captured = {
        check.id: (check.status, check.detail)
        for check in oracle.artifact_snapshot_scan.structural_checks("block", view)
        if check.id.startswith("block_")
    }
    result = oracle.validate_artifact("block", block, args())

    assert direct == captured
    assert direct["block_metadata_name"][0] == "fail"
    assert "duplicates block name acme/card" in direct["block_metadata_name"][1]
    assert result["status"] == "fail"


def test_block_contract_paths_share_exact_gate_results(tmp_path):
    block = write_block_contract(
        tmp_path / "shared-validator",
        valid_block_metadata(
            editorScript=["wp-element", "file:./missing.js"]
        ),
        build="echo not-a-build",
    )
    direct = {
        check.id: (check.status, check.detail)
        for check in oracle.check_block_contract(block)
    }
    snapshot = artifact_staging.snapshot_regular_tree(block)
    view = oracle.artifact_snapshot_scan.from_snapshot(snapshot)
    captured = {
        check.id: (check.status, check.detail)
        for check in oracle.artifact_snapshot_scan.structural_checks("block", view)
        if check.id.startswith("block_")
    }

    assert direct == captured
    assert direct["block_metadata_file_references"][0] == "fail"
    assert direct["block_registration"][0] == "fail"


def test_block_npm_build_without_approved_lock_blocks_without_host_command(tmp_path, monkeypatch):
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
    monkeypatch.setattr(oracle, "run_command", lambda *_args:(_ for _ in ()).throw(AssertionError("generated npm reached host runner")))

    result = oracle.validate_artifact("block", block_dir, args(require_tool=["npm-build"]))
    npm_check = next(check for check in result["checks"] if check["id"] == "npm_build")

    assert result["status"] == "blocked"
    assert npm_check["status"] == "blocked"
    assert "exact approved manifest and lock profile" in npm_check["detail"]


def test_required_blocked_phase_dominates_structural_failure(tmp_path):
    block_dir = tmp_path / "incomplete-block"
    block_dir.mkdir()
    (block_dir / "block.json").write_text('{"name":"acme/incomplete"}', encoding="utf-8")
    (block_dir / "package.json").write_text('{"scripts":{"build":"wp-scripts build"}}', encoding="utf-8")

    result = oracle.validate_artifact("block", block_dir, args(require_tool=["npm-build"]))

    assert any(check["status"] == "fail" for check in result["checks"])
    assert next(check for check in result["checks"] if check["id"] == "npm_build")["status"] == "blocked"
    assert result["status"] == "blocked"
    assert result["sandbox_posture"]["generated_execution"] == "blocked"


def test_snapshot_block_registration_rejects_nested_package_scripts_like_legacy(tmp_path):
    block=tmp_path/"block"; nested=block/"nested"; nested.mkdir(parents=True)
    (block/"block.json").write_text('{"name":"acme/card","title":"Card","category":"widgets"}')
    (nested/"package.json").write_text('{"scripts":{"build":"echo nested"}}')
    snapshot=artifact_staging.snapshot_regular_tree(block)
    view=oracle.artifact_snapshot_scan.from_snapshot(snapshot)
    legacy=oracle.check_block_registration(block)
    observed=next(check for check in oracle.artifact_snapshot_scan.structural_checks("block",view) if check.id=="block_registration")
    assert legacy.status=="fail" and observed.status=="fail"


def test_caller_claim_does_not_become_attested_staged_provenance(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    source = write_good_plugin(real)
    staged = artifact_staging.stage_tree(source, tmp_path / "leases")
    forged = tmp_path / "forged" / "plugin"
    monkeypatch.setattr(oracle, "structural_checks", lambda *_args, **_kwargs: [oracle.pass_check("static", "ok")])
    monkeypatch.setattr(oracle, "runtime_checks", lambda *_args, **_kwargs: [])
    try:
        result = oracle.validate_staged_artifact("plugin", staged, args(), source_path=forged)
        assert result["source_attested"] is True
        assert result["source_path"] == str(source.resolve())
        assert result["claimed_source_path"] == str(forged.absolute())
    finally:
        workspace_lease.cleanup(staged.lease)


def test_structural_scanner_cannot_read_replacement_during_staged_root_aba(tmp_path, monkeypatch):
    source = write_good_plugin(tmp_path)
    staged = artifact_staging.stage_tree(source, tmp_path / "leases")
    moved = staged.lease.root / "held-original"
    observed = []

    def swapping_structural(_artifact_type, supplied, timeout_sec=120, extras=None):
        staged.root.rename(moved)
        staged.root.mkdir()
        (staged.root / "evil.php").write_text("EVIL-REPLACEMENT", encoding="utf-8")
        try:
            if isinstance(supplied, Path):
                observed.append((supplied / "evil.php").read_text(encoding="utf-8"))
            else:
                observed.extend(entry.content.decode(errors="replace") for entry in supplied.entries)
        finally:
            (staged.root / "evil.php").unlink()
            staged.root.rmdir()
            moved.rename(staged.root)
        return [oracle.pass_check("scanner", "scan completed")]

    monkeypatch.setattr(oracle, "structural_checks", swapping_structural)
    monkeypatch.setattr(oracle, "trusted_external_checks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(oracle, "runtime_checks", lambda *_args, **_kwargs: [])
    try:
        result = oracle.validate_staged_artifact("plugin", staged, args())
        assert result["status"] == "pass"
        assert "EVIL-REPLACEMENT" not in observed
    finally:
        workspace_lease.cleanup(staged.lease)


def test_trusted_scan_handoff_cleanup_failure_is_reported_and_blocks(tmp_path, monkeypatch):
    source = write_good_plugin(tmp_path)
    staged = artifact_staging.stage_tree(source, tmp_path / "leases")
    original = workspace_lease.cleanup
    retained_scan = None

    def refuse_scan_handoff(lease):
        if lease is not staged.lease:
            raise workspace_lease.WorkspaceCleanupError("retained scan handoff")
        return original(lease)

    monkeypatch.setattr(oracle.runtime_artifact_pipeline.workspace_lease, "cleanup", refuse_scan_handoff)
    try:
        result = oracle.validate_staged_artifact("plugin", staged, args())
        retained_scan = next(lease for lease in workspace_lease._LIVE_LEASES.values() if lease is not staged.lease and lease.purpose is workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION)
        assert result["status"] == "blocked" and result["scan_handoff"]["state"] == "retained"
        assert result["scan_handoff"]["generated_execution"] is False
        assert "lease_id" not in json.dumps(result) and ".workspace-lease" not in json.dumps(result)
    finally:
        monkeypatch.setattr(oracle.runtime_artifact_pipeline.workspace_lease, "cleanup", original)
        if retained_scan is not None: original(retained_scan)
        original(staged.lease)


def test_trusted_scan_handoff_is_cleaned_and_reported_when_scanner_raises(tmp_path, monkeypatch):
    source = write_good_plugin(tmp_path)
    staged = artifact_staging.stage_tree(source, tmp_path / "leases")
    monkeypatch.setattr(
        oracle,
        "structural_checks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scanner exploded")),
    )
    try:
        result = oracle.validate_staged_artifact("plugin", staged, args())
        assert result["status"] == "blocked"
        assert result["scan_handoff"]["state"] == "removed"
        assert result["scan_handoff"]["retained"] is False
        assert next(item for item in result["checks"] if item["id"] == "trusted_scanner_handoff")["status"] == "blocked"
    finally:
        workspace_lease.cleanup(staged.lease)


def test_staged_plugin_check_cannot_execute_in_trusted_scan_handoff(tmp_path):
    source = write_good_plugin(tmp_path)
    result = oracle.validate_artifact("plugin", source, args(require_tool=["plugin-check"]))
    check = next(item for item in result["checks"] if item["id"] == "plugin_check")
    assert result["status"] == "blocked" and check["status"] == "blocked"
    assert "forbidden in the trusted scanner handoff" in check["detail"]


def test_unattested_stage_reports_source_only_as_caller_claim(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "plugin.php").write_text("<?php\n", encoding="utf-8")
    original = artifact_staging.stage_tree(source, tmp_path / "original")
    clone = None
    with artifact_staging.hold_staged_tree(original) as held:
        clone = artifact_staging.stage_held_tree(held, tmp_path / "clone")
    monkeypatch.setattr(oracle, "structural_checks", lambda *_args, **_kwargs: [oracle.pass_check("static", "ok")])
    monkeypatch.setattr(oracle, "runtime_checks", lambda *_args, **_kwargs: [])
    try:
        claimed = tmp_path / "claimed-source"
        result = oracle.validate_staged_artifact("plugin", clone, args(), source_path=claimed)
        assert result["source_attested"] is False and result["source_path"] is None
        assert result["claimed_source_path"] == str(claimed.absolute())
    finally:
        workspace_lease.cleanup(clone.lease)
        workspace_lease.cleanup(original.lease)


def test_block_npm_custom_entry_still_requires_approved_lock(tmp_path, monkeypatch):
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
    monkeypatch.setattr(oracle, "run_command", lambda *_args:(_ for _ in ()).throw(AssertionError("generated npm reached host runner")))

    result = oracle.validate_artifact("block", block_dir, args(require_tool=["npm-build"]))
    npm_check = next(check for check in result["checks"] if check["id"] == "npm_build")

    assert result["status"] == "blocked"
    assert npm_check["status"] == "blocked"


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

    assert result["status"] == "blocked"
    assert next(check for check in result["checks"] if check["id"] == "plugin_check")["status"] == "blocked"
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

    assert result["status"] == "blocked"
    assert next(check for check in result["checks"] if check["id"] == "plugin_check")["status"] == "blocked"


def test_phpunit_caller_vendor_tree_is_not_executed_on_host(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    (plugin_dir / "phpunit.xml").write_text("<phpunit />\n", encoding="utf-8")
    phpunit = plugin_dir / "vendor" / "bin" / "phpunit"
    phpunit.parent.mkdir(parents=True)
    phpunit.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(oracle, "run_command", lambda *_args:(_ for _ in ()).throw(AssertionError("generated PHPUnit reached host runner")))

    result = oracle.validate_artifact("plugin", plugin_dir, args(require_tool=["phpunit"]))

    assert result["status"] == "blocked"
    assert any("dependency root" in check["detail"] for check in result["checks"])


def test_phpunit_required_tool_blocks_when_suite_exists_but_phpunit_missing(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    (plugin_dir / "phpunit.xml").write_text("<phpunit />\n", encoding="utf-8")

    monkeypatch.setattr(oracle.shutil, "which", lambda _name: None)

    result = oracle.validate_artifact("plugin", plugin_dir, args(require_tool=["phpunit"]))
    phpunit_check = next(check for check in result["checks"] if check["id"] == "phpunit")

    assert result["status"] == "blocked"
    assert phpunit_check["status"] == "blocked"
    assert "exact approved manifest and lock profile" in phpunit_check["detail"]


def test_plugin_check_fails_when_wp_cli_reports_error_rows(tmp_path, monkeypatch):
    plugin_dir = write_good_plugin(tmp_path)
    monkeypatch.setattr(oracle.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "wp" else None)

    def fake_run(_command, _cwd, _timeout):
        return oracle.CommandResult(0, "line\tcolumn\ttype\tcode\tmessage\n0\t0\tERROR\tmissing_readme\tNo readme\n", "")

    monkeypatch.setattr(oracle, "run_command", fake_run)

    result = oracle.check_plugin_check(plugin_dir, args(require_tool=["plugin-check"]), True)

    assert result.status == "fail" and result.id == "plugin_check"


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

    result = oracle.check_plugin_check(plugin_dir, test_args, True)

    assert result.status == "pass"
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
