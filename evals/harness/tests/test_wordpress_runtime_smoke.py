"""Tests for the disposable WordPress runtime smoke harness."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import certify_wordpress_executor_artifact as certifier
import run_wordpress_runtime_smoke as smoke

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def write_interactive_block_artifact(source: Path, *, view_script_module: str = "file:./view.js") -> Path:
    block_dir = source / "blocks" / "interactive-counter"
    block_dir.mkdir(parents=True)
    (source / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "build": "wp-scripts build --source-path=blocks/interactive-counter --output-path=blocks/interactive-counter/build --experimental-modules",
                    "start": "wp-scripts start --source-path=blocks/interactive-counter --output-path=blocks/interactive-counter/build --experimental-modules",
                },
                "dependencies": {"@wordpress/interactivity": "^6.48.1"},
                "devDependencies": {"@wordpress/scripts": "^32.4.1"},
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "apiVersion": 3,
                "name": "acme/interactive-counter",
                "title": "Interactive Counter",
                "category": "widgets",
                "textdomain": "acme-interactive-counter",
                "editorScript": "file:./index.js",
                "viewScriptModule": view_script_module,
                "render": "file:./render.php",
                "supports": {"interactivity": True},
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "index.js").write_text(
        "window.wp.blocks.registerBlockType( 'acme/interactive-counter', { edit() { return 'Interactive counter'; }, save() { return null; } } );\n",
        encoding="utf-8",
    )
    (block_dir / "view.js").write_text(
        """import { store, getContext } from '@wordpress/interactivity';

store( 'acmeInteractiveCounter', {
    actions: {
        increment() {
            const context = getContext();
            context.count += 1;
        },
    },
} );
""",
        encoding="utf-8",
    )
    (block_dir / "render.php").write_text(
        """<?php
?>
<div data-wp-interactive="acmeInteractiveCounter" data-wp-context='{ "count": 0 }'>
    <span data-wp-text="context.count">0</span>
    <button type="button" data-wp-on--click="actions.increment">Increment</button>
</div>
""",
        encoding="utf-8",
    )
    return source


def write_deprecated_block_artifact(source: Path, *, include_fixture: bool = True) -> Path:
    block_dir = source / "blocks" / "deprecated-card"
    fixture_dir = source / "fixtures"
    block_dir.mkdir(parents=True)
    fixture_dir.mkdir(parents=True)
    (source / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "build": "wp-scripts build --source-path=blocks/deprecated-card --output-path=blocks/deprecated-card/build",
                    "start": "wp-scripts start --source-path=blocks/deprecated-card --output-path=blocks/deprecated-card/build",
                },
                "devDependencies": {"@wordpress/scripts": "^32.4.1"},
            }
        ),
        encoding="utf-8",
    )
    (source / "deprecation-smoke.json").write_text(
        json.dumps(
            {
                "oldContentFile": "fixtures/deprecated-v1.html",
                "expectedMigratedText": "Runtime block smoke: Legacy runtime smoke",
                "expectedMigratedAttributeName": "content",
                "expectedMigratedAttribute": "Legacy runtime smoke",
                "expectedSerializedMarker": "<strong>Runtime block smoke:</strong>",
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "apiVersion": 3,
                "name": "acme/deprecated-card",
                "title": "Deprecated Card",
                "category": "widgets",
                "textdomain": "acme-deprecated-card",
                "editorScript": "file:./index.js",
                "attributes": {
                    "content": {"type": "string", "source": "html", "selector": "span"},
                },
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "index.js").write_text(
        """import { registerBlockType } from '@wordpress/blocks';
import { useBlockProps } from '@wordpress/block-editor';
import { createElement } from '@wordpress/element';

registerBlockType( 'acme/deprecated-card', {
    attributes: {
        content: { type: 'string', source: 'html', selector: 'span' },
    },
    edit() {
        return createElement( 'p', useBlockProps(), 'Runtime block smoke: Legacy runtime smoke' );
    },
    save( { attributes } ) {
        return createElement( 'div', useBlockProps.save(), [
            createElement( 'strong', { key: 'label' }, 'Runtime block smoke:' ),
            ' ',
            createElement( 'span', { key: 'content' }, attributes.content ),
        ] );
    },
    deprecated: [
        {
            attributes: {
                text: { type: 'string', source: 'html', selector: 'p' },
            },
            migrate( { text } ) {
                return { content: text };
            },
            save( { attributes } ) {
                return createElement( 'p', useBlockProps.save(), attributes.text );
            },
        },
    ],
} );
""",
        encoding="utf-8",
    )
    if include_fixture:
        (fixture_dir / "deprecated-v1.html").write_text(
            '<!-- wp:acme/deprecated-card {"text":"Legacy runtime smoke"} -->\n'
            '<p class="wp-block-acme-deprecated-card">Legacy runtime smoke</p>\n'
            "<!-- /wp:acme/deprecated-card -->\n",
            encoding="utf-8",
        )
    return source


def write_mcp_public_ability_artifact(source: Path) -> Path:
    plugin_dir = source / "acme-mcp-smoke"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "acme-mcp-smoke.php").write_text(
        """<?php
/**
 * Plugin Name: Acme MCP Smoke
 * Requires at least: 7.0
 *
 * @package AcmeMcpSmoke
 */

if ( ! defined( 'ABSPATH' ) ) {
\texit;
}

add_action( 'wp_abilities_api_init', 'acme_mcp_smoke_register_ability' );

function acme_mcp_smoke_register_ability(): void {
\twp_register_ability(
\t\t'acme-mcp-smoke/get-runtime-marker',
\t\tarray(
\t\t\t'label' => 'Get runtime marker',
\t\t\t'description' => 'Returns a marker for MCP Adapter smoke tests.',
\t\t\t'category' => 'site',
\t\t\t'input_schema' => array( 'type' => 'object' ),
\t\t\t'output_schema' => array( 'type' => 'object' ),
\t\t\t'permission_callback' => '__return_true',
\t\t\t'execute_callback' => 'acme_mcp_smoke_execute',
\t\t\t'meta' => array(
\t\t\t\t'mcp' => array(
\t\t\t\t\t'public' => true,
\t\t\t\t),
\t\t\t),
\t\t)
\t);
}

