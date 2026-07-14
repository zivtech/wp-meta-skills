"""Tests for the disposable WordPress runtime smoke harness."""

import json
import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import certify_wordpress_executor_artifact as certifier
import run_wordpress_runtime_smoke as smoke

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def patch_artifact_validators(monkeypatch, validator):
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_artifact", validator)

    def validate_staged(artifact_type, staged, args, *, source_path=None, subpath=None):
        path = source_path or (staged.root / subpath if subpath else staged.root)
        return validator(artifact_type, path, args)

    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_staged_artifact", validate_staged)


def patch_successful_block_build(monkeypatch, tmp_path, source):
    output = import_sandbox_output(source,tmp_path/"sandbox-output")
    outcome = smoke.runtime_artifact_pipeline.artifact_execution.ExecutionOutcome(
        "pass", "sandbox passed", ("npm", "run", "build"), output
    )
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.artifact_execution, "run_generated", lambda *_args: outcome)
    return output


def import_sandbox_output(source, parent):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive:
        archive.add(source,arcname=".")
    stream.seek(0)
    return smoke.artifact_staging.import_tar_stream(stream,parent,dependency_policy="strict")


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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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
    original_stage = smoke.artifact_staging.stage_tree
    which_called = False

    def stage_then_mutate(path):
        staged = original_stage(path)
        plugin.write_text("after", encoding="utf-8")
        return staged

    def observe_which(_name):
        nonlocal which_called
        which_called = True
        return None

    monkeypatch.setattr(smoke.artifact_staging, "stage_tree", stage_then_mutate)
    monkeypatch.setattr(smoke.shutil, "which", observe_which)
    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "runtime", artifact_path=source,
                             expected_artifact_digest=expected)
    assert result["status"] == "blocked"
    assert result["input_artifact_digest"] == expected
    assert plugin.read_text() == "after"
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
        if str(path) == candidate.name and kwargs.get("dir_fd") is not None and not swapped:
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