function acme_mcp_smoke_execute( array $input ): array {
\treturn array( 'marker' => (string) ( $input['marker'] ?? 'Runtime MCP smoke' ) );
}
""",
        encoding="utf-8",
    )
    return plugin_dir


def write_ai_client_provider_artifact(source: Path) -> Path:
    plugin_dir = source / "acme-ai-client-smoke"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "acme-ai-client-smoke.php").write_text(
        """<?php
/**
 * Plugin Name: Acme AI Client Smoke
 * Requires at least: 7.0
 *
 * @package AcmeAIClientSmoke
 */

namespace AcmeAIClientSmoke;

use WordPress\\AiClient\\AiClient;
use WordPress\\AiClient\\ModelMetadataDirectoryInterface;
use WordPress\\AiClient\\ModelInterface;
use WordPress\\AiClient\\OptionEnum;
use WordPress\\AiClient\\ModalityEnum;
use WordPress\\AiClient\\ProviderAvailabilityInterface;
use WordPress\\AiClient\\ProviderInterface;
use WordPress\\AiClient\\ProviderMetadata;
use WordPress\\AiClient\\ProviderTypeEnum;
use WordPress\\AiClient\\TextGenerationModelInterface;

const PROVIDER_ID = 'acme-ai-client-smoke';
const MODEL_ID    = 'acme-deterministic-text';

add_action( 'init', __NAMESPACE__ . '\\register_provider', 5 );

function register_provider(): void {
\tif ( ! class_exists( AiClient::class ) ) {
\t\treturn;
\t}

\tAiClient::defaultRegistry()->registerProvider( new DeterministicProvider() );
}

function generate_summary( string $prompt ) {
\tif ( ! current_user_can( 'edit_posts' ) ) {
\t\treturn new \\WP_Error( 'acme_ai_client_forbidden', 'Current user cannot run the AI Client smoke.' );
\t}

\t$response = wp_ai_client_prompt( $prompt )
\t\t->using_model_preference( array( PROVIDER_ID, MODEL_ID ) )
\t\t->generate_text();

\tif ( is_wp_error( $response ) ) {
\t\treturn $response;
\t}

\treturn esc_html( $response );
}

final class DeterministicProvider implements ProviderInterface, ModelMetadataDirectoryInterface, ProviderAvailabilityInterface {
\tpublic function getMetadata(): ProviderMetadata {
\t\treturn new ProviderMetadata(
\t\t\tarray(
\t\t\t\t'id'   => PROVIDER_ID,
\t\t\t\t'name' => 'Acme AI Client Smoke',
\t\t\t\t'type' => ProviderTypeEnum::server(),
\t\t\t)
\t\t);
\t}

\tpublic function listModels(): array {
\t\treturn array( new DeterministicTextModel() );
\t}

\tpublic function isConfigured(): bool {
\t\treturn true;
\t}
}

final class DeterministicTextModel implements ModelInterface, TextGenerationModelInterface {
\tpublic function getId(): string {
\t\treturn MODEL_ID;
\t}

\tpublic function generateTextResult( array $request ) {
\t\treturn 'AI Client smoke: deterministic provider response';
\t}

\tpublic function getSupportedOptions(): array {
\t\treturn array(
\t\t\tOptionEnum::inputModalities()->value  => array( array( ModalityEnum::text() ) ),
\t\t\tOptionEnum::outputModalities()->value => array( array( ModalityEnum::text() ) ),
\t\t);
\t}
}
""",
        encoding="utf-8",
    )
    return plugin_dir


def test_write_runtime_fixture_creates_wp_env_project(tmp_path):
    plugin_dir = smoke.write_runtime_fixture(tmp_path)

    config = json.loads((tmp_path / ".wp-env.json").read_text(encoding="utf-8"))
    plugin_text = (plugin_dir / "acme-runtime-smoke.php").read_text(encoding="utf-8")

    assert config["plugins"] == ["./acme-runtime-smoke"]
    assert config["autoPort"] is True
    assert config["testsEnvironment"] is False
    assert "Plugin Name: Acme Runtime Smoke" in plugin_text
    assert "License: GPL-2.0-or-later" in plugin_text
    assert "ABSPATH" in plugin_text
    assert "sanitize_key" in plugin_text
    assert (plugin_dir / "readme.txt").exists()


def test_create_wp_env_temp_root_uses_docker_safe_basename(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(tmp_path))

    temp_root = smoke.create_wp_env_temp_root()

    try:
        assert temp_root.exists()
        assert re.fullmatch(r"wp-meta-skills-runtime-[a-f0-9]{12}", temp_root.name)
        assert "_" not in temp_root.name
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_write_block_runtime_fixture_creates_registered_block_plugin(tmp_path):
    plugin_dir = smoke.write_block_runtime_fixture(tmp_path)

    config = json.loads((tmp_path / ".wp-env.json").read_text(encoding="utf-8"))
    plugin_text = (plugin_dir / "acme-block-runtime-smoke.php").read_text(encoding="utf-8")
    block_json = json.loads((plugin_dir / "blocks" / "runtime-card" / "block.json").read_text(encoding="utf-8"))

    assert config["plugins"] == ["./acme-block-runtime-smoke"]
    assert "Plugin Name: Acme Block Runtime Smoke" in plugin_text
    assert "register_block_type" in plugin_text
    assert block_json["name"] == "acme/runtime-card"
    assert block_json["editorScript"] == "file:./index.js"
    assert block_json["render"] == "file:./render.php"
    assert "registerBlockType" in (plugin_dir / "blocks" / "runtime-card" / "index.js").read_text(encoding="utf-8")
    assert "wp-blocks" in (plugin_dir / "blocks" / "runtime-card" / "index.asset.php").read_text(encoding="utf-8")


def test_copy_plugin_artifact_creates_wp_env_project(tmp_path):
    source = tmp_path / "generated" / "acme-generated"
    source.mkdir(parents=True)
    (source / "acme-generated.php").write_text("<?php\n/**\n * Plugin Name: Acme Generated\n */\n", encoding="utf-8")

    plugin_dir = smoke.copy_plugin_artifact(source, tmp_path / "runtime")
    config = json.loads((tmp_path / "runtime" / ".wp-env.json").read_text(encoding="utf-8"))

    assert plugin_dir.name == "acme-generated"
    assert config["plugins"] == ["./acme-generated"]
    assert (plugin_dir / "acme-generated.php").exists()


def test_copy_block_artifact_as_plugin_wraps_generated_block_files(tmp_path):
    source = tmp_path / "generated-block"
    block_dir = source / "blocks" / "runtime-card"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "apiVersion": 3,
                "name": "acme/runtime-card",
                "title": "Runtime Card",
                "category": "widgets",
                "textdomain": "acme-runtime-card",
                "editorScript": "file:./index.js",
                "render": "file:./render.php",
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "index.js").write_text("window.wp.blocks.registerBlockType( 'acme/runtime-card', {} );\n", encoding="utf-8")
    (block_dir / "index.asset.php").write_text("<?php\nreturn array( 'dependencies' => array() );\n", encoding="utf-8")
    (block_dir / "render.php").write_text("<?php echo esc_html__( 'Runtime block smoke', 'acme' );\n", encoding="utf-8")

    wrapped = smoke.copy_block_artifact_as_plugin(source, tmp_path / "runtime")
    config = json.loads((tmp_path / "runtime" / ".wp-env.json").read_text(encoding="utf-8"))
    plugin_text = (wrapped.plugin_dir / f"{wrapped.plugin_dir.name}.php").read_text(encoding="utf-8")

    assert wrapped.block_name == "acme/runtime-card"
    assert wrapped.textdomain == "acme-runtime-card"
    assert wrapped.source_block_dir == block_dir.resolve()
    assert wrapped.copied_block_dir == wrapped.plugin_dir / "generated" / "blocks" / "runtime-card"
    assert config["plugins"] == [f"./{wrapped.plugin_dir.name}"]
    assert "Plugin Name: Generated Block Runtime Wrapper" in plugin_text
    assert "Text Domain: acme-runtime-card" in plugin_text
    assert "register_block_type" in plugin_text
    assert "__DIR__ . '/generated/blocks/runtime-card'" in plugin_text
    assert "Generated Block Runtime Wrapper" in (wrapped.plugin_dir / "readme.txt").read_text(encoding="utf-8")
    assert (wrapped.copied_block_dir / "block.json").exists()
    assert (wrapped.copied_block_dir / "render.php").exists()


def test_runtime_smoke_passes_narrow_gate_and_records_full_profile(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        if args.profile == "runtime":
            return {"status": "blocked", "pass": False, "checks": []}
        return {"status": "pass", "pass": True, "checks": [], "runtime_roots": {"wp_env_root": args.wp_env_root}}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "fixture", keep_artifacts=True)

    assert result["status"] == "pass"
    runtime_root = Path(result["runtime_root"])
    assert runtime_root.parent == (tmp_path / "fixture").resolve()
    assert result["workdir_parent"] == str((tmp_path / "fixture").resolve())
    assert result["narrow_gate"]["runtime_roots"]["wp_env_root"] == str(runtime_root)
    assert result["full_plugin_runtime_profile"]["status"] == "blocked"
    assert "not WPCS proof" in result["negative_space"]
    assert commands[0][0][:3] == ["/usr/bin/npx", "--yes", "@wordpress/env"]
    assert commands[0][0][-2:] == ["start", "--auto-port"]
    assert commands[1][0][-3:] == ["plugin", "activate", "acme-runtime-smoke"]
    assert commands[-1][0][-1] == "stop"


def test_runtime_smoke_deletes_only_leased_child(tmp_path, monkeypatch):
    parent = tmp_path / "caller"
    parent.mkdir()
    marker = parent / "caller-owned.txt"
    sibling = tmp_path / "wp-meta-skills-runtime-lookalike"
    marker.write_text("keep", encoding="utf-8")
    sibling.mkdir()
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: None)

    result = smoke.run_smoke(timeout_sec=5, workdir=parent)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert sibling.is_dir()
    assert not Path(result["runtime_root"]).exists()
    assert result["workdir_parent"] == str(parent.resolve())


def test_runtime_smoke_blocks_and_retains_child_when_cleanup_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        smoke,
        "cleanup_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(smoke.WorkspaceCleanupError("ownership mismatch")),
    )

    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "caller")

    assert result["status"] == "blocked"
    assert result["pass"] is False
    assert result["cleanup_error"] == "ownership mismatch"
    assert Path(result["runtime_root"]).is_dir()


def test_runtime_smoke_blocks_on_non_utf8_lease_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: None)
    original_write = smoke.write_runtime_fixture

    def corrupt_sentinel(root):
        plugin_dir = original_write(root)
        (root / ".workspace-lease").write_bytes(b"\xff\xfe")
        return plugin_dir

    monkeypatch.setattr(smoke, "write_runtime_fixture", corrupt_sentinel)
    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "caller")

    assert result["status"] == "blocked"
    assert result["fixture_retained"] is True
    assert "cleanup validation failed" in result["cleanup_error"]
    assert Path(result["runtime_root"]).is_dir()


def test_write_result_uses_exact_custom_root_and_identity(tmp_path):
    summary = {"status": "pass", "fixture_retained": False, "negative_space": [],
               "run_id": "exact-run", "evidence_id": "fresh", "input_artifact_digest": "a" * 64}
    out = smoke.write_result(summary, "exact-run", tmp_path)
    data = json.loads((out / "runtime-smoke.json").read_text(encoding="utf-8"))
    assert out == tmp_path.resolve() / "exact-run"
    assert data["evidence_id"] == "fresh"
    assert not (out / ".runtime-smoke.json.tmp").exists()


def test_write_result_refuses_existing_run(tmp_path):
    summary = {"status": "pass", "fixture_retained": False, "negative_space": []}
    smoke.write_result(summary, "same-run", tmp_path)
    with pytest.raises(FileExistsError):
        smoke.write_result(summary, "same-run", tmp_path)


def test_write_result_rejects_symlinked_results_parent(tmp_path):
    real = tmp_path / "real"; real.mkdir()
    linked = tmp_path / "linked"; linked.symlink_to(real, target_is_directory=True)
    summary = {"status": "pass", "fixture_retained": False, "negative_space": []}
    with pytest.raises(ValueError, match="symlink component"):
        smoke.write_result(summary, "run", linked)
    assert list(real.iterdir()) == []


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", "/absolute", "x" * 129])
def test_write_result_rejects_unsafe_run_id_before_write(tmp_path, run_id):
    summary = {"status": "pass", "fixture_retained": False, "negative_space": []}
    with pytest.raises(ValueError):
        smoke.write_result(summary, run_id, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_setup_failure_cleans_child_and_preserves_parent_and_siblings(tmp_path, monkeypatch):
    parent = tmp_path / "caller"
    parent.mkdir()
    marker = parent / "owned.txt"
    sibling = parent / "unrelated"
    marker.write_text("keep", encoding="utf-8")
    sibling.mkdir()

    def fail_setup(_root):
        raise ValueError("fixture setup failed")

    monkeypatch.setattr(smoke, "write_runtime_fixture", fail_setup)
    with pytest.raises(ValueError, match="fixture setup failed"):
        smoke.run_smoke(timeout_sec=5, workdir=parent)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert sibling.is_dir()
    assert sorted(path.name for path in parent.iterdir()) == ["owned.txt", "unrelated"]


def test_mutation_during_staging_blocks_before_wp_env(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir()
    plugin = source / "plugin.php"; plugin.write_text("before", encoding="utf-8")
    expected = smoke.digest_regular_tree(source)
    original_copy = smoke.copy_plugin_artifact
    which_called = False

    def mutating_copy(path, root):
        destination = original_copy(path, root)
        plugin.write_text("after", encoding="utf-8")
        (destination / "plugin.php").write_text("after", encoding="utf-8")
        return destination

    def forbidden_which(_name):
        nonlocal which_called
        which_called = True
        raise AssertionError("wp-env discovery must not run after staged digest mismatch")

    monkeypatch.setattr(smoke, "copy_plugin_artifact", mutating_copy)
    monkeypatch.setattr(smoke.shutil, "which", forbidden_which)
    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "runtime", artifact_path=source,
                             expected_artifact_digest=expected)
    assert result["status"] == "blocked"
    assert result["input_artifact_digest"] != expected
    assert which_called is False


def test_staging_symlink_swap_never_copies_external_or_starts_wp_env(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir()
    candidate = source / "plugin.php"; candidate.write_text("safe", encoding="utf-8")
    external = tmp_path / "external"; external.write_text("DO-NOT-COPY", encoding="utf-8")
    original_open = certifier.os.open
    which_called = False

    swapped = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == candidate and not swapped:
            swapped = True
            candidate.unlink(); candidate.symlink_to(external)
        return original_open(path, flags, *args, **kwargs)

    def forbidden_which(_name):
        nonlocal which_called
        which_called = True
        return "/usr/bin/npx"

    monkeypatch.setattr(certifier.os, "open", swapping_open)
    monkeypatch.setattr(smoke.shutil, "which", forbidden_which)
    with pytest.raises(OSError):
        smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "runtime", artifact_path=source)
    assert which_called is False
    copied = list((tmp_path / "runtime").rglob("plugin.php"))
    assert all(path.read_text(encoding="utf-8") != "DO-NOT-COPY" for path in copied if not path.is_symlink())


def test_phpunit_smoke_blocks_when_artifact_composer_install_fails():
    ok_command = smoke.CommandRun(["ok"], "/tmp", 0, "ok", "", 0.01)
    failed_composer = smoke.CommandRun(["composer", "install"], "/tmp", 1, "", "failed", 0.01)

    status = smoke.status_from_gates(
        npx="/usr/bin/npx",
        provision_full_profile=False,
        provisioning={"artifact_composer_install": failed_composer},
        start=ok_command,
        activation=ok_command,
        narrow_gate={"status": "pass"},
        full_profile={"status": "blocked"},
        ability_smoke=None,
        block_smoke=None,
        editor_smoke=None,
        interactivity_static_gate=None,
        interactivity_smoke=False,
        block_deprecation_static_gate=None,
        block_deprecation_smoke=False,
        block_deprecation_post=None,
        block_build_gate=None,
        block_build_smoke=False,
        phpunit_gate={"status": "pass"},
        phpunit_smoke=True,
        mcp_adapter_gate=None,
        mcp_adapter_smoke=False,
        ai_client_gate=None,
        ai_client_smoke=False,
        stop=ok_command,
        strict_full_profile=False,
    )

    assert status == "blocked"


def test_runtime_smoke_can_provision_full_profile(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        checks = [
            {"id": "phpcs_wpcs", "status": "pass"},
            {"id": "plugin_check", "status": "pass"},
        ]
        return {"status": "pass", "pass": True, "checks": checks, "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        keep_artifacts=True,
        provision_full_profile=True,
    )

    assert result["status"] == "pass"
    assert sorted(result["provisioning"]) == ["composer_install", "plugin_check_install"]
    assert "not WPCS proof" not in result["negative_space"]
    assert "acme-runtime-smoke" in (Path(result["runtime_root"]) / "composer.json").read_text(encoding="utf-8")
    assert commands[0][0][:2] == ["/usr/bin/composer", "install"]
    assert commands[2][0][-3:] == ["plugin", "activate", "acme-runtime-smoke"]
    assert commands[3][0][-4:] == ["plugin", "install", "plugin-check", "--activate"]


def test_runtime_smoke_uses_existing_artifact_and_records_ability_smoke(tmp_path, monkeypatch):
    source = tmp_path / "generated" / "acme-generated"
    source.mkdir(parents=True)
    (source / "acme-generated.php").write_text("<?php\n/**\n * Plugin Name: Acme Generated\n */\n", encoding="utf-8")
    commands = []
    validated_paths = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, path, args):
        validated_paths.append(path)
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        keep_artifacts=True,
        ability_name="acme/get-status",
    )

    assert result["status"] == "pass"
    assert result["source_artifact_path"] == str(source.resolve())
    assert result["ability_smoke_status"] == "pass"
    assert result["artifact_path"].endswith("acme-generated")
    assert "not proof of executor-generated artifacts" not in result["negative_space"]
    assert any(command[0][-2] == "eval" for command in commands)
    assert {path.name for path in validated_paths} == {"acme-generated"}


def test_runtime_smoke_can_verify_block_registration(tmp_path, monkeypatch):
    commands = []
    validate_calls = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(artifact_type, path, args):
        validate_calls.append((artifact_type, path.name, args.require_tool))
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        keep_artifacts=True,
        fixture_kind="block",
    )

    assert result["status"] == "pass"
    assert result["block_name"] == "acme/runtime-card"
    assert result["block_smoke_status"] == "pass"
    assert "not block validation proof" not in result["negative_space"]
    assert "not full block validation proof" in result["negative_space"]
    assert any("WP_Block_Type_Registry" in " ".join(command[0]) for command in commands)
    assert ("block", "acme-block-runtime-smoke", ["wp-env"]) in validate_calls


def test_runtime_smoke_can_verify_editor_block_registry(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        keep_artifacts=True,
        fixture_kind="block",
        block_name="acme/runtime-card",
        editor_smoke=True,
    )

    editor_command = next(command for command, _cwd in commands if any("run_wordpress_editor_smoke.js" in part for part in command))

    assert result["status"] == "pass"
    assert result["editor_smoke_status"] == "pass"
    assert "not editor or browser smoke proof" not in result["negative_space"]
    assert "not full editor interaction proof" in result["negative_space"]
    assert "--url" in editor_command
    assert editor_command[editor_command.index("--url") + 1] == "http://localhost:8899"
    assert editor_command[editor_command.index("--block-name") + 1] == "acme/runtime-card"


def test_runtime_smoke_can_request_editor_insert_render_smoke(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        keep_artifacts=True,
        fixture_kind="block",
        block_name="acme/runtime-card",
        editor_insert_render_smoke=True,
    )

    editor_command = next(command for command, _cwd in commands if any("run_wordpress_editor_smoke.js" in part for part in command))

    assert result["status"] == "pass"
    assert result["editor_smoke_requested"] is True
    assert result["editor_insert_render_smoke_requested"] is True
    assert result["editor_smoke_status"] == "pass"
    assert "--insert-render-smoke" in editor_command
    assert "not full editor interaction proof" not in result["negative_space"]
    assert "not block deprecation proof" in result["negative_space"]
    assert "not Interactivity API proof" in result["negative_space"]


def test_runtime_smoke_wraps_generated_block_artifact_for_editor_insert_render(tmp_path, monkeypatch):
    source = tmp_path / "generated-block"
    block_dir = source / "blocks" / "runtime-card"
    block_dir.mkdir(parents=True)
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "apiVersion": 3,
                "name": "acme/runtime-card",
                "title": "Runtime Card",
                "category": "widgets",
                "textdomain": "acme-runtime-card",
                "editorScript": "file:./index.js",
                "render": "file:./render.php",
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "index.js").write_text("window.wp.blocks.registerBlockType( 'acme/runtime-card', {} );\n", encoding="utf-8")
    (block_dir / "index.asset.php").write_text("<?php\nreturn array( 'dependencies' => array() );\n", encoding="utf-8")
    (block_dir / "render.php").write_text("<?php echo esc_html__( 'Runtime block smoke', 'acme' );\n", encoding="utf-8")
    commands = []
    validate_calls = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(artifact_type, path, args):
        validate_calls.append((artifact_type, path.resolve(), args.require_tool))
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        editor_insert_render_smoke=True,
    )
    editor_command = next(command for command, _cwd in commands if any("run_wordpress_editor_smoke.js" in part for part in command))

    assert result["status"] == "pass"
    assert result["artifact_kind"] == "block"
    assert result["source_artifact_path"] == str(source.resolve())
    assert result["block_name"] == "acme/runtime-card"
    assert result["wrapped_block_artifact"]["block_name"] == "acme/runtime-card"
    assert result["wrapped_block_artifact"]["textdomain"] == "acme-runtime-card"
    assert result["artifact_path"].endswith("acme-runtime-card")
    assert result["editor_smoke_status"] == "pass"
    assert "--insert-render-smoke" in editor_command
    assert editor_command[editor_command.index("--block-name") + 1] == "acme/runtime-card"
    assert "not proof of executor-generated artifacts" not in result["negative_space"]
    assert "not editor or browser smoke proof" not in result["negative_space"]
    assert ("block", source.resolve(), ["wp-env"]) in validate_calls


def test_runtime_smoke_runs_generated_block_build_gate_on_disposable_copy(tmp_path, monkeypatch):
    source = tmp_path / "generated-block"
    block_dir = source / "blocks" / "runtime-card"
    block_dir.mkdir(parents=True)
    (source / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "build": "wp-scripts build blocks/runtime-card/index.js --output-path=blocks/runtime-card/build"
                },
                "devDependencies": {"@wordpress/scripts": "^30.0.0"},
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "apiVersion": 3,
                "name": "acme/runtime-card",
                "title": "Runtime Card",
                "category": "widgets",
                "textdomain": "acme-runtime-card",
                "editorScript": "file:./index.js",
                "render": "file:./render.php",
            }
        ),
        encoding="utf-8",
    )
    (block_dir / "index.js").write_text("window.wp.blocks.registerBlockType( 'acme/runtime-card', {} );\n", encoding="utf-8")
    (block_dir / "render.php").write_text("<?php echo esc_html__( 'Runtime block smoke', 'acme-runtime-card' );\n", encoding="utf-8")
    commands = []
    validate_calls = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(artifact_type, path, args):
        validate_calls.append((artifact_type, path.resolve(), args.require_tool))
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        block_build_smoke=True,
        editor_insert_render_smoke=True,
    )

    copied_artifact = Path(result["runtime_root"]) / "acme-runtime-card" / "generated"
    npm_install = next(command for command, cwd in commands if command[:3] == ["/usr/bin/npm", "install", "--no-audit"])

    assert npm_install == ["/usr/bin/npm", "install", "--no-audit", "--no-fund"]
    assert result["status"] == "pass"
    assert result["block_build_smoke_requested"] is True
    assert result["block_build_smoke_status"] == "pass"
    assert result["wrapped_block_artifact"]["copied_artifact_dir"] == str(copied_artifact)
    assert "not full block validation proof" not in result["negative_space"]
    assert ("block", copied_artifact.resolve(), ["npm-build"]) in validate_calls


def test_block_interactivity_surface_gate_requires_exact_surfaces(tmp_path):
    source = write_interactive_block_artifact(tmp_path / "generated-block")

    result = smoke.check_block_interactivity_surfaces(source)

    assert result["status"] == "pass"
    assert {check["id"] for check in result["checks"]} >= {
        "supports_interactivity",
        "view_script_module_declared",
        "interactivity_import",
        "interactivity_store",
        "wp_interactive_directive",
        "wp_click_directive",
        "wp_text_directive",
        "experimental_modules_build",
    }


def test_block_interactivity_surface_gate_fails_missing_view_module(tmp_path):
    source = write_interactive_block_artifact(
        tmp_path / "generated-block",
        view_script_module="file:./missing-view.js",
    )

    result = smoke.check_block_interactivity_surfaces(source)

    assert result["status"] == "fail"
    assert any(
        check["id"] == "view_script_module_exists" and check["status"] == "fail"
        for check in result["checks"]
    )


def test_runtime_smoke_can_request_interactivity_smoke(tmp_path, monkeypatch):
    source = write_interactive_block_artifact(tmp_path / "generated-block")
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        block_build_smoke=True,
        editor_insert_render_smoke=True,
        interactivity_smoke=True,
    )
    editor_command = next(command for command, _cwd in commands if any("run_wordpress_editor_smoke.js" in part for part in command))

    assert result["status"] == "pass"
    assert result["interactivity_smoke_requested"] is True
    assert result["interactivity_smoke_status"] == "pass"
    assert result["interactivity_static_gate"]["status"] == "pass"
    assert "--interactivity-smoke" in editor_command
    assert "not block deprecation or Interactivity API proof" not in result["negative_space"]
    assert "not block deprecation proof" in result["negative_space"]


def test_block_deprecation_surface_gate_requires_fixture_and_migration(tmp_path):
    source = write_deprecated_block_artifact(tmp_path / "generated-block")

    result = smoke.check_block_deprecation_surfaces(source)

    assert result["status"] == "pass"
    assert result["old_content_file"] == "fixtures/deprecated-v1.html"
    assert result["expected_migrated_text"] == "Runtime block smoke: Legacy runtime smoke"
    assert result["expected_migrated_attribute_name"] == "content"
    assert {check["id"] for check in result["checks"]} >= {
        "deprecation_smoke_config",
        "deprecation_fixture_exists",
        "deprecation_fixture_targets_block",
        "deprecated_array_declared",
        "deprecated_migrate_declared",
    }


def test_block_deprecation_surface_gate_fails_missing_legacy_fixture(tmp_path):
    source = write_deprecated_block_artifact(tmp_path / "generated-block", include_fixture=False)

    result = smoke.check_block_deprecation_surfaces(source)

    assert result["status"] == "fail"
    assert any(
        check["id"] == "deprecation_fixture_exists" and check["status"] == "fail"
        for check in result["checks"]
    )


def test_runtime_smoke_can_request_block_deprecation_smoke(tmp_path, monkeypatch):
    source = write_deprecated_block_artifact(tmp_path / "generated-block")
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        if command[-2] == "eval" and "wp_insert_post" in command[-1]:
            return smoke.CommandRun(command, str(cwd), 0, '{"postId":123}', "", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        block_build_smoke=True,
        block_deprecation_smoke=True,
    )
    editor_command = next(command for command, _cwd in commands if any("run_wordpress_editor_smoke.js" in part for part in command))

    assert result["status"] == "pass"
    assert result["block_deprecation_smoke_requested"] is True
    assert result["block_deprecation_smoke_status"] == "pass"
    assert result["block_deprecation_static_gate"]["status"] == "pass"
    assert "--deprecation-smoke" in editor_command
    assert editor_command[editor_command.index("--post-id") + 1] == "123"
    assert "--expected-migrated-text" in editor_command
    assert "not block deprecation proof" not in result["negative_space"]
    assert "not Interactivity API proof" in result["negative_space"]


def test_runtime_smoke_runs_generated_plugin_phpunit_gate_on_disposable_copy(tmp_path, monkeypatch):
    source = tmp_path / "generated" / "acme-generated"
    source.mkdir(parents=True)
    (source / "acme-generated.php").write_text(
        "<?php\n/**\n * Plugin Name: Acme Generated\n *\n * @package AcmeGenerated\n */\n",
        encoding="utf-8",
    )
    (source / "composer.json").write_text(
        json.dumps({"require-dev": {"phpunit/phpunit": "^12.0"}}),
        encoding="utf-8",
    )
    (source / "phpunit.xml").write_text("<phpunit />\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "GeneratedTest.php").write_text("<?php\n", encoding="utf-8")
    commands = []
    validate_calls = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(artifact_type, path, args):
        validate_calls.append((artifact_type, path.resolve(), args.require_tool))
        checks = []
        if args.require_tool == ["phpunit"]:
            checks.append({"id": "phpunit", "status": "pass", "required": True})
        return {"status": "pass", "pass": True, "checks": checks, "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        keep_artifacts=True,
        phpunit_smoke=True,
    )

    copied_artifact = Path(result["runtime_root"]) / "acme-generated"
    composer_install = next(command for command, cwd in commands if command[:2] == ["/usr/bin/composer", "install"])

    assert composer_install == ["/usr/bin/composer", "install", "--no-interaction", "--no-progress", "--quiet"]
    assert result["status"] == "pass"
    assert result["phpunit_smoke_requested"] is True
    assert result["phpunit_smoke_status"] == "pass"
    assert "not PHPUnit proof" not in result["negative_space"]
    assert ("plugin", copied_artifact.resolve(), ["phpunit"]) in validate_calls


def test_parse_wp_env_site_url_from_stderr():
    command = smoke.CommandRun(
        ["wp-env", "start"],
        "/tmp",
        0,
        "",
        "WordPress development site started at http://localhost:8893\nMySQL is listening on port 32816",
        0.01,
    )

    assert smoke.parse_wp_env_site_url(command) == "http://localhost:8893"


def test_ability_smoke_missing_api_is_blocked():
    command = smoke.CommandRun(["wp", "eval"], "/tmp", 3, "", "wp_get_ability unavailable", 0.01)

    assert smoke.ability_smoke_status(command) == "blocked"


def test_ability_smoke_registration_error_is_fail_even_when_eval_source_is_echoed():
    stderr = "wp_get_ability unavailable; WordPress 6.9+ Abilities API not present.\nability not registered: acme/get-status"
    command = smoke.CommandRun(["wp", "eval"], "/tmp", 1, "", stderr, 0.01)

    assert smoke.ability_smoke_status(command) == "fail"


def test_block_smoke_registration_error_is_fail():
    command = smoke.CommandRun(["wp", "eval"], "/tmp", 4, "", "block not registered: acme/missing", 0.01)

    assert smoke.block_smoke_status(command) == "fail"


def test_editor_smoke_missing_node_is_blocked():
    command = smoke.CommandRun(["node"], "/tmp", 127, "", "node executable not found", 0.0)

    assert smoke.editor_smoke_status(command) == "blocked"


def test_editor_smoke_frontend_render_helper_requires_wrapper_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for editor smoke helper test")
    script = HARNESS_ROOT / "run_wordpress_editor_smoke.js"
    code = """