def test_staging_root_swap_at_open_never_copies_external_or_starts_wp_env(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir()
    (source / "plugin.php").write_text("safe", encoding="utf-8")
    external = tmp_path / "external"; external.mkdir()
    (external / "secret.php").write_text("DO-NOT-COPY", encoding="utf-8")
    original_open = certifier.os.open
    swapped = False
    which_called = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if str(path) == source.name and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            moved = tmp_path / "moved-source"; source.rename(moved)
            source.symlink_to(external, target_is_directory=True)
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
    assert not any(path.name == "secret.php" for path in (tmp_path / "runtime").rglob("*"))


def test_phpunit_smoke_blocks_when_sandbox_gate_blocks():
    ok_command = smoke.CommandRun(["ok"], "/tmp", 0, "ok", "", 0.01)

    status = smoke.status_from_gates(
        npx="/usr/bin/npx",
        provision_full_profile=False,
        provisioning={},
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
        phpunit_gate={"status": "blocked"},
        phpunit_smoke=True,
        mcp_adapter_gate=None,
        mcp_adapter_smoke=False,
        ai_client_gate=None,
        ai_client_smoke=False,
        stop=ok_command,
        strict_full_profile=False,
    )

    assert status == "blocked"


def test_required_blocked_gate_dominates_fail_regardless_order():
    ok=smoke.CommandRun(["ok"],"/tmp",0,"ok","",0.01)
    common=dict(
        npx="/usr/bin/npx",provision_full_profile=False,provisioning={},start=ok,activation=ok,
        narrow_gate={"status":"pass"},full_profile=None,ability_smoke=None,block_smoke=None,
        editor_smoke=None,interactivity_static_gate=None,interactivity_smoke=False,
        block_deprecation_static_gate=None,block_deprecation_smoke=False,block_deprecation_post=None,
        block_build_smoke=True,phpunit_smoke=True,mcp_adapter_gate=None,mcp_adapter_smoke=False,
        ai_client_gate=None,ai_client_smoke=False,stop=ok,strict_full_profile=False,
    )
    first=smoke.status_from_gates(**common,block_build_gate={"status":"fail"},phpunit_gate={"status":"blocked"})
    second=smoke.status_from_gates(**common,block_build_gate={"status":"blocked"},phpunit_gate={"status":"fail"})
    assert first=="blocked" and second=="blocked"


@pytest.mark.parametrize("metadata",[None,"{malformed"])
def test_runtime_preparation_metadata_failure_cleans_sandbox_output(tmp_path,monkeypatch,metadata):
    source=tmp_path/"source"; source.mkdir(); (source/"package.json").write_text('{"scripts":{"build":"echo ok"}}')
    if metadata is not None: (source/"block.json").write_text(metadata)
    output=patch_successful_block_build(monkeypatch,tmp_path,source)
    patch_artifact_validators(monkeypatch,lambda *_args,**_kwargs:{"status":"pass","pass":True,"checks":[]})
    result=smoke.run_smoke(
        timeout_sec=5,workdir=tmp_path/"runtime",artifact_path=source,
        artifact_kind="block",block_build_smoke=True,
    )
    receipt=result["artifact_retention"]["components"]["sandbox_output"]
    assert result["status"]=="blocked" and receipt["state"]=="removed"
    assert not output.lease.root.exists()
    assert next(check for check in result["checks"] if check["id"]=="artifact_preparation")["status"]=="blocked"


def test_runtime_preparation_synthesis_exception_cleans_sandbox_output(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir()
    (source/"block.json").write_text('{"name":"acme/card","title":"Card","category":"widgets"}')
    output=patch_successful_block_build(monkeypatch,tmp_path,source)
    patch_artifact_validators(monkeypatch,lambda *_args,**_kwargs:{"status":"pass","pass":True,"checks":[]})
    monkeypatch.setattr(smoke.runtime_artifact_pipeline,"synthesize_block_runtime",lambda *_args:(_ for _ in ()).throw(RuntimeError("synthesis exploded")))
    result=smoke.run_smoke(
        timeout_sec=5,workdir=tmp_path/"runtime",artifact_path=source,
        artifact_kind="block",block_build_smoke=True,
    )
    assert result["status"]=="blocked"
    assert result["artifact_retention"]["components"]["sandbox_output"]["state"]=="removed"
    assert not output.lease.root.exists() and "synthesis exploded" in result["checks"][0]["detail"]


def test_runtime_retains_typed_sandbox_import_cleanup_evidence_end_to_end(tmp_path, monkeypatch):
    source=tmp_path/"source"; source.mkdir()
    (source/"block.json").write_text('{"name":"acme/card","title":"Card","category":"widgets"}')
    retained=import_sandbox_output(source,tmp_path/"retained-output")
    error="WorkspaceCleanupError: cleanup did not complete normally"
    receipt=smoke.artifact_staging.StagingCleanupReceipt(
        "sandbox_output",smoke.artifact_staging.StageRole.SANDBOX_OUTPUT,retained.lease,retained.root,
        "retained",True,True,str(retained.root),error,
    )
    sandbox=smoke.runtime_artifact_pipeline.artifact_execution.sandboxed_package_runner.SandboxResult(
        "blocked",None,"","",None,"import blocked","container",staging_cleanup_receipts=(receipt,)
    )
    execution=smoke.runtime_artifact_pipeline.artifact_execution
    monkeypatch.setattr(execution,"_profile",lambda *_args:"approved")
    monkeypatch.setattr(execution,"_image",lambda _kind:"node@sha256:"+"a"*64)
    monkeypatch.setattr(execution.sandboxed_package_runner,"run_sandbox",lambda _request:sandbox)
    monkeypatch.setattr(smoke.shutil,"which",lambda _name:None)
    try:
        result=smoke.run_smoke(
            timeout_sec=5,workdir=tmp_path/"runtime",artifact_path=source,
            artifact_kind="block",block_build_smoke=True,
        )
        component=result["artifact_retention"]["components"]["sandbox_output"]
        assert result["status"]=="blocked" and component["state"]=="retained"
        assert component["recovery_path"]==str(retained.root) and component["error"]==error
        assert component["exists"] is True and component["live"] is True
        assert [item["resource_path"] for item in component["resources"]]==[str(retained.root)]
    finally:
        smoke.runtime_artifact_pipeline.workspace_lease.cleanup(retained.lease)


def test_runtime_preparation_preserves_post_stage_and_sandbox_cleanup_receipts(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir()
    (source / "block.json").write_text('{"name":"acme/card","title":"Card","category":"widgets"}')
    staged = smoke.artifact_staging.stage_tree(source, tmp_path / "input")
    output = patch_successful_block_build(monkeypatch, tmp_path, source)
    patch_artifact_validators(monkeypatch, lambda *_args, **_kwargs: {"status": "pass", "pass": True, "checks": []})
    monkeypatch.setattr(smoke.runtime_artifact_pipeline, "SynthesizedRuntime", lambda *_args: (_ for _ in ()).throw(RuntimeError("constructor failed")))
    try:
        with pytest.raises(smoke.runtime_artifact_pipeline.RuntimePreparationError, match="constructor failed") as caught:
            smoke._prepare_generated_runtime(
                staged, "block", source, True, False, False, 5,
                tmp_path / "runtime", tmp_path / "trusted-wpcs",
            )
        receipts = {receipt.component: receipt for receipt in caught.value.receipts}
        assert set(receipts) == {"synthesized_runtime", "sandbox_output"}
        assert all(receipt.state == "removed" for receipt in receipts.values())
        assert not output.root.exists()
    finally:
        smoke.runtime_artifact_pipeline.workspace_lease.cleanup(staged.lease)


def test_runtime_preparation_preserves_primary_and_cleanup_failure(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir()
    (source/"block.json").write_text('{"name":"acme/card","title":"Card","category":"widgets"}')
    output=patch_successful_block_build(monkeypatch,tmp_path,source)
    patch_artifact_validators(monkeypatch,lambda *_args,**_kwargs:{"status":"pass","pass":True,"checks":[]})
    original=smoke.runtime_artifact_pipeline.workspace_lease.cleanup
    def cleanup(lease):
        if lease is output.lease: raise smoke.WorkspaceCleanupError("cleanup exploded")
        return original(lease)
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease,"cleanup",cleanup)
    monkeypatch.setattr(smoke.runtime_artifact_pipeline,"synthesize_block_runtime",lambda *_args:(_ for _ in ()).throw(RuntimeError("synthesis exploded")))
    result=smoke.run_smoke(timeout_sec=5,workdir=tmp_path/"runtime",artifact_path=source,artifact_kind="block",block_build_smoke=True)
    checks={check["id"]:check["detail"] for check in result["checks"]}
    assert result["status"]=="blocked" and "synthesis exploded" in checks["artifact_preparation"]
    assert "cleanup" in checks["sandbox_output_cleanup"]
    assert result["artifact_retention"]["components"]["sandbox_output"]["recovery_path"]==str(output.root)
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease,"cleanup",original)
    original(output.lease)


def test_runtime_input_exception_surfaces_cleanup_failure_and_retained_copy(tmp_path,monkeypatch):
    source=tmp_path/"source"; source.mkdir(); (source/"plugin.php").write_text("<?php")
    original=smoke.runtime_artifact_pipeline.workspace_lease.cleanup
    @smoke.stage_runtime_input
    def explode(**_kwargs): raise RuntimeError("wrapped exploded")
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease,"cleanup",lambda _lease:(_ for _ in ()).throw(smoke.WorkspaceCleanupError("cleanup exploded")))
    with pytest.raises(smoke.runtime_artifact_pipeline.RuntimeInputCleanupError,match="wrapped exploded.*cleanup") as caught:
        explode(artifact_path=source)
    receipt=caught.value.receipt
    assert receipt.state=="retained" and receipt.recovery_path and Path(receipt.recovery_path).exists()
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease,"cleanup",original)
    original(next(lease for lease in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES.values() if lease.root==Path(receipt.resource_path).parent))


def test_pre_body_verification_failure_propagates_after_cleaning_owned_input(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir(); (source / "plugin.php").write_text("<?php")
    created = []
    body_called = False
    original_stage = smoke.artifact_staging.stage_tree

    def capture_stage(*args, **kwargs):
        staged = original_stage(*args, **kwargs)
        created.append(staged)
        return staged

    @smoke.stage_runtime_input
    def body(**_kwargs):
        nonlocal body_called
        body_called = True

    monkeypatch.setattr(smoke.artifact_staging, "stage_tree", capture_stage)
    monkeypatch.setattr(smoke.artifact_staging, "verify_staged_tree", lambda _staged: (_ for _ in ()).throw(RuntimeError("initial verification failed")))
    with pytest.raises(RuntimeError, match="initial verification failed"):
        body(artifact_path=source)
    assert body_called is False and created
    assert not created[0].root.exists()
    assert created[0].lease.lease_id not in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES


def test_pre_body_staging_error_propagates_without_leaking_a_lease(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "outside.php").symlink_to(tmp_path / "outside.php")
    live_before = set(smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES)

    @smoke.stage_runtime_input
    def body(**_kwargs):
        raise AssertionError("body must not run after pre-body staging failure")

    with pytest.raises(ValueError, match="link|special"):
        body(artifact_path=source)
    assert set(smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES) == live_before


def test_pre_body_internal_staging_dual_failure_translates_retained_input_receipt(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir(); (source / "plugin.php").write_text("<?php")
    original_cleanup = smoke.runtime_artifact_pipeline.workspace_lease.cleanup
    monkeypatch.setattr(smoke.artifact_staging, "_manifest_from_fd", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("staging verification failed")))
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease, "cleanup", lambda _lease: (_ for _ in ()).throw(smoke.WorkspaceCleanupError("cleanup failed")))
    retained = None

    @smoke.stage_runtime_input
    def body(**_kwargs):
        raise AssertionError("body must not run after pre-body staging failure")

    try:
        with pytest.raises(smoke.runtime_artifact_pipeline.RuntimeInputCleanupError, match="staging verification failed.*cleanup") as caught:
            body(artifact_path=source)
        error = caught.value; receipt = error.receipt
        assert isinstance(error.primary, RuntimeError) and str(error.primary) == "staging verification failed"
        assert receipt.component == "input_copy" and receipt.state == "retained"
        assert receipt.exists and receipt.live and receipt.error
        assert receipt.recovery_path and Path(receipt.recovery_path).exists()
        retained = next(
            lease for lease in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES.values()
            if lease.root / "artifact" == Path(receipt.resource_path)
        )
    finally:
        monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease, "cleanup", original_cleanup)
        if retained is not None and retained.lease_id in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES:
            original_cleanup(retained)