const assert = require("assert");
const smoke = require(process.argv[1]);
assert.strictEqual(smoke.defaultBlockClassName("acme/runtime-card"), "wp-block-acme-runtime-card");
assert.strictEqual(smoke.defaultBlockClassName("core/paragraph"), "wp-block-paragraph");
assert.strictEqual(
  smoke.verifyFrontendRender("Runtime block smoke", "wp-block-acme-runtime-card").frontendTextFound,
  true,
);
assert.deepStrictEqual(
  smoke.verifyInteractivityResult("0", "1"),
  { beforeText: "0", afterText: "1", clickChangedText: true },
);
assert.deepStrictEqual(
  smoke.verifyDeprecationResult({
    targetBlockFound: true,
    migratedAttributeFound: true,
    serializedMarkerFound: true,
    invalidBlockUIFound: false,
    didSaveFail: false,
  }),
  {
    targetBlockFound: true,
    migratedAttributeFound: true,
    serializedMarkerFound: true,
    invalidBlockUIFound: false,
    didSaveFail: false,
  },
);
assert.throws(
  () => smoke.verifyFrontendRender("Unrelated body text", "wp-block-acme-runtime-card"),
  /frontend render text not found/,
);
assert.throws(
  () => smoke.verifyInteractivityResult("0", "0"),
  /updated text mismatch|did not change/,
);
assert.throws(
  () => smoke.verifyDeprecationResult({
    targetBlockFound: true,
    migratedAttributeFound: false,
    serializedMarkerFound: true,
    invalidBlockUIFound: false,
    didSaveFail: false,
    expectedMigratedAttribute: "Legacy runtime smoke",
    expectedMigratedAttributeName: "content",
  }),
  /migrated attribute not found/,
);
"""
    subprocess.run([node, "-e", code, str(script)], check=True)


def test_mcp_public_ability_static_gate_requires_meta_public(tmp_path):
    plugin_dir = write_mcp_public_ability_artifact(tmp_path)

    gate = smoke.check_mcp_public_ability_surfaces(plugin_dir, "acme-mcp-smoke/get-runtime-marker")

    assert gate["status"] == "pass"
    assert {check["id"]: check["status"] for check in gate["checks"]} == {
        "mcp_smoke_ability_name": "pass",
        "mcp_public_meta_flag": "pass",
        "mcp_public_ability_registered": "pass",
    }


def test_mcp_adapter_runtime_gate_passes_for_discover_and_execute():
    ok_install = smoke.CommandRun(["wp", "plugin", "install"], "/tmp", 0, "installed", "", 0.01)
    ok_list = smoke.CommandRun(["wp", "mcp-adapter", "list"], "/tmp", 0, "mcp-adapter-default-server", "", 0.01)
    ok_tools = smoke.CommandRun(
        ["wp", "mcp-adapter", "serve"],
        "/tmp",
        0,
        '{"result":{"tools":[{"name":"mcp-adapter-discover-abilities"},{"name":"mcp-adapter-get-ability-info"},{"name":"mcp-adapter-execute-ability"}]}}',
        "",
        0.01,
    )
    ok_discover = smoke.CommandRun(
        ["wp", "mcp-adapter", "serve"],
        "/tmp",
        0,
        '{"result":{"content":[{"text":"acme-mcp-smoke/get-runtime-marker"}]}}',
        "",
        0.01,
    )
    ok_execute = smoke.CommandRun(
        ["wp", "mcp-adapter", "serve"],
        "/tmp",
        0,
        '{"result":{"content":[{"text":"Runtime MCP smoke"}]}}',
        "",
        0.01,
    )

    gate = smoke.mcp_adapter_runtime_gate(
        requested=True,
        static_gate={"status": "pass"},
        install=ok_install,
        list_servers=ok_list,
        tools_list=ok_tools,
        discover=ok_discover,
        execute=ok_execute,
        ability_name="acme-mcp-smoke/get-runtime-marker",
        expected_output="Runtime MCP smoke",
    )

    assert smoke.mcp_adapter_smoke_status(gate) == "pass"


def test_runtime_smoke_can_verify_mcp_adapter_smoke(tmp_path, monkeypatch):
    source = write_mcp_public_ability_artifact(tmp_path / "generated")
    commands = []
    input_commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if command[-2:] == ["start", "--auto-port"]:
            return smoke.CommandRun(command, str(cwd), 0, "", "WordPress development site started at http://localhost:8899", 0.01)
        if command[-2:] == ["mcp-adapter", "list"]:
            return smoke.CommandRun(command, str(cwd), 0, "mcp-adapter-default-server", "", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_run_command_with_input(command, cwd, _timeout, input_text):
        input_commands.append((command, input_text))
        if '"method":"tools/list"' in input_text:
            output = '{"result":{"tools":[{"name":"mcp-adapter-discover-abilities"},{"name":"mcp-adapter-get-ability-info"},{"name":"mcp-adapter-execute-ability"}]}}'
        elif "mcp-adapter-discover-abilities" in input_text:
            output = '{"result":{"content":[{"text":"acme-mcp-smoke/get-runtime-marker"}]}}'
        else:
            output = '{"result":{"content":[{"text":"Runtime MCP smoke"}]}}'
        return smoke.CommandRun(command, str(cwd), 0, output, "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke, "run_command_with_input", fake_run_command_with_input)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        keep_artifacts=True,
        ability_name="acme-mcp-smoke/get-runtime-marker",
        mcp_adapter_smoke=True,
        mcp_adapter_execute_args={"marker": "Runtime MCP smoke"},
        mcp_adapter_expected_output="Runtime MCP smoke",
    )

    assert result["status"] == "pass"
    assert result["mcp_adapter_smoke_status"] == "pass"
    assert "not MCP Adapter runtime proof" not in result["negative_space"]
    assert any(smoke.MCP_ADAPTER_PLUGIN_ZIP in command for command, _cwd in commands)
    assert len(input_commands) == 3


def test_ai_client_provider_static_gate_requires_provider_helper(tmp_path):
    plugin_dir = write_ai_client_provider_artifact(tmp_path)

    gate = smoke.check_ai_client_provider_surfaces(
        plugin_dir,
        "acme-ai-client-smoke",
        "acme-deterministic-text",
        "AcmeAIClientSmoke\\generate_summary",
    )

    assert gate["status"] == "pass"
    assert {check["id"]: check["status"] for check in gate["checks"]} == {
        "ai_client_provider_id": "pass",
        "ai_client_model_id": "pass",
        "ai_client_prompt_helper": "pass",
        "ai_client_error_boundary": "pass",
        "ai_client_provider_registered": "pass",
        "ai_client_provider_interfaces": "pass",
        "ai_client_helper_function": "pass",
    }

    missing_helper = smoke.check_ai_client_provider_surfaces(
        plugin_dir,
        "acme-ai-client-smoke",
        "acme-deterministic-text",
        "AcmeAIClientSmoke\\missing_summary",
    )

    assert missing_helper["status"] == "fail"
    assert {check["id"]: check["status"] for check in missing_helper["checks"]}["ai_client_helper_function"] == "fail"


def test_ai_client_provider_call_gate_passes_for_registered_provider():
    command = smoke.CommandRun(
        ["wp", "--user=admin", "eval"],
        "/tmp",
        0,
        json.dumps(
            {
                "provider_id": "acme-ai-client-smoke",
                "model_id": "acme-deterministic-text",
                "helper_function": "AcmeAIClientSmoke\\generate_summary",
                "wp_ai_client_prompt": True,
                "ai_client_registry": True,
                "provider_registered": True,
                "provider_configured": True,
                "connector_registered": True,
                "output": "AI Client smoke: deterministic provider response",
            }
        ),
        "",
        0.01,
    )

    gate = smoke.ai_client_provider_call_gate(
        requested=True,
        static_gate={"status": "pass"},
        command=command,
        provider_id="acme-ai-client-smoke",
        model_id="acme-deterministic-text",
        helper_function="AcmeAIClientSmoke\\generate_summary",
        expected_output="AI Client smoke: deterministic provider response",
    )

    assert smoke.ai_client_smoke_status(gate) == "pass"


def test_runtime_smoke_can_verify_ai_client_smoke(tmp_path, monkeypatch):
    source = write_ai_client_provider_artifact(tmp_path / "generated")
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        if "eval" in command and any("wp_ai_client_prompt" in part for part in command):
            output = json.dumps(
                {
                    "provider_id": "acme-ai-client-smoke",
                    "model_id": "acme-deterministic-text",
                    "helper_function": "AcmeAIClientSmoke\\generate_summary",
                    "wp_ai_client_prompt": True,
                    "ai_client_registry": True,
                    "provider_registered": True,
                    "provider_configured": True,
                    "connector_registered": True,
                    "output": "AI Client smoke: deterministic provider response",
                }
            )
            return smoke.CommandRun(command, str(cwd), 0, output, "", 0.01)
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        checks = [
            {"id": "phpcs_wpcs", "status": "pass"},
            {"id": "plugin_check", "status": "pass"},
        ]
        return {"status": "pass", "pass": True, "checks": checks, "profile": args.profile}

    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        keep_artifacts=True,
        ai_client_smoke=True,
        ai_client_provider_id="acme-ai-client-smoke",
        ai_client_model_id="acme-deterministic-text",
        ai_client_helper_function="AcmeAIClientSmoke\\generate_summary",
        ai_client_prompt="Runtime AI Client smoke",
        ai_client_expected_output="AI Client smoke: deterministic provider response",
    )

    ai_client_commands = [command for command, _cwd in commands if any("wp_ai_client_prompt" in part for part in command)]

    assert result["status"] == "pass"
    assert result["ai_client_smoke_status"] == "pass"
    assert "not AI Client provider-call proof" not in result["negative_space"]
    assert ai_client_commands
    assert any(command.index("--user=admin") < command.index("eval") for command in ai_client_commands)


def test_runtime_smoke_blocks_when_wp_env_start_fails(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(command, cwd, _timeout):
        commands.append((command, cwd))
        return smoke.CommandRun(command, str(cwd), 1, "", "port is allocated", 0.01)

    monkeypatch.setattr(smoke, "run_command", fake_run_command)

    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "fixture", keep_artifacts=True)

    assert result["status"] == "blocked"
    assert result["narrow_gate"] is None
    assert result["commands"]["stop"] is None