def test_pre_body_verification_and_cleanup_failure_preserve_both_and_retained_input(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.mkdir(); (source / "plugin.php").write_text("<?php")
    created = []
    original_stage = smoke.artifact_staging.stage_tree
    original_cleanup = smoke.runtime_artifact_pipeline.workspace_lease.cleanup

    def capture_stage(*args, **kwargs):
        staged = original_stage(*args, **kwargs)
        created.append(staged)
        return staged

    @smoke.stage_runtime_input
    def body(**_kwargs):
        raise AssertionError("body must not run after pre-body failure")

    monkeypatch.setattr(smoke.artifact_staging, "stage_tree", capture_stage)
    monkeypatch.setattr(smoke.artifact_staging, "verify_staged_tree", lambda _staged: (_ for _ in ()).throw(RuntimeError("initial verification failed")))
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease, "cleanup", lambda _lease: (_ for _ in ()).throw(smoke.WorkspaceCleanupError("cleanup failed")))
    try:
        with pytest.raises(smoke.runtime_artifact_pipeline.RuntimeInputCleanupError, match="initial verification failed.*cleanup") as caught:
            body(artifact_path=source)
        receipt = caught.value.receipt
        assert isinstance(caught.value.primary, RuntimeError)
        assert receipt.state == "retained" and receipt.error
        assert receipt.recovery_path == str(created[0].root) and created[0].root.exists()
        assert created[0].lease.lease_id in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES
    finally:
        monkeypatch.setattr(smoke.runtime_artifact_pipeline.workspace_lease, "cleanup", original_cleanup)
        if created and created[0].lease.lease_id in smoke.runtime_artifact_pipeline.workspace_lease._LIVE_LEASES:
            original_cleanup(created[0].lease)


def test_runtime_smoke_can_provision_full_profile(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(smoke.wp_security_gate, "resolve_toolchain", lambda _root: (
        SimpleNamespace(php="/usr/bin/php", phpcs=tmp_path / "vendor/bin/phpcs",
                        installed_paths="/pinned/wpcs"), None,
    ))

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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        keep_artifacts=True,
        provision_full_profile=True,
    )

    assert result["status"] == "pass"
    assert sorted(result["provisioning"]) == ["phpcs_wpcs_toolchain", "plugin_check_install"]
    assert "not WPCS proof" not in result["negative_space"]
    assert not (Path(result["runtime_root"]) / "composer.json").exists()
    assert commands[0][0][:2] == ["/usr/bin/php", str(tmp_path / "vendor/bin/phpcs")]
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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        keep_artifacts=True,
        ability_name="acme/get-status",
    )

    assert result["status"] == "blocked"
    assert result["ability_smoke_status"] == "blocked"
    assert result["sandbox_posture"]["host_fallback"] is False
    assert "ability-oracle" in result["reason"]
    assert commands == [] and validated_paths == []


def test_runtime_smoke_accepts_caller_held_stage_without_restaging(tmp_path, monkeypatch):
    source = tmp_path / "generated" / "acme-held"
    source.mkdir(parents=True)
    (source / "acme-held.php").write_text("<?php\n/** Plugin Name: Acme Held */\n", encoding="utf-8")
    staged = smoke.artifact_staging.stage_tree(source)
    claimed = tmp_path / "claimed" / "different-plugin"
    manifest_digest = smoke.artifact_staging.manifest_sha256(staged.manifest)

    def forbidden_stage(_source):
        raise AssertionError("caller-held staged capability must not be restaged")

    def fake_run_command(command, cwd, _timeout):
        return smoke.CommandRun(command, str(cwd), 0, "ok", "", 0.01)

    def fake_validate_artifact(_artifact_type, _path, args):
        return {"status": "pass", "pass": True, "checks": [], "profile": args.profile}

    monkeypatch.setattr(smoke.artifact_staging, "stage_tree", forbidden_stage)
    monkeypatch.setattr(smoke.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(smoke, "run_command", fake_run_command)
    patch_artifact_validators(monkeypatch, fake_validate_artifact)
    try:
        result = smoke.run_smoke(
            timeout_sec=5,
            workdir=tmp_path / "fixture",
            staged_artifact=staged,
            artifact_source_path=claimed,
        )

        assert result["status"] == "blocked"
        assert result["source_artifact_path"] == str(source.resolve())
        assert result["source_artifact_attested"] is True
        assert result["claimed_source_artifact_path"] == str(claimed.absolute())
        assert result["artifact_execution_copy"] == str(staged.root)
        assert result["artifact_execution_retained"] is True
        assert result["artifact_manifest_sha256"] == manifest_digest
        assert result["sandbox_posture"]["input_capability"] == "caller_held"
        assert result["sandbox_posture"]["host_fallback"] is False
        assert "not proof of executor-generated artifacts" in result["negative_space"]
        assert staged.lease.lease_id not in json.dumps(result)
        smoke.artifact_staging.verify_staged_tree(staged)
    finally:
        smoke.cleanup_workspace(staged.lease)


def test_boolean_executor_provenance_cannot_erase_negative_space(tmp_path, monkeypatch):
    source = tmp_path / "generated" / "acme-untrusted"
    source.mkdir(parents=True)
    (source / "acme-untrusted.php").write_text("<?php\n/** Plugin Name: Untrusted */\n", encoding="utf-8")
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: None)

    with pytest.raises(TypeError, match="executor_provenance"):
        smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "rejected", artifact_path=source, executor_provenance=True)
    result = smoke.run_smoke(timeout_sec=5, workdir=tmp_path / "fixture", artifact_path=source)
    assert "not proof of executor-generated artifacts" in result["negative_space"]


def test_cli_evidence_strings_do_not_issue_executor_provenance(tmp_path, monkeypatch, capsys):
    source = tmp_path / "generated" / "acme-cli"
    source.mkdir(parents=True)
    (source / "acme-cli.php").write_text("<?php\n/** Plugin Name: CLI */\n", encoding="utf-8")
    digest = smoke.digest_regular_tree(source)
    captured = {}

    def fake_run_smoke(**kwargs):
        captured.update(kwargs)
        return {"status": "blocked", "pass": False, "negative_space": list(smoke.BASE_NEGATIVE_SPACE), "input_artifact_digest": digest}

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)
    code = smoke.main([
        "--artifact-path", str(source), "--evidence-id", "caller-string",
        "--expected-artifact-digest", digest,
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2 and "executor_provenance" not in captured
    assert "not proof of executor-generated artifacts" in payload["negative_space"]


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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        editor_insert_render_smoke=True,
    )
    assert result["status"] == "blocked"
    assert result["editor_smoke_status"] == "blocked"
    assert "legacy-editor-oracle" in result["reason"]
    assert commands == [] and validate_calls == []


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
    built = tmp_path / "sandbox-built"
    shutil.copytree(source, built)
    built_block = built / "blocks" / "runtime-card" / "build"
    built_block.mkdir()
    shutil.copy2(block_dir / "block.json", built_block / "block.json")
    (built_block / "marker.js").write_text("fresh sandbox output\n", encoding="utf-8")
    output = import_sandbox_output(built,tmp_path/"sandbox-output")
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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)
    outcome = smoke.runtime_artifact_pipeline.artifact_execution.ExecutionOutcome(
        "pass", "sandbox passed", ("npm", "run", "build"), output
    )
    monkeypatch.setattr(smoke.runtime_artifact_pipeline.artifact_execution, "run_generated", lambda *_args: outcome)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        block_build_smoke=True,
        editor_insert_render_smoke=True,
    )

    assert not any(command[:2] == ["/usr/bin/npm", "install"] for command, _cwd in commands)
    assert result["status"] == "blocked"
    assert result["block_build_smoke_status"] == "blocked"
    assert result["editor_smoke_status"] == "blocked"
    assert "legacy-editor-oracle" in result["reason"]
    assert any(call[0] == "block" and call[2] == [] for call in validate_calls)
    assert result["artifact_retention"]["components"]["sandbox_output"]["state"] == "removed"


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
    patch_successful_block_build(monkeypatch, tmp_path, source)
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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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
    assert result["status"] == "blocked"
    assert result["interactivity_smoke_status"] == "blocked"
    assert result["editor_smoke_status"] == "blocked"
    assert "legacy-editor-oracle" in result["reason"]
    assert commands == []


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
    patch_successful_block_build(monkeypatch, tmp_path, source)
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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        artifact_kind="block",
        keep_artifacts=True,
        block_build_smoke=True,
        block_deprecation_smoke=True,
    )
    assert result["status"] == "blocked"
    assert result["block_deprecation_smoke_status"] == "blocked"
    assert result["editor_smoke_status"] == "blocked"
    assert "legacy-editor-oracle" in result["reason"]
    assert commands == []


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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

    result = smoke.run_smoke(
        timeout_sec=5,
        workdir=tmp_path / "fixture",
        artifact_path=source,
        keep_artifacts=True,
        phpunit_smoke=True,
    )

    assert not any(command[:2] == ["/usr/bin/composer", "install"] for command, _cwd in commands)
    assert result["status"] == "blocked"
    assert result["phpunit_smoke_status"] == "blocked"
    assert result["sandbox_posture"]["host_fallback"] is False
    assert validate_calls == []


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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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

    assert result["status"] == "blocked"
    assert result["mcp_adapter_smoke_status"] == "blocked"
    assert "mcp-adapter" in result["reason"]
    assert commands == [] and input_commands == []


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
    patch_artifact_validators(monkeypatch, fake_validate_artifact)

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

    assert result["status"] == "blocked"
    assert result["ai_client_smoke_status"] == "blocked"
    assert "ai-client" in result["reason"]
    assert ai_client_commands == []


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
