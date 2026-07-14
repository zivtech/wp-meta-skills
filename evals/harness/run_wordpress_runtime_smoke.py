#!/usr/bin/env python3
"""Run a disposable WordPress wp-env runtime smoke for generated artifacts.

This harness makes the manual runtime proof reproducible:

1. Create a tiny plugin fixture under a temporary wp-env project.
2. Start WordPress with @wordpress/env using automatic port selection.
3. Run the generated artifact oracle against the plugin directory while pointing
   wp-env checks at the project root.
4. Stop the wp-env project and emit a JSON summary.

The default pass condition is intentionally narrow: php lint plus a wp-env smoke
must pass. The full plugin runtime profile is recorded as informational unless
--strict-full-profile is set.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import validate_wordpress_artifact
import artifact_staging
import isolated_runtime_contract
import runtime_artifact_pipeline
import wp_env_network_guard
import wp_security_gate
from wp_runtime_types import RuntimeRequest, RuntimeResult
from certify_wordpress_executor_artifact import EVIDENCE_SCHEMA_VERSION
from artifact_staging import EXECUTION_CLOSURE_IGNORE, digest_regular_tree, snapshot_regular_tree_with_kind
from workspace_lease import (WorkspaceCleanupError, WorkspacePurpose, cleanup as cleanup_workspace,
                             create_ephemeral, create_named, validate_safe_name)
from workspace_lease import validate_output_parent


ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = ROOT / "evals" / "results" / "wordpress-skill-candidate-eval"
DEFAULT_RUN_ID = "wp-env-runtime-smoke"
MCP_ADAPTER_PLUGIN_ZIP = "https://github.com/WordPress/mcp-adapter/releases/latest/download/mcp-adapter.zip"
PHP_TOOLS_ROOT = ROOT / "evals" / "harness" / "php-tools"


def create_wp_env_temp_root() -> Path:
    """Create a temp root whose basename is safe for wp-env Docker names."""
    return create_ephemeral(Path(tempfile.gettempdir()), WorkspacePurpose.RUNTIME).root


def _prepare_runtime_input(kwargs):
    source = kwargs.get("artifact_path")
    staged = kwargs.get("staged_artifact")
    if source is not None and staged is not None:
        raise ValueError("artifact_path and staged_artifact are mutually exclusive")
    owned = None
    try:
        owned = artifact_staging.stage_tree(Path(source)) if source is not None else None
        active = owned or staged
        manifest = artifact_staging.verify_staged_tree(active) if active is not None else None
        if active is not None:
            kwargs["staged_artifact"] = active
            reported = kwargs.get("artifact_source_path") or source
            kwargs["artifact_source_path"] = Path(reported).expanduser().absolute() if reported else None
        return owned, active, manifest
    except artifact_staging.StagingCleanupError as error:
        receipt=runtime_artifact_pipeline.cleanup_receipt_from_staging("input_copy",error.receipt)
        raise runtime_artifact_pipeline.RuntimeInputCleanupError(error.primary,receipt) from error
    except Exception as primary:
        if owned is None: raise
        receipt=runtime_artifact_pipeline.cleanup_component("input_copy",owned)
        if receipt.state!="removed" or receipt.error:
            raise runtime_artifact_pipeline.RuntimeInputCleanupError(primary,receipt) from primary
        raise


def _cleanup_runtime_input(owned, active):
    if owned is not None:
        return runtime_artifact_pipeline.cleanup_component("input_copy", owned)
    if active is not None:
        return runtime_artifact_pipeline.observe_component("input_copy", active)
    return None


def _runtime_sandbox_posture(result, owned, active):
    generated = {}
    for requested, status, name in (
        ("block_build_smoke_requested", "block_build_smoke_status", "npm_build"),
        ("phpunit_smoke_requested", "phpunit_smoke_status", "phpunit"),
    ):
        generated[name] = result.get(status, "not_run") if result.get(requested) else "not_requested"
    return {
        "generated_execution": generated,
        "host_fallback": False,
        "input_capability": "fresh_stage" if owned else "caller_held" if active else "fixture",
        "static_scan_root": "staged_copy",
    }


def _merge_evidence(base, overlay):
    merged = dict(base) if isinstance(base, dict) else {}
    for key, value in overlay.items():
        prior = merged.get(key)
        merged[key] = _merge_evidence(prior, value) if isinstance(value, dict) else value
    return merged


def _attach_runtime_input_evidence(result, owned, active, manifest, input_receipt):
    receipts = result.pop("_artifact_retention_receipts", [])
    if input_receipt is not None:
        receipts.append(input_receipt)
    retention = runtime_artifact_pipeline.retention_summary(receipts)
    result["artifact_execution_copy"] = str(active.root) if active else None
    result["artifact_execution_retained"] = bool(input_receipt and (input_receipt.exists or input_receipt.live))
    result["artifact_retention"] = retention
    result["artifact_manifest_sha256"] = (
        artifact_staging.manifest_sha256(manifest) if manifest is not None else None
    )
    result["sandbox_posture"] = _merge_evidence(
        result.get("sandbox_posture"), _runtime_sandbox_posture(result, owned, active)
    )
    cleanup_failures = [
        receipt for receipt in receipts
        if receipt.state not in {"removed", "not_created"}
        or receipt.error or receipt.exists or receipt.live
    ]
    cleanup_blocked = bool(cleanup_failures)
    if cleanup_blocked:
        result["status"] = "blocked"
        result["pass"] = False
        failed = cleanup_failures[0]
        result["artifact_execution_cleanup_error"] = (
            failed.error or f"{failed.component} remains {failed.state}"
        )
    return result


def stage_runtime_input(function):
    """Stage before the body; propagate staging errors but never leak an owned lease."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        owned, active, manifest = _prepare_runtime_input(kwargs)
        evidence_id = kwargs.pop("evidence_id", None)
        primary = None; result = None
        try:
            if active is not None and function.__name__ == "run_smoke":
                if "executor_provenance" in kwargs:
                    raise TypeError("run_smoke() got an unexpected keyword argument 'executor_provenance'")
                result = _run_isolated_smoke_input(active, evidence_id, kwargs)
                result.update({
                    "source_artifact_path":active.source_path if active.source_attested else None,
                    "source_artifact_attested":active.source_attested,
                    "claimed_source_artifact_path":str(kwargs["artifact_source_path"]) if kwargs.get("artifact_source_path") else None,
                })
            else:
                result = function(*args, **kwargs)
            if active is not None and artifact_staging.verify_staged_tree(active) != manifest:
                raise RuntimeError("runtime smoke mutated the held staged artifact")
        except Exception as exc:
            primary = exc
        finally:
            input_receipt = _cleanup_runtime_input(owned, active)
        if primary is not None:
            if owned is not None and input_receipt is not None and (input_receipt.state != "removed" or input_receipt.error):
                raise runtime_artifact_pipeline.RuntimeInputCleanupError(primary,input_receipt) from primary
            raise primary
        return _attach_runtime_input_evidence(result, owned, active, manifest, input_receipt)
    return wrapped


BASE_NEGATIVE_SPACE = (
    "not PHPUnit proof",
    "not block validation proof",
    "not editor or browser smoke proof",
    "not proof of executor-generated artifacts",
)
ARTIFACT_COPY_IGNORE = set(EXECUTION_CLOSURE_IGNORE)


@dataclass(frozen=True)
class CommandRun:
    command: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class WrappedBlockArtifact:
    plugin_dir: Path
    copied_artifact_dir: Path
    source_block_dir: Path
    copied_block_dir: Path
    block_name: str
    textdomain: str


@dataclass(frozen=True)
class PreparedRuntimeArtifact:
    synthesized: runtime_artifact_pipeline.SynthesizedRuntime
    effective_block: artifact_staging.StagedTree | None
    sandbox_output: artifact_staging.StagedTree | None
    block_build_gate: dict[str, Any] | None
    phpunit_gate: dict[str, Any] | None
    wpcs_gate: dict[str, Any] | None
    trusted_provisioning: dict[str, Any]
    wrapped: WrappedBlockArtifact | None
    preparation_receipts: tuple[runtime_artifact_pipeline.CleanupReceipt, ...] = ()


def write_runtime_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    plugin_dir = root / "acme-runtime-smoke"
    plugin_dir.mkdir(exist_ok=True)

    write_wp_env_config(root, plugin_dir.name)

    (plugin_dir / "acme-runtime-smoke.php").write_text(
        """<?php
/**
 * Plugin Name: Acme Runtime Smoke
 * Description: Disposable runtime smoke plugin for wp-meta-skills validation.
 * Version: 0.1.0
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Author: Zivtech
 * License: GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 *
 * @package AcmeRuntimeSmoke
 */

if ( ! defined( 'ABSPATH' ) ) {
\texit;
}

add_action( 'init', 'acme_runtime_smoke_register_setting' );

/**
 * Register the runtime smoke setting.
 */
function acme_runtime_smoke_register_setting(): void {
\tregister_setting(
\t\t'acme_runtime_smoke',
\t\t'acme_runtime_smoke_mode',
\t\tarray(
\t\t\t'type'              => 'string',
\t\t\t'sanitize_callback' => 'sanitize_key',
\t\t\t'default'           => 'default',
\t\t)
\t);
}
""",
        encoding="utf-8",
    )
    (plugin_dir / "readme.txt").write_text(
        """=== Acme Runtime Smoke ===
Contributors: zivtech
Tags: testing
Requires at least: 6.5
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Disposable runtime smoke plugin for wp-meta-skills validation.

== Description ==

This plugin exists only to validate the WordPress runtime smoke harness.

== Changelog ==

= 0.1.0 =
Initial runtime smoke fixture.
""",
        encoding="utf-8",
    )
    return plugin_dir


def write_block_runtime_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    plugin_dir = root / "acme-block-runtime-smoke"
    plugin_dir.mkdir(exist_ok=True)

    write_wp_env_config(root, plugin_dir.name)

    (plugin_dir / "acme-block-runtime-smoke.php").write_text(
        """<?php
/**
 * Plugin Name: Acme Block Runtime Smoke
 * Description: Disposable block runtime smoke plugin for wp-meta-skills validation.
 * Version: 0.1.0
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Author: Zivtech
 * License: GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 *
 * @package AcmeBlockRuntimeSmoke
 */

if ( ! defined( 'ABSPATH' ) ) {
\texit;
}

add_action( 'init', 'acme_block_runtime_smoke_register_block' );

/**
 * Register the runtime smoke block.
 */
function acme_block_runtime_smoke_register_block(): void {
\tregister_block_type( __DIR__ . '/blocks/runtime-card' );
}
""",
        encoding="utf-8",
    )
    block_dir = plugin_dir / "blocks" / "runtime-card"
    block_dir.mkdir(parents=True, exist_ok=True)
    (block_dir / "block.json").write_text(
        json.dumps(
            {
                "apiVersion": 3,
                "name": "acme/runtime-card",
                "title": "Runtime Card",
                "category": "widgets",
                "textdomain": "acme-block-runtime-smoke",
                "editorScript": "file:./index.js",
                "render": "file:./render.php",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (block_dir / "index.asset.php").write_text(
        """<?php
/**
 * Editor script asset metadata for the runtime smoke block.
 *
 * @package AcmeBlockRuntimeSmoke
 */

return array(
\t'dependencies' => array( 'wp-blocks', 'wp-element', 'wp-i18n' ),
\t'version'      => '0.1.0',
);
""",
        encoding="utf-8",
    )
    (block_dir / "index.js").write_text(
        """( function ( blocks, element, i18n ) {
\tconst el = element.createElement;
\tconst __ = i18n.__;

\tblocks.registerBlockType( 'acme/runtime-card', {
\t\tedit: function () {
\t\t\treturn el( 'p', {}, __( 'Runtime block smoke', 'acme-block-runtime-smoke' ) );
\t\t},
\t\tsave: function () {
\t\t\treturn null;
\t\t},
\t} );
} )( window.wp.blocks, window.wp.element, window.wp.i18n );
""",
        encoding="utf-8",
    )
    (block_dir / "render.php").write_text(
        """<?php
/**
 * Render callback template for the runtime smoke block.
 *
 * @package AcmeBlockRuntimeSmoke
 */

?>
<div <?php echo wp_kses_data( get_block_wrapper_attributes() ); ?>>
\t<?php echo esc_html__( 'Runtime block smoke', 'acme-block-runtime-smoke' ); ?>
</div>
""",
        encoding="utf-8",
    )
    (plugin_dir / "readme.txt").write_text(
        """=== Acme Block Runtime Smoke ===
Contributors: zivtech
Tags: block, testing
Requires at least: 6.5
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Disposable block runtime smoke plugin for wp-meta-skills validation.
""",
        encoding="utf-8",
    )
    return plugin_dir


def write_wp_env_config(root: Path, plugin_path: str) -> None:
    configured = plugin_path if Path(plugin_path).is_absolute() else f"./{plugin_path}"
    config = {
        "plugins": [configured],
        "config": {"WP_DEBUG": True},
        "testsEnvironment": False,
        "autoPort": True,
    }
    (root / ".wp-env.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def wrapped_block_artifact_summary(wrapped: WrappedBlockArtifact | None) -> dict[str, str] | None:
    if not wrapped:
        return None
    return {
        "plugin_dir": str(wrapped.plugin_dir),
        "copied_artifact_dir": str(wrapped.copied_artifact_dir),
        "source_block_dir": str(wrapped.source_block_dir),
        "copied_block_dir": str(wrapped.copied_block_dir),
        "block_name": wrapped.block_name,
        "textdomain": wrapped.textdomain,
    }


def _write_staged_file(destination: Path, content: bytes) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure no-follow artifact staging is unavailable")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)


def copy_plugin_artifact(source: Path, root: Path, *, artifact_name: str | None = None) -> Path:
    source = source.expanduser().absolute()
    root_kind, snapshot = snapshot_regular_tree_with_kind(source)
    destination_name = artifact_name or source.name
    if Path(destination_name).name != destination_name or destination_name in {"", ".", ".."}:
        raise ValueError("artifact name is not a safe path component")

    root.mkdir(parents=True, exist_ok=True)
    plugin_dir = root / destination_name
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)

    if root_kind == "directory":
        plugin_dir.mkdir()
        for relative, content, _info in snapshot:
            destination = plugin_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _write_staged_file(destination, content)
    else:
        plugin_dir.mkdir()
        _relative, content, _info = snapshot[0]
        _write_staged_file(plugin_dir / source.name, content)

    write_wp_env_config(root, plugin_dir.name)
    return plugin_dir


def safe_plugin_slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:48] or "generated-block"


def block_textdomain(metadata: dict[str, Any]) -> str:
    textdomain = metadata.get("textdomain")
    if isinstance(textdomain, str) and textdomain.strip():
        return safe_plugin_slug(textdomain)
    block_name = str(metadata.get("name", "generated-block"))
    return safe_plugin_slug(block_name.split("/")[-1])


def find_block_metadata(source: Path, *, prefer_build: bool = False) -> tuple[Path, dict[str, Any]]:
    source = source.resolve()
    if source.is_file():
        candidates = [source] if source.name == "block.json" else []
    else:
        candidates = sorted(path for path in source.rglob("block.json") if ".git" not in path.parts and "node_modules" not in path.parts)
    if prefer_build:
        build_candidates = [path for path in candidates if "build" in path.parts]
        candidates = build_candidates + [path for path in candidates if path not in build_candidates]
    if not candidates:
        raise FileNotFoundError(f"no block.json found in generated block artifact: {source}")
    block_json = candidates[0]
    data = json.loads(block_json.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError(f"{block_json} must contain a block name")
    return block_json, data


def _metadata_file_entries(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        entries: list[str] = []
        for item in value:
            entries.extend(_metadata_file_entries(item))
        return entries
    return []


def _resolve_block_asset_files(block_dir: Path, value: Any) -> list[Path]:
    paths: list[Path] = []
    for entry in _metadata_file_entries(value):
        if entry.startswith("file:"):
            paths.append((block_dir / entry.removeprefix("file:")).resolve())
    return paths


def _check_result(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "status": "pass" if passed else "fail", "detail": detail}


def aggregate_artifact_text(source: Path, *, suffixes: set[str]) -> str:
    source = source.resolve()
    if source.is_file():
        return source.read_text(encoding="utf-8", errors="replace") if source.suffix.lower() in suffixes else ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(source.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in suffixes
        and "node_modules" not in path.parts
        and ".git" not in path.parts
        and "vendor" not in path.parts
    )


def check_block_interactivity_surfaces(source: Path) -> dict[str, Any]:
    """Check deterministic Interactivity API surfaces before browser smoke."""

    block_json, metadata = find_block_metadata(source, prefer_build=True)
    block_dir = block_json.parent
    source_root = block_json.parent if source.is_file() else source.resolve()
    aggregate = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(source_root.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in {".php", ".js", ".json"}
        and "node_modules" not in path.parts
        and ".git" not in path.parts
    )
    view_script_files = _resolve_block_asset_files(block_dir, metadata.get("viewScriptModule"))
    view_script_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in view_script_files if path.exists())
    package_json = source_root / "package.json"
    package_scripts: dict[str, Any] = {}
    if package_json.exists():
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
        package_scripts = package_data.get("scripts") if isinstance(package_data.get("scripts"), dict) else {}
    build_script = str(package_scripts.get("build", ""))

    supports = metadata.get("supports") if isinstance(metadata.get("supports"), dict) else {}
    checks = [
        _check_result(
            "supports_interactivity",
            supports.get("interactivity") is True,
            "block.json supports.interactivity is true"
            if supports.get("interactivity") is True
            else "block.json must set supports.interactivity: true",
        ),
        _check_result(
            "view_script_module_declared",
            bool(view_script_files),
            f"viewScriptModule resolves to {', '.join(str(path.relative_to(source_root)) for path in view_script_files if path.is_relative_to(source_root))}"
            if view_script_files
            else "block.json must declare viewScriptModule with a file: reference",
        ),
        _check_result(
            "view_script_module_exists",
            bool(view_script_files) and all(path.exists() for path in view_script_files),
            "viewScriptModule target file(s) exist"
            if view_script_files and all(path.exists() for path in view_script_files)
            else "viewScriptModule target file(s) must exist before runtime smoke",
        ),
        _check_result(
            "interactivity_import",
            "@wordpress/interactivity" in f"{view_script_text}\n{aggregate}",
            "frontend module imports @wordpress/interactivity"
            if "@wordpress/interactivity" in f"{view_script_text}\n{aggregate}"
            else "frontend module must import @wordpress/interactivity",
        ),
        _check_result(
            "interactivity_store",
            bool(re.search(r"\bstore\s*\(", f"{view_script_text}\n{aggregate}")),
            "frontend module defines an Interactivity API store"
            if re.search(r"\bstore\s*\(", f"{view_script_text}\n{aggregate}")
            else "frontend module must call store(...)",
        ),
        _check_result(
            "wp_interactive_directive",
            "data-wp-interactive" in aggregate,
            "frontend markup includes data-wp-interactive"
            if "data-wp-interactive" in aggregate
            else "frontend markup must include data-wp-interactive",
        ),
        _check_result(
            "wp_click_directive",
            "data-wp-on--click" in aggregate,
            "frontend markup includes data-wp-on--click"
            if "data-wp-on--click" in aggregate
            else "frontend markup must include a click directive",
        ),
        _check_result(
            "wp_text_directive",
            "data-wp-text" in aggregate,
            "frontend markup includes data-wp-text"
            if "data-wp-text" in aggregate
            else "frontend markup must include data-wp-text for deterministic state assertion",
        ),
        _check_result(
            "experimental_modules_build",
            "--experimental-modules" in build_script,
            "package build script uses --experimental-modules"
            if "--experimental-modules" in build_script
            else "package build script must use --experimental-modules",
        ),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "pass": status == "pass",
        "artifact_path": str(source.resolve()),
        "block_json": str(block_json),
        "view_script_modules": [str(path) for path in view_script_files],
        "checks": checks,
    }


def _source_root(source: Path, block_json: Path) -> Path:
    return block_json.parent if source.is_file() else source.resolve()


def check_block_deprecation_surfaces(source: Path) -> dict[str, Any]:
    """Check deterministic block deprecation surfaces before editor migration smoke."""

    block_json, metadata = find_block_metadata(source, prefer_build=False)
    source_root = _source_root(source.resolve(), block_json)
    aggregate = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(source_root.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in {".html", ".js", ".json"}
        and "node_modules" not in path.parts
        and ".git" not in path.parts
        and "build" not in path.parts
    )
    config_candidates = sorted(source_root.rglob("deprecation-smoke.json"))
    smoke_config: dict[str, Any] = {}
    config_error: str | None = None
    if config_candidates:
        try:
            loaded = json.loads(config_candidates[0].read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                smoke_config = loaded
            else:
                config_error = "deprecation-smoke.json must contain an object"
        except json.JSONDecodeError as exc:
            config_error = f"deprecation-smoke.json is invalid JSON: {exc}"

    old_content_file = str(smoke_config.get("oldContentFile", "fixtures/deprecated-v1.html"))
    old_content_path = (source_root / old_content_file).resolve()
    old_content = old_content_path.read_text(encoding="utf-8", errors="replace") if old_content_path.exists() else ""
    block_name = str(metadata["name"])
    expected_migrated_text = str(smoke_config.get("expectedMigratedText", "Runtime block smoke: Legacy runtime smoke"))
    expected_migrated_attribute_name = str(smoke_config.get("expectedMigratedAttributeName", "content"))
    expected_migrated_attribute = str(smoke_config.get("expectedMigratedAttribute", "Legacy runtime smoke"))
    expected_serialized_marker = str(smoke_config.get("expectedSerializedMarker", "<strong>Runtime block smoke:</strong>"))

    checks = [
        _check_result(
            "deprecation_smoke_config",
            bool(config_candidates) and not config_error,
            f"deprecation smoke config found at {config_candidates[0].relative_to(source_root)}"
            if config_candidates and not config_error
            else config_error or "deprecation-smoke.json must describe the legacy fixture and expected migrated output",
        ),
        _check_result(
            "deprecation_fixture_exists",
            old_content_path.exists(),
            f"legacy serialized fixture found at {old_content_file}"
            if old_content_path.exists()
            else f"legacy serialized fixture missing: {old_content_file}",
        ),
        _check_result(
            "deprecation_fixture_targets_block",
            f"<!-- wp:{block_name}" in old_content,
            f"legacy fixture contains serialized {block_name} block"
            if f"<!-- wp:{block_name}" in old_content
            else f"legacy fixture must contain serialized {block_name} content",
        ),
        _check_result(
            "deprecated_array_declared",
            bool(re.search(r"\bdeprecated\s*:", aggregate)),
            "block script declares a deprecated array"
            if re.search(r"\bdeprecated\s*:", aggregate)
            else "block script must declare deprecated versions",
        ),
        _check_result(
            "deprecated_save_declared",
            "deprecated" in aggregate and bool(re.search(r"\bsave\s*\(", aggregate)),
            "deprecated block version includes a save implementation"
            if "deprecated" in aggregate and re.search(r"\bsave\s*\(", aggregate)
            else "deprecated block version must include save(...)",
        ),
        _check_result(
            "deprecated_migrate_declared",
            bool(re.search(r"\bmigrate\s*\(", aggregate)),
            "deprecated block version includes migrate(...)"
            if re.search(r"\bmigrate\s*\(", aggregate)
            else "deprecated block version must include migrate(...)",
        ),
        _check_result(
            "expected_migrated_text_configured",
            bool(expected_migrated_text.strip()),
            "expected migrated frontend text configured"
            if expected_migrated_text.strip()
            else "expectedMigratedText must be non-empty",
        ),
        _check_result(
            "expected_migrated_attribute_name_configured",
            bool(expected_migrated_attribute_name.strip()),
            "expected migrated attribute name configured"
            if expected_migrated_attribute_name.strip()
            else "expectedMigratedAttributeName must be non-empty",
        ),
        _check_result(
            "expected_serialized_marker_configured",
            bool(expected_serialized_marker.strip()),
            "expected current serialized marker configured"
            if expected_serialized_marker.strip()
            else "expectedSerializedMarker must be non-empty",
        ),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "pass": status == "pass",
        "artifact_path": str(source.resolve()),
        "block_json": str(block_json),
        "block_name": block_name,
        "old_content_file": old_content_file,
        "old_content": old_content,
        "expected_migrated_text": expected_migrated_text,
        "expected_migrated_attribute_name": expected_migrated_attribute_name,
        "expected_migrated_attribute": expected_migrated_attribute,
        "expected_serialized_marker": expected_serialized_marker,
        "checks": checks,
    }


def copy_block_artifact_as_plugin(source: Path, root: Path) -> WrappedBlockArtifact:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"artifact path does not exist: {source}")
    block_json, metadata = find_block_metadata(source)
    source_root = block_json.parent if source.is_file() else source
    source_block_dir = block_json.parent
    textdomain = block_textdomain(metadata)
    plugin_dir = root / textdomain
    generated_dir = plugin_dir / "generated"

    root.mkdir(parents=True, exist_ok=True)
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
    plugin_dir.mkdir(parents=True)
    if source_root.is_dir():
        shutil.copytree(
            source_root,
            generated_dir,
            ignore=shutil.ignore_patterns(*sorted(ARTIFACT_COPY_IGNORE)),
        )
    else:
        generated_dir.mkdir()
        shutil.copy2(source_root, generated_dir / source_root.name)

    copied_block_dir = generated_dir / source_block_dir.relative_to(source_root)
    block_relative_path = copied_block_dir.relative_to(plugin_dir).as_posix()
    plugin_file = plugin_dir / f"{plugin_dir.name}.php"
    plugin_file.write_text(
        f"""<?php
/**
 * Plugin Name: Generated Block Runtime Wrapper
 * Description: Temporary wp-env wrapper for a generated block executor artifact.
 * Version: 0.1.0
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Author: Zivtech
 * Text Domain: {textdomain}
 * License: GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 *
 * @package GeneratedBlockRuntimeWrapper
 */

if ( ! defined( 'ABSPATH' ) ) {{
\texit;
}}

add_action( 'init', 'generated_block_runtime_wrapper_register_block' );

/**
 * Register the generated block artifact.
 */
function generated_block_runtime_wrapper_register_block(): void {{
\t$generated_block_runtime_wrapper_block_dir       = __DIR__ . '/{block_relative_path}';
\t$generated_block_runtime_wrapper_built_block_dir = $generated_block_runtime_wrapper_block_dir . '/build';
\tregister_block_type(
\t\tfile_exists( $generated_block_runtime_wrapper_built_block_dir . '/block.json' )
\t\t\t? $generated_block_runtime_wrapper_built_block_dir
\t\t\t: $generated_block_runtime_wrapper_block_dir
\t);
}}
""",
        encoding="utf-8",
    )
    (plugin_dir / "readme.txt").write_text(
        f"""=== Generated Block Runtime Wrapper ===
Contributors: zivtech
Tags: block, testing
Requires at least: 6.5
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Temporary wp-env wrapper for the generated `{metadata["name"]}` block artifact.
""",
        encoding="utf-8",
    )
    write_wp_env_config(root, plugin_dir.name)
    return WrappedBlockArtifact(
        plugin_dir=plugin_dir,
        copied_artifact_dir=generated_dir,
        source_block_dir=source_block_dir,
        copied_block_dir=copied_block_dir,
        block_name=str(metadata["name"]),
        textdomain=textdomain,
    )


def truncate_output(value: str, limit: int = 16000) -> str:
    return value[-limit:] if len(value) > limit else value


def run_command(command: list[str], cwd: Path, timeout_sec: int) -> CommandRun:
    started = datetime.now()
    try:
        proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout_sec)
        duration = (datetime.now() - started).total_seconds()
        return CommandRun(
            command=command,
            cwd=str(cwd),
            returncode=proc.returncode,
            stdout=truncate_output(proc.stdout),
            stderr=truncate_output(proc.stderr),
            duration_sec=round(duration, 3),
        )
    except FileNotFoundError as exc:
        duration = (datetime.now() - started).total_seconds()
        return CommandRun(
            command=command,
            cwd=str(cwd),
            returncode=127,
            stdout="",
            stderr=str(exc),
            duration_sec=round(duration, 3),
        )
    except subprocess.TimeoutExpired as exc:
        duration = (datetime.now() - started).total_seconds()
        return CommandRun(
            command=command,
            cwd=str(cwd),
            returncode=124,
            stdout=truncate_output(exc.stdout or ""),
            stderr=truncate_output(exc.stderr or f"timed out after {timeout_sec}s"),
            duration_sec=round(duration, 3),
        )


def run_command_with_input(command: list[str], cwd: Path, timeout_sec: int, input_text: str) -> CommandRun:
    started = datetime.now()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )
        duration = (datetime.now() - started).total_seconds()
        return CommandRun(
            command=command,
            cwd=str(cwd),
            returncode=proc.returncode,
            stdout=truncate_output(proc.stdout),
            stderr=truncate_output(proc.stderr),
            duration_sec=round(duration, 3),
        )
    except FileNotFoundError as exc:
        duration = (datetime.now() - started).total_seconds()
        return CommandRun(
            command=command,
            cwd=str(cwd),
            returncode=127,
            stdout="",
            stderr=str(exc),
            duration_sec=round(duration, 3),
        )
    except subprocess.TimeoutExpired as exc:
        duration = (datetime.now() - started).total_seconds()
        return CommandRun(
            command=command,
            cwd=str(cwd),
            returncode=124,
            stdout=truncate_output(exc.stdout or ""),
            stderr=truncate_output(exc.stderr or f"timed out after {timeout_sec}s"),
            duration_sec=round(duration, 3),
        )


def missing_command(name: str, cwd: Path) -> CommandRun:
    return CommandRun([name], str(cwd), 127, "", f"{name} executable not found", 0.0)


def wp_env_cli_command(npx: str, *wp_args: str) -> list[str]:
    return [npx, "--yes", "@wordpress/env", "run", "cli", "--", "wp", *wp_args]


def parse_wp_env_site_url(command: CommandRun | None) -> str | None:
    if not command:
        return None
    haystack = f"{command.stdout}\n{command.stderr}"
    marker = "WordPress development site started at "
    for line in haystack.splitlines():
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return None


def ability_registration_eval(ability_name: str) -> str:
    return f"""
if ( ! function_exists( 'wp_get_ability' ) ) {{
    fwrite( STDERR, 'wp_get_ability unavailable; WordPress 6.9+ Abilities API not present.' );
    exit( 3 );
}}
$ability = wp_get_ability( {json.dumps(ability_name)} );
if ( ! $ability ) {{
    fwrite( STDERR, 'ability not registered: {ability_name}' );
    exit( 4 );
}}
echo wp_json_encode(
    array(
        'name'        => $ability->get_name(),
        'label'       => $ability->get_label(),
        'description' => $ability->get_description(),
        'category'    => $ability->get_category(),
    )
);
"""


def ability_post_summary_eval(ability_name: str) -> str:
    return f"""
if ( ! function_exists( 'wp_get_ability' ) ) {{
    fwrite( STDERR, 'wp_get_ability unavailable; WordPress 6.9+ Abilities API not present.' );
    exit( 3 );
}}
$user = get_user_by( 'login', 'admin' );
if ( $user ) {{
    wp_set_current_user( (int) $user->ID );
}}
$post_id = wp_insert_post(
    array(
        'post_title'   => 'Runtime Ability Smoke',
        'post_excerpt' => 'Runtime excerpt summary.',
        'post_content' => 'Runtime body content for ability smoke execution.',
        'post_status'  => 'publish',
        'post_author'  => get_current_user_id() ?: 1,
    ),
    true
);
if ( is_wp_error( $post_id ) ) {{
    fwrite( STDERR, $post_id->get_error_message() );
    exit( 5 );
}}
$ability = wp_get_ability( {json.dumps(ability_name)} );
if ( ! $ability ) {{
    fwrite( STDERR, 'ability not registered: {ability_name}' );
    exit( 4 );
}}
$result = $ability->execute( array( 'post_id' => (int) $post_id ) );
if ( is_wp_error( $result ) ) {{
    fwrite( STDERR, $result->get_error_message() );
    exit( 6 );
}}
if ( ! is_array( $result ) || empty( $result['summary'] ) ) {{
    fwrite( STDERR, 'ability execution did not return a summary array' );
    exit( 7 );
}}
echo wp_json_encode( $result );
"""


def ability_smoke_status(command: CommandRun | None) -> str:
    if command is None:
        return "not_run"
    if command.ok:
        return "pass"
    if "ability not registered" in command.stderr or "WP_Abilities_Registry::register" in command.stderr:
        return "fail"
    if "wp_get_ability unavailable" in command.stderr:
        return "blocked"
    return "fail"


def mcp_adapter_request(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        separators=(",", ":"),
    ) + "\n"


def mcp_adapter_tools_call_request(tool_name: str, arguments: dict[str, Any] | None = None, request_id: int = 1) -> str:
    return mcp_adapter_request(
        "tools/call",
        {
            "name": tool_name,
            "arguments": arguments or {},
        },
        request_id=request_id,
    )


def parse_json_object_from_output(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    stripped = text.strip()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _contains_json_rpc_error(command: CommandRun | None) -> bool:
    if not command:
        return False
    parsed = parse_json_object_from_output(command.stdout)
    if parsed:
        return bool(parsed.get("error"))
    return '"error"' in command.stdout.lower()


def check_mcp_public_ability_surfaces(source: Path, ability_name: str | None) -> dict[str, Any]:
    text = aggregate_artifact_text(source, suffixes={".php"})
    expected_ability = ability_name or ""
    checks = [
        _check_result(
            "mcp_smoke_ability_name",
            bool(expected_ability.strip()),
            f"ability selected for MCP smoke: {expected_ability}"
            if expected_ability.strip()
            else "--ability-name is required for MCP Adapter runtime smoke",
        ),
        _check_result(
            "mcp_public_meta_flag",
            "meta" in text and "mcp" in text and "public" in text,
            "ability registration includes meta.mcp.public"
            if "meta" in text and "mcp" in text and "public" in text
            else "default MCP server requires ability registration args with meta.mcp.public",
        ),
        _check_result(
            "mcp_public_ability_registered",
            bool(expected_ability and expected_ability in text and "wp_register_ability" in text),
            f"artifact registers {expected_ability} with wp_register_ability()"
            if expected_ability and expected_ability in text and "wp_register_ability" in text
            else "artifact must register the selected ability with wp_register_ability()",
        ),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "pass": status == "pass",
        "artifact_path": str(source.resolve()),
        "ability_name": ability_name,
        "checks": checks,
    }


def command_failed_because_mcp_unavailable(command: CommandRun | None) -> bool:
    if not command:
        return False
    haystack = f"{command.stdout}\n{command.stderr}".lower()
    return any(
        marker in haystack
        for marker in (
            "mcp-adapter",
            "not a registered wp command",
            "plugin could not be found",
            "failed to download",
            "could not create directory",
            "timed out",
        )
    )


def mcp_adapter_runtime_gate(
    *,
    requested: bool,
    static_gate: dict[str, Any] | None,
    install: CommandRun | None,
    list_servers: CommandRun | None,
    tools_list: CommandRun | None,
    discover: CommandRun | None,
    execute: CommandRun | None,
    ability_name: str | None,
    expected_output: str | None,
) -> dict[str, Any] | None:
    if not requested:
        return None
    checks: list[dict[str, str]] = []
    if static_gate:
        checks.append(
            _check_result(
                "mcp_static_public_ability",
                static_gate.get("status") == "pass",
                "artifact declares an MCP-public ability"
                if static_gate.get("status") == "pass"
                else "artifact must declare a selected ability with meta.mcp.public before runtime MCP exposure can be claimed",
            )
        )
    else:
        checks.append(_check_result("mcp_static_public_ability", False, "MCP static gate was not run"))

    install_ok = bool(install and install.ok)
    checks.append(
        _check_result(
            "mcp_adapter_install",
            install_ok,
            "MCP Adapter plugin installed and activated"
            if install_ok
            else "MCP Adapter plugin could not be installed or activated",
        )
    )

    list_ok = bool(list_servers and list_servers.ok and "mcp-adapter-default-server" in list_servers.stdout)
    checks.append(
        _check_result(
            "mcp_adapter_default_server",
            list_ok,
            "wp mcp-adapter list exposes mcp-adapter-default-server"
            if list_ok
            else "wp mcp-adapter list must expose mcp-adapter-default-server",
        )
    )

    tools_text = tools_list.stdout if tools_list else ""
    tools_ok = bool(
        tools_list
        and tools_list.ok
        and not _contains_json_rpc_error(tools_list)
        and all(
            tool_name in tools_text
            for tool_name in (
                "mcp-adapter-discover-abilities",
                "mcp-adapter-get-ability-info",
                "mcp-adapter-execute-ability",
            )
        )
    )
    checks.append(
        _check_result(
            "mcp_tools_list",
            tools_ok,
            "tools/list exposes the MCP Adapter discovery, info, and execute tools"
            if tools_ok
            else "tools/list must expose mcp-adapter-discover-abilities, mcp-adapter-get-ability-info, and mcp-adapter-execute-ability",
        )
    )

    discover_text = discover.stdout if discover else ""
    discover_ok = bool(
        discover
        and discover.ok
        and not _contains_json_rpc_error(discover)
        and ability_name
        and ability_name in discover_text
    )
    checks.append(
        _check_result(
            "mcp_discover_public_ability",
            discover_ok,
            f"mcp-adapter-discover-abilities lists {ability_name}"
            if discover_ok
            else f"mcp-adapter-discover-abilities must list {ability_name}",
        )
    )

    execute_text = execute.stdout if execute else ""
    expected_ok = not expected_output or expected_output in execute_text
    execute_ok = bool(execute and execute.ok and not _contains_json_rpc_error(execute) and expected_ok)
    checks.append(
        _check_result(
            "mcp_execute_public_ability",
            execute_ok,
            "mcp-adapter-execute-ability executed the public ability"
            if execute_ok
            else "mcp-adapter-execute-ability must execute the public ability through STDIO transport",
        )
    )

    if static_gate and static_gate.get("status") != "pass":
        status = "fail"
    elif install and not install.ok and command_failed_because_mcp_unavailable(install):
        status = "blocked"
    elif any(
        command and not command.ok and command_failed_because_mcp_unavailable(command)
        for command in (list_servers, tools_list, discover, execute)
    ):
        status = "blocked"
    else:
        status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "pass": status == "pass",
        "ability_name": ability_name,
        "expected_output": expected_output,
        "checks": checks,
    }


def mcp_adapter_smoke_status(gate: dict[str, Any] | None) -> str:
    if gate is None:
        return "not_run"
    return str(gate.get("status", "fail"))


def _php_global_function_name(function_name: str) -> str:
    return function_name.lstrip("\\").split("\\")[-1]


def check_ai_client_provider_surfaces(
    source: Path,
    provider_id: str | None,
    model_id: str | None,
    helper_function: str | None,
) -> dict[str, Any]:
    text = aggregate_artifact_text(source, suffixes={".php"})
    lower = text.lower()
    helper_basename = _php_global_function_name(helper_function or "")
    checks = [
        _check_result(
            "ai_client_provider_id",
            bool(provider_id and provider_id in text),
            f"artifact names AI Client provider {provider_id}"
            if provider_id and provider_id in text
            else "--ai-client-provider-id must be present in the artifact",
        ),
        _check_result(
            "ai_client_model_id",
            bool(model_id and model_id in text),
            f"artifact names AI Client model {model_id}"
            if model_id and model_id in text
            else "--ai-client-model-id must be present in the artifact",
        ),
        _check_result(
            "ai_client_prompt_helper",
            "wp_ai_client_prompt" in lower and "generate_text" in lower and "using_model_preference" in lower,
            "artifact calls wp_ai_client_prompt() through using_model_preference() and generate_text()"
            if "wp_ai_client_prompt" in lower and "generate_text" in lower and "using_model_preference" in lower
            else "artifact must call wp_ai_client_prompt() through using_model_preference() and generate_text()",
        ),
        _check_result(
            "ai_client_error_boundary",
            "is_wp_error" in lower and ("current_user_can" in lower or "wp_ai_client_prevent_prompt" in lower),
            "AI Client call handles WP_Error and has a capability or prompt-prevention boundary"
            if "is_wp_error" in lower and ("current_user_can" in lower or "wp_ai_client_prevent_prompt" in lower)
            else "AI Client call must handle WP_Error and enforce a capability or prompt-prevention boundary",
        ),
        _check_result(
            "ai_client_provider_registered",
            "aiclient::defaultregistry" in lower and "registerprovider" in lower,
            "artifact registers a provider through AiClient::defaultRegistry()->registerProvider()"
            if "aiclient::defaultregistry" in lower and "registerprovider" in lower
            else "artifact must register a provider through AiClient::defaultRegistry()->registerProvider()",
        ),
        _check_result(
            "ai_client_provider_interfaces",
            "providerinterface" in lower and "textgenerationmodelinterface" in lower,
            "artifact implements ProviderInterface and TextGenerationModelInterface"
            if "providerinterface" in lower and "textgenerationmodelinterface" in lower
            else "artifact must implement ProviderInterface and TextGenerationModelInterface for deterministic provider proof",
        ),
        _check_result(
            "ai_client_helper_function",
            bool(helper_basename and f"function {helper_basename.lower()}" in lower),
            f"artifact defines helper function {helper_function}"
            if helper_basename and f"function {helper_basename.lower()}" in lower
            else "--ai-client-helper-function must name a generated helper function",
        ),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "pass": status == "pass",
        "artifact_path": str(source.resolve()),
        "provider_id": provider_id,
        "model_id": model_id,
        "helper_function": helper_function,
        "checks": checks,
    }


def ai_client_provider_call_eval(
    *,
    provider_id: str,
    model_id: str,
    helper_function: str,
    prompt: str,
) -> str:
    return f"""
$result = array(
    'provider_id'             => {json.dumps(provider_id)},
    'model_id'                => {json.dumps(model_id)},
    'helper_function'         => {json.dumps(helper_function)},
    'wp_ai_client_prompt'     => function_exists( 'wp_ai_client_prompt' ),
    'ai_client_registry'      => class_exists( 'WordPress\\\\AiClient\\\\AiClient' ),
    'provider_registered'     => false,
    'provider_configured'     => false,
    'connector_registered'    => null,
    'output'                  => null,
);
if ( ! $result['wp_ai_client_prompt'] || ! $result['ai_client_registry'] ) {{
    echo wp_json_encode( $result );
    exit( 12 );
}}
$registry = WordPress\\AiClient\\AiClient::defaultRegistry();
$result['provider_registered'] = $registry->hasProvider( {json.dumps(provider_id)} );
$result['provider_configured'] = $registry->isProviderConfigured( {json.dumps(provider_id)} );
if ( function_exists( 'wp_is_connector_registered' ) ) {{
    $result['connector_registered'] = wp_is_connector_registered( {json.dumps(provider_id)} );
}}
if ( ! function_exists( {json.dumps(helper_function)} ) ) {{
    $result['helper_missing'] = true;
    echo wp_json_encode( $result );
    exit( 13 );
}}
$output = call_user_func( {json.dumps(helper_function)}, {json.dumps(prompt)} );
if ( is_wp_error( $output ) ) {{
    $result['wp_error_code']    = $output->get_error_code();
    $result['wp_error_message'] = $output->get_error_message();
    echo wp_json_encode( $result );
    exit( 14 );
}}
$result['output'] = (string) $output;
echo wp_json_encode( $result );
"""


def command_failed_because_ai_client_unavailable(command: CommandRun | None) -> bool:
    if not command:
        return False
    haystack = f"{command.stdout}\n{command.stderr}".lower()
    return any(
        marker in haystack
        for marker in (
            "wp_ai_client_prompt",
            "wordpress\\aiclient\\aiclient",
            "ai client is unavailable",
            "not a registered wp command",
            "timed out",
        )
    )


def ai_client_provider_call_gate(
    *,
    requested: bool,
    static_gate: dict[str, Any] | None,
    command: CommandRun | None,
    provider_id: str | None,
    model_id: str | None,
    helper_function: str | None,
    expected_output: str | None,
) -> dict[str, Any] | None:
    if not requested:
        return None
    parsed = parse_json_object_from_output(command.stdout if command else "")
    checks: list[dict[str, str]] = []
    checks.append(
        _check_result(
            "ai_client_static_provider_surface",
            bool(static_gate and static_gate.get("status") == "pass"),
            "artifact declares a deterministic AI Client provider and helper"
            if static_gate and static_gate.get("status") == "pass"
            else "artifact must declare a deterministic AI Client provider and helper",
        )
    )
    checks.append(
        _check_result(
            "ai_client_command_completed",
            bool(command and command.ok),
            "AI Client runtime command completed"
            if command and command.ok
            else "AI Client runtime command must complete",
        )
    )
    checks.append(
        _check_result(
            "ai_client_output_json",
            isinstance(parsed, dict),
            "AI Client runtime command emitted JSON evidence"
            if isinstance(parsed, dict)
            else "AI Client runtime command must emit JSON evidence",
        )
    )
    checks.append(
        _check_result(
            "ai_client_core_available",
            bool(parsed and parsed.get("wp_ai_client_prompt") and parsed.get("ai_client_registry")),
            "WordPress AI Client prompt and provider registry are available"
            if parsed and parsed.get("wp_ai_client_prompt") and parsed.get("ai_client_registry")
            else "WordPress AI Client prompt and provider registry must be available",
        )
    )
    checks.append(
        _check_result(
            "ai_client_provider_registered",
            bool(parsed and parsed.get("provider_registered")),
            f"provider {provider_id} is registered"
            if parsed and parsed.get("provider_registered")
            else f"provider {provider_id} must be registered",
        )
    )
    checks.append(
        _check_result(
            "ai_client_provider_configured",
            bool(parsed and parsed.get("provider_configured")),
            f"provider {provider_id} is configured"
            if parsed and parsed.get("provider_configured")
            else f"provider {provider_id} must be configured",
        )
    )
    checks.append(
        _check_result(
            "ai_client_connector_registered",
            bool(parsed and parsed.get("connector_registered")),
            f"connector {provider_id} is registered"
            if parsed and parsed.get("connector_registered")
            else f"connector {provider_id} must be registered",
        )
    )
    output = str(parsed.get("output", "")) if isinstance(parsed, dict) else ""
    expected_ok = not expected_output or expected_output in output
    checks.append(
        _check_result(
            "ai_client_provider_output",
            bool(output and expected_ok),
            f"helper {helper_function} returned expected provider output"
            if output and expected_ok
            else f"helper {helper_function} must return expected provider output",
        )
    )
    if static_gate and static_gate.get("status") != "pass":
        status = "fail"
    elif command and not command.ok and command_failed_because_ai_client_unavailable(command):
        status = "blocked"
    else:
        status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "pass": status == "pass",
        "provider_id": provider_id,
        "model_id": model_id,
        "helper_function": helper_function,
        "expected_output": expected_output,
        "evidence": parsed,
        "checks": checks,
    }


def ai_client_smoke_status(gate: dict[str, Any] | None) -> str:
    if gate is None:
        return "not_run"
    return str(gate.get("status", "fail"))


def block_registration_eval(block_name: str) -> str:
    return f"""
$registry = WP_Block_Type_Registry::get_instance();
$block = $registry->get_registered( {json.dumps(block_name)} );
if ( ! $block ) {{
    fwrite( STDERR, 'block not registered: {block_name}' );
    exit( 4 );
}}
echo wp_json_encode(
    array(
        'name'       => $block->name,
        'title'      => $block->title,
        'category'   => $block->category,
        'renderable' => is_callable( $block->render_callback ),
    )
);
"""


def block_deprecation_post_eval(old_content: str) -> str:
    return f"""
$post_id = wp_insert_post(
    array(
        'post_title'   => 'Deprecated Block Runtime Smoke',
        'post_content' => {json.dumps(old_content)},
        'post_status'  => 'draft',
        'post_author'  => 1,
    ),
    true
);
if ( is_wp_error( $post_id ) ) {{
    fwrite( STDERR, $post_id->get_error_message() );
    exit( 5 );
}}
echo wp_json_encode( array( 'postId' => (int) $post_id ) );
"""


def parse_block_deprecation_post_id(command: CommandRun | None) -> int | None:
    if not command or not command.ok:
        return None
    try:
        data = json.loads(command.stdout.strip())
    except json.JSONDecodeError:
        return None
    post_id = data.get("postId") if isinstance(data, dict) else None
    return int(post_id) if isinstance(post_id, int) and post_id > 0 else None


def block_smoke_status(command: CommandRun | None) -> str:
    if command is None:
        return "not_run"
    if command.ok:
        return "pass"
    if "block not registered" in command.stderr:
        return "fail"
    return "fail"


def editor_smoke_status(command: CommandRun | None) -> str:
    if command is None:
        return "not_run"
    if command.returncode == 127:
        return "blocked"
    if command.ok:
        return "pass"
    return "fail"


def interactivity_smoke_status(command: CommandRun | None, requested: bool, static_gate: dict[str, Any] | None) -> str:
    if not requested:
        return "not_run"
    if not static_gate:
        return "fail"
    if static_gate.get("status") != "pass":
        return str(static_gate.get("status", "fail"))
    return editor_smoke_status(command)


def block_deprecation_smoke_status(
    command: CommandRun | None,
    requested: bool,
    static_gate: dict[str, Any] | None,
    post_command: CommandRun | None,
) -> str:
    if not requested:
        return "not_run"
    if not static_gate:
        return "fail"
    if static_gate.get("status") != "pass":
        return str(static_gate.get("status", "fail"))
    if not post_command or not post_command.ok or parse_block_deprecation_post_id(post_command) is None:
        return "fail"
    return editor_smoke_status(command)


def artifact_check_status(profile: dict[str, Any] | None, check_id: str) -> str:
    for check in (profile or {}).get("checks", []):
        if check.get("id") == check_id:
            return str(check.get("status", "not_run"))
    return "not_run"


def gate_status(gate: dict[str, Any] | None) -> str:
    if gate is None:
        return "not_run"
    return str(gate.get("status", "not_run"))


def oracle_args(
    *,
    profile: str,
    require_tool: list[str] | None,
    timeout_sec: int,
    wp_env_root: Path | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        profile=profile,
        require_tool=require_tool or [],
        timeout_sec=timeout_sec,
        wp_root=None,
        wp_env_root=str(wp_env_root) if wp_env_root else None,
        plugin_check_require=None,
    )


def _generated_build_gate(build, output_gate):
    check = {
        "id": "npm_build",
        "status": build.status,
        "required": True,
        "detail": build.detail,
        "command": list(build.command),
    }
    checks = [check]
    if output_gate is not None:
        checks.extend(output_gate.get("checks", []))
    statuses = {item.get("status") for item in checks if item.get("required", True)}
    status = "blocked" if "blocked" in statuses else "fail" if "fail" in statuses else "pass"
    return {
        "status": status,
        "pass": status == "pass",
        "checks": checks,
        "sandbox_posture": {"generated_execution": build.status, "host_fallback": False},
        "post_build_validation": output_gate,
    }


def _wrapped_runtime(prepared, effective):
    relative = prepared.block_relative or Path()
    plugin = prepared.plugin_dir
    return WrappedBlockArtifact(
        plugin,
        plugin / "generated",
        effective.root / relative,
        plugin / "generated" / relative,
        prepared.block_name or "",
        prepared.textdomain or prepared.plugin_slug,
    )


def _merged_receipts(*groups):
    merged=[]
    for group in groups:
        for receipt in group:
            if receipt not in merged: merged.append(receipt)
    return merged


def _prepare_phpunit(staged, artifact_kind, requested, timeout_sec):
    if not requested:
        return None, []
    if artifact_kind != "plugin":
        raise ValueError("artifact-local PHPUnit is supported only for plugin artifacts")
    gate=validate_wordpress_artifact.validate_staged_artifact(
        "plugin",staged,
        oracle_args(profile="static",require_tool=["phpunit"],
                    timeout_sec=timeout_sec,wp_env_root=None),
        _defer_retention=True,
    )
    return gate,gate.pop("_artifact_retention_receipts", [])


def _prepare_block_build(staged, artifact_kind, requested, timeout_sec):
    if artifact_kind != "block" or not requested:
        return staged,None,None,[]
    build=runtime_artifact_pipeline.build_block(staged,timeout_sec)
    output=build.output; output_gate=None
    receipts=[
        runtime_artifact_pipeline.cleanup_receipt_from_staging("sandbox_output",receipt)
        for receipt in build.staging_cleanup_receipts
    ]
    if output is not None:
        output_gate=validate_wordpress_artifact.validate_staged_artifact(
            "block",output,oracle_args(
                profile="static",require_tool=[],timeout_sec=timeout_sec,wp_env_root=None,
            ),
        )
    return output or staged,output,_generated_build_gate(build,output_gate),receipts


def _synthesize_runtime(staged, effective, artifact_kind, source_path, parent):
    if artifact_kind == "block":
        synthesized=runtime_artifact_pipeline.synthesize_block_runtime(effective,parent)
        return synthesized,_wrapped_runtime(synthesized,effective)
    claimed=source_path.name if source_path is not None else "generated-plugin"
    return runtime_artifact_pipeline.synthesize_plugin_runtime(staged,claimed,parent),None


def _prepare_wpcs(synthesized, requested, timeout_sec, _temp_root):
    if not requested:
        return None,{},[]
    toolchain, reason = wp_security_gate.resolve_toolchain(PHP_TOOLS_ROOT)
    provisioning = {"phpcs_wpcs_toolchain": {
        "status": "pass" if toolchain else "blocked",
        "root": str(PHP_TOOLS_ROOT),
        "lockfile": str(PHP_TOOLS_ROOT / "composer.lock"),
        "network": "not attempted during artifact validation",
        "detail": reason,
    }}
    if toolchain is None:
        gate={"status":"blocked","pass":False,"checks":[{
            "id":"phpcs_wpcs","status":"blocked","required":True,
            "detail": reason or "pinned WPCS toolchain is unavailable",
        }]}
        return gate,provisioning,[]
    gate=validate_wordpress_artifact.validate_staged_artifact(
        "plugin",synthesized.staged,
        oracle_args(profile="static",require_tool=["wpcs"],
                    timeout_sec=timeout_sec,wp_env_root=PHP_TOOLS_ROOT),
        subpath=Path(synthesized.plugin_slug),_defer_retention=True,
    )
    return gate,provisioning,gate.pop("_artifact_retention_receipts", [])


def _prepare_generated_runtime(
    staged, artifact_kind, source_path, build_requested, phpunit_requested,
    full_profile_requested, timeout_sec, parent, temp_root,
):
    output=None; synthesized=None; preparation_receipts=[]
    try:
        phpunit_gate,receipts=_prepare_phpunit(
            staged,artifact_kind,phpunit_requested,timeout_sec,
        ); preparation_receipts.extend(receipts)
        effective,output,build_gate,receipts=_prepare_block_build(
            staged,artifact_kind,build_requested,timeout_sec,
        ); preparation_receipts.extend(receipts)
        synthesized,wrapped=_synthesize_runtime(
            staged,effective,artifact_kind,source_path,parent,
        )
        wpcs_gate,provisioning,receipts=_prepare_wpcs(
            synthesized,full_profile_requested,timeout_sec,temp_root,
        ); preparation_receipts.extend(receipts)
        return PreparedRuntimeArtifact(
            synthesized,effective if artifact_kind=="block" else None,output,build_gate,phpunit_gate,
            wpcs_gate,provisioning,wrapped,
            tuple(preparation_receipts),
        )
    except runtime_artifact_pipeline.RuntimePreparationError as exc:
        receipts=_merged_receipts(
            preparation_receipts,exc.receipts,runtime_artifact_pipeline.cleanup_preparation(None,output)
        )
        raise runtime_artifact_pipeline.RuntimePreparationError(exc.primary,receipts) from exc
    except Exception as exc:
        receipts=_merged_receipts(
            preparation_receipts,runtime_artifact_pipeline.cleanup_preparation(synthesized,output)
        )
        raise runtime_artifact_pipeline.RuntimePreparationError(exc,receipts) from exc


def _preparation_failure_result(error, artifact_kind, temp_root, build_requested, phpunit_requested, retained):
    checks=[{"id":"artifact_preparation","status":"blocked","required":True,"detail":str(error)}]
    for receipt in error.receipts:
        if receipt.state!="removed" or receipt.error:
            checks.append({"id":f"{receipt.component}_cleanup","status":"blocked","required":True,"detail":receipt.error or f"{receipt.component} remains {receipt.state}"})
    return {
        "status":"blocked","pass":False,"artifact_kind":artifact_kind,
        "runtime_root":str(temp_root),"fixture_root":str(temp_root),"fixture_retained":retained,
        "block_build_smoke_requested":build_requested,"block_build_smoke_status":"blocked" if build_requested else "not_run",
        "phpunit_smoke_requested":phpunit_requested,
        "phpunit_smoke_status":"blocked" if phpunit_requested else "not_run",
        "checks":checks,"negative_space":list(BASE_NEGATIVE_SPACE),
        "_artifact_retention_receipts":list(error.receipts),
    }


def _release_prepared_runtime(prepared, hold_context, retain_synthesized):
    receipts = []
    hold_error = None
    if hold_context is not None:
        try:
            hold_context.__exit__(None, None, None)
        except Exception as exc:
            hold_error = f"{type(exc).__name__}: held runtime proof changed"
    if prepared is None:
        return receipts
    receipts.extend(prepared.preparation_receipts)
    synthesized = prepared.synthesized.staged
    receipt = (
        runtime_artifact_pipeline.observe_component("synthesized_runtime", synthesized)
        if retain_synthesized
        else runtime_artifact_pipeline.cleanup_component("synthesized_runtime", synthesized)
    )
    if hold_error and receipt.error is None:
        receipt = runtime_artifact_pipeline.CleanupReceipt(
            receipt.component, receipt.state, receipt.exists, receipt.live, receipt.recovery_path, hold_error, receipt.resource_path
        )
    receipts.append(receipt)
    if prepared.sandbox_output is not None:
        receipts.append(runtime_artifact_pipeline.cleanup_component("sandbox_output", prepared.sandbox_output))
    return _merged_receipts(receipts)


def _generated_runtime_unsupported(kwargs):
    fields={
        "ability_name":"ability-oracle",
        "editor_smoke":"legacy-editor-oracle",
        "editor_insert_render_smoke":"legacy-editor-oracle",
        "interactivity_smoke":"legacy-editor-oracle",
        "block_deprecation_smoke":"legacy-editor-oracle",
        "mcp_adapter_smoke":"mcp-adapter",
        "ai_client_smoke":"ai-client",
    }
    return sorted({label for field,label in fields.items() if kwargs.get(field)})


def _blocked_isolated_result(detail,digest,receipts=(),requested=None):
    requested=requested or {}
    result={
        "status":"blocked","pass":False,"reason":detail,"checks":[],
        "artifact_kind":requested.get("artifact_kind","plugin"),
        "input_artifact_digest":digest,"negative_space":[*BASE_NEGATIVE_SPACE,"isolated runtime not executed"],
        "sandbox_posture":{"host_fallback":False,"generated_execution":"blocked"},
        "block_build_smoke_requested":bool(requested.get("block_build_smoke")),
        "phpunit_smoke_requested":bool(requested.get("phpunit_smoke")),
        "_artifact_retention_receipts":list(receipts),
    }
    fields={"ability_name":"ability_smoke_status","editor_smoke":"editor_smoke_status",
        "editor_insert_render_smoke":"editor_smoke_status","interactivity_smoke":"interactivity_smoke_status",
        "block_deprecation_smoke":"block_deprecation_smoke_status","block_build_smoke":"block_build_smoke_status",
        "phpunit_smoke":"phpunit_smoke_status","mcp_adapter_smoke":"mcp_adapter_smoke_status",
        "ai_client_smoke":"ai_client_smoke_status"}
    for field,status in fields.items():
        if requested.get(field): result[status]="blocked"
    if requested.get("block_deprecation_smoke"): result["editor_smoke_status"]="blocked"
    return result


def _isolated_result_payload(runtime,request,prepared,artifact_kind,kwargs,receipts):
    expected_manifest=artifact_staging.manifest_sha256(prepared.synthesized.staged.manifest)
    result=isolated_runtime_contract.adapt_runtime_result(
        runtime,request,artifact_kind=artifact_kind,expected_manifest_digest=expected_manifest,
        block_build_requested=bool(kwargs.get("block_build_smoke")),
        block_build_gate=prepared.block_build_gate,
        phpunit_requested=bool(kwargs.get("phpunit_smoke")),
        phpunit_gate=prepared.phpunit_gate,
        full_profile_requested=bool(
            kwargs.get("provision_full_profile") or kwargs.get("strict_full_profile")
        ),
        wpcs_gate=prepared.wpcs_gate,
        trusted_provisioning=prepared.trusted_provisioning,
    )
    result["_artifact_retention_receipts"]=list(receipts)
    return result


def _run_isolated_smoke_input(staged,evidence_id,kwargs):
    digest=artifact_staging.digest_manifest_tree(staged.manifest)
    expected=kwargs.get("expected_artifact_digest")
    artifact_kind=kwargs.get("artifact_kind","plugin")
    lease=create_ephemeral(kwargs.get("workdir"),WorkspacePurpose.RUNTIME); prepared=None; terminal=None
    try:
        prepared=_prepare_generated_runtime(
            staged,artifact_kind,kwargs.get("artifact_source_path"),
            kwargs.get("block_build_smoke",False),kwargs.get("phpunit_smoke",False),
            kwargs.get("provision_full_profile",False) or kwargs.get("strict_full_profile",False),
            kwargs["timeout_sec"],lease.root.parent,lease.root/"trusted-wpcs",
        )
        unsupported=_generated_runtime_unsupported(kwargs)
        if unsupported: raise ValueError("unpinned optional runtime support is blocked: "+", ".join(unsupported))
        if expected != digest: raise ValueError("generated runtime requires the exact Plan 008 artifact digest")
        if not evidence_id: raise ValueError("generated runtime requires the Plan 008 evidence ID")
        build_status=(prepared.block_build_gate or {}).get("status")
        if kwargs.get("block_build_smoke") and build_status != "pass":
            terminal=isolated_runtime_contract.stopped_build_result(
                artifact_kind=artifact_kind,digest=digest,gate=prepared.block_build_gate or {},
                receipts=[],phpunit_requested=bool(kwargs.get("phpunit_smoke")),
            )
            runtime=request=None
        else:
            request=RuntimeRequest(prepared.synthesized.staged,prepared.synthesized.plugin_slug,evidence_id,
                digest,expected,kwargs["timeout_sec"],lease.root.parent)
            runtime=wp_env_network_guard.run_staged_runtime(request)
            if not isinstance(runtime,RuntimeResult): raise TypeError("isolated runtime returned an invalid result")
    except runtime_artifact_pipeline.RuntimePreparationError as exc:
        cleanup_workspace(lease,repository_root=ROOT)
        return _preparation_failure_result(exc,artifact_kind,lease.root,
            kwargs.get("block_build_smoke",False),kwargs.get("phpunit_smoke",False),False)
    except (TypeError,ValueError,RuntimeError,OSError) as exc:
        runtime=None; detail=f"{type(exc).__name__}: {exc}"
    receipts=_release_prepared_runtime(prepared,None,False)
    if terminal is not None: terminal["_artifact_retention_receipts"]=list(receipts)
    try: cleanup_workspace(lease,repository_root=ROOT)
    except WorkspaceCleanupError as exc: return _blocked_isolated_result(f"runtime workspace cleanup: {exc}",digest,receipts,kwargs)
    if terminal is not None: return terminal
    return _isolated_result_payload(runtime,request,prepared,artifact_kind,kwargs,receipts) if runtime else _blocked_isolated_result(detail,digest,receipts,kwargs)


def _required_status(value: str) -> str:
    return value if value in {"pass","fail","blocked"} else "fail"


def _dominant_status(statuses: list[str]) -> str:
    if "blocked" in statuses: return "blocked"
    if "fail" in statuses: return "fail"
    return "pass"


def status_from_gates(
    *,
    npx: str | None, provision_full_profile: bool, provisioning: dict[str, CommandRun],
    start: CommandRun | None, activation: CommandRun | None,
    narrow_gate: dict[str, Any] | None, full_profile: dict[str, Any] | None,
    ability_smoke: CommandRun | None, block_smoke: CommandRun | None, editor_smoke: CommandRun | None,
    interactivity_static_gate: dict[str, Any] | None, interactivity_smoke: bool,
    block_deprecation_static_gate: dict[str, Any] | None, block_deprecation_smoke: bool,
    block_deprecation_post: CommandRun | None, block_build_gate: dict[str, Any] | None,
    block_build_smoke: bool, phpunit_gate: dict[str, Any] | None, phpunit_smoke: bool,
    mcp_adapter_gate: dict[str, Any] | None, mcp_adapter_smoke: bool,
    ai_client_gate: dict[str, Any] | None, ai_client_smoke: bool,
    stop: CommandRun | None, strict_full_profile: bool,
) -> str:
    require_full_profile = strict_full_profile or provision_full_profile
    statuses=[]
    if provision_full_profile and any(not command.ok for command in provisioning.values()):
        statuses.append("blocked")
    if block_build_smoke:
        statuses.append(_required_status(gate_status(block_build_gate)))
    interactivity_status = interactivity_smoke_status(editor_smoke, interactivity_smoke, interactivity_static_gate)
    if interactivity_smoke: statuses.append(_required_status(interactivity_status))
    deprecation_status = block_deprecation_smoke_status(
        editor_smoke,
        block_deprecation_smoke,
        block_deprecation_static_gate,
        block_deprecation_post,
    )
    if block_deprecation_smoke: statuses.append(_required_status(deprecation_status))
    if not npx: statuses.append("blocked")
    if not start or not start.ok: statuses.append("blocked")
    if not activation or not activation.ok: statuses.append("fail")
    ability_status = ability_smoke_status(ability_smoke)
    if ability_smoke is not None: statuses.append(_required_status(ability_status))
    if block_smoke is not None: statuses.append(_required_status(block_smoke_status(block_smoke)))
    if phpunit_smoke:
        statuses.append(_required_status(gate_status(phpunit_gate)))
    if mcp_adapter_smoke:
        statuses.append(_required_status(mcp_adapter_smoke_status(mcp_adapter_gate)))
    if ai_client_smoke:
        statuses.append(_required_status(ai_client_smoke_status(ai_client_gate)))
    if editor_smoke is not None: statuses.append(_required_status(editor_smoke_status(editor_smoke)))
    statuses.append(_required_status(gate_status(narrow_gate)))
    if require_full_profile: statuses.append(_required_status(gate_status(full_profile)))
    if stop and not stop.ok: statuses.append("blocked")
    return _dominant_status(statuses)


@stage_runtime_input
def run_smoke(
    *,
    timeout_sec: int,
    workdir: Path | None = None,
    artifact_path: Path | None = None,
    staged_artifact: artifact_staging.StagedTree | None = None,
    artifact_source_path: Path | None = None,
    artifact_kind: str = "plugin",
    expected_artifact_digest: str | None = None,
    keep_artifacts: bool = False,
    keep_running: bool = False,
    provision_full_profile: bool = False,
    strict_full_profile: bool = False,
    ability_name: str | None = None,
    execute_post_summary_ability: bool = False,
    block_name: str | None = None,
    fixture_kind: str = "plugin",
    editor_smoke: bool = False,
    editor_insert_render_smoke: bool = False,
    interactivity_smoke: bool = False,
    block_deprecation_smoke: bool = False,
    block_build_smoke: bool = False,
    phpunit_smoke: bool = False,
    mcp_adapter_smoke: bool = False,
    mcp_adapter_execute_args: dict[str, Any] | None = None,
    mcp_adapter_expected_output: str | None = None,
    ai_client_smoke: bool = False,
    ai_client_provider_id: str | None = None,
    ai_client_model_id: str | None = None,
    ai_client_helper_function: str | None = None,
    ai_client_prompt: str = "Runtime AI Client smoke",
    ai_client_expected_output: str | None = None,
) -> dict[str, Any]:
    editor_smoke = editor_smoke or editor_insert_render_smoke or block_deprecation_smoke
    if interactivity_smoke and not editor_insert_render_smoke:
        raise ValueError("interactivity_smoke requires editor_insert_render_smoke")
    if artifact_kind not in {"plugin", "block"}:
        raise ValueError(f"unsupported artifact_kind: {artifact_kind}")
    lease = create_ephemeral(workdir, WorkspacePurpose.RUNTIME)
    temp_root = lease.root
    cleanup_error: str | None = None
    wrapped_block_artifact: WrappedBlockArtifact | None = None
    source_block_artifact_path: Path | None = None
    prepared_artifact: PreparedRuntimeArtifact | None = None
    prepared_hold = None
    prepared_hold_context = None
    artifact_retention_receipts = []
    try:
        if staged_artifact is not None:
            stage_parent = lease.caller_parent or temp_root.parent
            prepared_artifact = _prepare_generated_runtime(
                staged_artifact, artifact_kind, artifact_source_path, block_build_smoke,
                phpunit_smoke, timeout_sec, stage_parent
            )
            prepared_hold_context = artifact_staging.hold_staged_tree(prepared_artifact.synthesized.staged)
            prepared_hold = prepared_hold_context.__enter__()
            plugin_dir = prepared_artifact.synthesized.plugin_dir
            write_wp_env_config(temp_root, str(plugin_dir))
            if artifact_kind == "block":
                wrapped_block_artifact = prepared_artifact.wrapped
                source_block_artifact_path = wrapped_block_artifact.copied_artifact_dir
                block_name = block_name or wrapped_block_artifact.block_name
        elif fixture_kind == "block":
            plugin_dir = write_block_runtime_fixture(temp_root)
            block_name = block_name or "acme/runtime-card"
        else:
            plugin_dir = write_runtime_fixture(temp_root)
    except runtime_artifact_pipeline.RuntimePreparationError as setup_error:
        retained=keep_artifacts or keep_running; cleanup_detail=None
        if not retained:
            try: cleanup_workspace(lease,repository_root=ROOT)
            except WorkspaceCleanupError as cleanup_failure: cleanup_detail=str(cleanup_failure); retained=True
        result=_preparation_failure_result(setup_error,artifact_kind,temp_root,block_build_smoke,phpunit_smoke,retained)
        if cleanup_detail:
            result["checks"].append({"id":"runtime_workspace_cleanup","status":"blocked","required":True,"detail":cleanup_detail})
        return result
    except Exception as setup_error:
        artifact_retention_receipts.extend(_release_prepared_runtime(prepared_artifact, prepared_hold_context, False))
        prepared_hold_context = None
        if not keep_artifacts and not keep_running:
            try:
                cleanup_workspace(lease, repository_root=ROOT)
            except WorkspaceCleanupError as cleanup_failure:
                raise cleanup_failure from setup_error
        raise
    staged_artifact_digest = (
        artifact_staging.digest_manifest_tree(staged_artifact.manifest)
        if staged_artifact is not None
        else digest_regular_tree(plugin_dir)
    )
    if expected_artifact_digest and staged_artifact_digest != expected_artifact_digest:
        artifact_retention_receipts.extend(
            _release_prepared_runtime(prepared_artifact, prepared_hold_context, keep_artifacts or keep_running)
        )
        prepared_hold_context = None
        if not keep_artifacts and not keep_running:
            cleanup_workspace(lease, repository_root=ROOT)
        return {
            "status": "blocked", "pass": False, "artifact_kind": artifact_kind,
            "input_artifact_digest": staged_artifact_digest,
            "fixture_retained": keep_artifacts or keep_running,
            "runtime_root": str(temp_root), "workdir_parent": str(lease.caller_parent) if lease.caller_parent else None,
            "full_plugin_runtime_profile": {"status": "blocked", "checks": [{
                "id": "artifact_digest", "status": "blocked", "detail": "staged artifact digest mismatch"
            }]},
            "checks": [{"id": "artifact_digest", "status": "blocked", "detail": "staged artifact digest mismatch"}],
            "negative_space": list(BASE_NEGATIVE_SPACE),
            "_artifact_retention_receipts": artifact_retention_receipts,
        }
    try:
        npx = shutil.which("npx")
    except Exception as setup_error:
        if not keep_artifacts and not keep_running:
            try:
                cleanup_workspace(lease, repository_root=ROOT)
            except WorkspaceCleanupError as cleanup_failure:
                raise cleanup_failure from setup_error
        raise
    start: CommandRun | None = None
    activation: CommandRun | None = None
    stop: CommandRun | None = None
    ability_smoke: CommandRun | None = None
    block_smoke: CommandRun | None = None
    editor_smoke_run: CommandRun | None = None
    block_deprecation_post: CommandRun | None = None
    mcp_adapter_install: CommandRun | None = None
    mcp_adapter_list: CommandRun | None = None
    mcp_adapter_tools_list: CommandRun | None = None
    mcp_adapter_discover: CommandRun | None = None
    mcp_adapter_execute: CommandRun | None = None
    ai_client_call: CommandRun | None = None
    narrow_gate: dict[str, Any] | None = None
    block_gate: dict[str, Any] | None = None
    block_build_gate: dict[str, Any] | None = prepared_artifact.block_build_gate if prepared_artifact else None
    interactivity_static_gate: dict[str, Any] | None = None
    block_deprecation_static_gate: dict[str, Any] | None = None
    mcp_adapter_static_gate: dict[str, Any] | None = None
    mcp_adapter_gate: dict[str, Any] | None = None
    ai_client_static_gate: dict[str, Any] | None = None
    ai_client_gate: dict[str, Any] | None = None
    phpunit_gate: dict[str, Any] | None = None
    full_profile: dict[str, Any] | None = None
    provisioning: dict[str, CommandRun] = {}

    try:
        if block_build_smoke and block_build_gate is None:
            block_build_root = wrapped_block_artifact.copied_artifact_dir if wrapped_block_artifact else plugin_dir
            if staged_artifact is not None:
                block_build_gate = validate_wordpress_artifact.validate_staged_artifact(
                    "block",
                    staged_artifact,
                    oracle_args(
                        profile="static",
                        require_tool=["npm-build"],
                        timeout_sec=timeout_sec,
                        wp_env_root=temp_root,
                    ),
                    source_path=artifact_source_path,
                )
            else:
                block_build_gate = validate_wordpress_artifact.validate_artifact(
                    "block",
                    block_build_root,
                    oracle_args(
                        profile="static",
                        require_tool=["npm-build"],
                        timeout_sec=timeout_sec,
                        wp_env_root=temp_root,
                    ),
                )

        if interactivity_smoke:
            interactivity_path = (
                wrapped_block_artifact.copied_artifact_dir
                if wrapped_block_artifact
                else source_block_artifact_path or plugin_dir
            )
            interactivity_static_gate = check_block_interactivity_surfaces(interactivity_path)

        if block_deprecation_smoke:
            block_deprecation_path = (
                wrapped_block_artifact.copied_artifact_dir
                if wrapped_block_artifact
                else source_block_artifact_path or plugin_dir
            )
            block_deprecation_static_gate = check_block_deprecation_surfaces(block_deprecation_path)

        if mcp_adapter_smoke:
            mcp_adapter_static_gate = check_mcp_public_ability_surfaces(plugin_dir, ability_name)

        if ai_client_smoke:
            ai_client_static_gate = check_ai_client_provider_surfaces(
                plugin_dir,
                ai_client_provider_id,
                ai_client_model_id,
                ai_client_helper_function,
            )

        if provision_full_profile:
            toolchain, reason = wp_security_gate.resolve_toolchain(PHP_TOOLS_ROOT)
            if toolchain:
                provisioning["phpcs_wpcs_toolchain"] = run_command(
                    [toolchain.php, str(toolchain.phpcs), "--runtime-set", "installed_paths",
                     toolchain.installed_paths, "-i"],
                    PHP_TOOLS_ROOT, timeout_sec,
                )
            else:
                provisioning["phpcs_wpcs_toolchain"] = missing_command(
                    reason or "pinned WPCS toolchain", PHP_TOOLS_ROOT,
                )

        build_ready = not block_build_smoke or gate_status(block_build_gate) == "pass"
        if npx and build_ready:
            start = run_command([npx, "--yes", "@wordpress/env", "start", "--auto-port"], temp_root, timeout_sec)
            if start.ok:
                activation = run_command(wp_env_cli_command(npx, "plugin", "activate", plugin_dir.name), temp_root, timeout_sec)
                if provision_full_profile:
                    provisioning["plugin_check_install"] = run_command(
                        wp_env_cli_command(npx, "plugin", "install", "plugin-check", "--activate"),
                        temp_root,
                        timeout_sec,
                    )
                if activation.ok and mcp_adapter_smoke and mcp_adapter_static_gate and mcp_adapter_static_gate.get("status") == "pass":
                    mcp_adapter_install = run_command(
                        wp_env_cli_command(npx, "plugin", "install", MCP_ADAPTER_PLUGIN_ZIP, "--activate"),
                        temp_root,
                        timeout_sec,
                    )
                    if mcp_adapter_install.ok:
                        mcp_adapter_list = run_command(
                            wp_env_cli_command(npx, "mcp-adapter", "list"),
                            temp_root,
                            timeout_sec,
                        )
                        serve_command = wp_env_cli_command(
                            npx,
                            "mcp-adapter",
                            "serve",
                            "--user=admin",
                            "--server=mcp-adapter-default-server",
                        )
                        mcp_adapter_tools_list = run_command_with_input(
                            serve_command,
                            temp_root,
                            timeout_sec,
                            mcp_adapter_request("tools/list"),
                        )
                        mcp_adapter_discover = run_command_with_input(
                            serve_command,
                            temp_root,
                            timeout_sec,
                            mcp_adapter_tools_call_request("mcp-adapter-discover-abilities", {}),
                        )
                        if ability_name:
                            mcp_adapter_execute = run_command_with_input(
                                serve_command,
                                temp_root,
                                timeout_sec,
                                mcp_adapter_tools_call_request(
                                    "mcp-adapter-execute-ability",
                                    {
                                        "ability_name": ability_name,
                                        "parameters": mcp_adapter_execute_args or {},
                                    },
                                ),
                            )
                if (
                    activation.ok
                    and ai_client_smoke
                    and ai_client_static_gate
                    and ai_client_static_gate.get("status") == "pass"
                    and ai_client_provider_id
                    and ai_client_model_id
                    and ai_client_helper_function
                ):
                    ai_client_call = run_command(
                        wp_env_cli_command(
                            npx,
                            "--user=admin",
                            "eval",
                            ai_client_provider_call_eval(
                                provider_id=ai_client_provider_id,
                                model_id=ai_client_model_id,
                                helper_function=ai_client_helper_function,
                                prompt=ai_client_prompt,
                            ),
                        ),
                        temp_root,
                        timeout_sec,
                    )
                if activation.ok and ability_name:
                    eval_code = (
                        ability_post_summary_eval(ability_name)
                        if execute_post_summary_ability
                        else ability_registration_eval(ability_name)
                    )
                    ability_smoke = run_command(wp_env_cli_command(npx, "eval", eval_code), temp_root, timeout_sec)
                if activation.ok and block_name:
                    block_smoke = run_command(
                        wp_env_cli_command(npx, "eval", block_registration_eval(block_name)),
                        temp_root,
                        timeout_sec,
                    )
                    if block_deprecation_smoke and block_deprecation_static_gate and block_deprecation_static_gate.get("status") == "pass":
                        block_deprecation_post = run_command(
                            wp_env_cli_command(
                                npx,
                                "eval",
                                block_deprecation_post_eval(str(block_deprecation_static_gate.get("old_content", ""))),
                            ),
                            temp_root,
                            timeout_sec,
                        )
                    if editor_smoke:
                        site_url = parse_wp_env_site_url(start)
                        node = shutil.which("node")
                        if not site_url:
                            editor_smoke_run = CommandRun(
                                ["node", "evals/harness/run_wordpress_editor_smoke.js"],
                                str(temp_root),
                                127,
                                "",
                                "could not parse wp-env site URL from start output",
                                0.0,
                            )
                        elif not node:
                            editor_smoke_run = missing_command("node", temp_root)
                        else:
                            editor_command = [
                                node,
                                str(ROOT / "evals" / "harness" / "run_wordpress_editor_smoke.js"),
                                "--url",
                                site_url,
                                "--block-name",
                                block_name,
                                "--timeout-ms",
                                str(timeout_sec * 1000),
                            ]
                            if editor_insert_render_smoke:
                                editor_command.append("--insert-render-smoke")
                            if interactivity_smoke:
                                editor_command.append("--interactivity-smoke")
                            if block_deprecation_smoke:
                                post_id = parse_block_deprecation_post_id(block_deprecation_post)
                                if post_id:
                                    editor_command.extend(["--deprecation-smoke", "--post-id", str(post_id)])
                                    if block_deprecation_static_gate:
                                        editor_command.extend(
                                            [
                                                "--expected-migrated-text",
                                                str(block_deprecation_static_gate.get("expected_migrated_text", "")),
                                                "--expected-migrated-attribute-name",
                                                str(block_deprecation_static_gate.get("expected_migrated_attribute_name", "")),
                                                "--expected-migrated-attribute",
                                                str(block_deprecation_static_gate.get("expected_migrated_attribute", "")),
                                                "--expected-serialized-marker",
                                                str(block_deprecation_static_gate.get("expected_serialized_marker", "")),
                                            ]
                                        )
                            editor_smoke_run = run_command(
                                editor_command,
                                ROOT,
                                timeout_sec,
                            )
                narrow_args = oracle_args(
                    profile="static", require_tool=["php-lint", "wp-env"], timeout_sec=timeout_sec, wp_env_root=temp_root
                )
                if prepared_artifact is not None:
                    narrow_gate = validate_wordpress_artifact.validate_staged_artifact(
                        "plugin", prepared_artifact.synthesized.staged, narrow_args,
                        subpath=Path(prepared_artifact.synthesized.plugin_slug),
                    )
                else:
                    narrow_gate = validate_wordpress_artifact.validate_artifact("plugin", plugin_dir, narrow_args)
                if block_name:
                    block_gate_path = source_block_artifact_path or plugin_dir
                    block_args = oracle_args(
                        profile="static",
                        require_tool=["wp-env"],
                        timeout_sec=timeout_sec,
                        wp_env_root=temp_root,
                    )
                    if prepared_artifact is not None and artifact_kind == "block":
                        block_gate = validate_wordpress_artifact.validate_staged_artifact(
                            "block",
                            prepared_artifact.effective_block,
                            block_args,
                        )
                    else:
                        block_gate = validate_wordpress_artifact.validate_artifact(
                            "block",
                            block_gate_path,
                            block_args,
                        )
                if phpunit_smoke:
                    phpunit_args = oracle_args(
                        profile="static",
                        require_tool=["phpunit"],
                        timeout_sec=timeout_sec,
                        wp_env_root=temp_root,
                    )
                    if staged_artifact is not None and artifact_kind == "plugin":
                        phpunit_gate = validate_wordpress_artifact.validate_staged_artifact(
                            "plugin",
                            staged_artifact,
                            phpunit_args,
                            source_path=artifact_source_path,
                        )
                    else:
                        phpunit_gate = validate_wordpress_artifact.validate_artifact(
                            "plugin",
                            plugin_dir,
                            phpunit_args,
                        )
                full_args = oracle_args(
                    profile="runtime", require_tool=[], timeout_sec=timeout_sec, wp_env_root=temp_root
                )
                if prepared_artifact is not None:
                    full_profile = validate_wordpress_artifact.validate_staged_artifact(
                        "plugin", prepared_artifact.synthesized.staged, full_args,
                        subpath=Path(prepared_artifact.synthesized.plugin_slug),
                    )
                else:
                    full_profile = validate_wordpress_artifact.validate_artifact("plugin", plugin_dir, full_args)
                mcp_adapter_gate = mcp_adapter_runtime_gate(
                    requested=mcp_adapter_smoke,
                    static_gate=mcp_adapter_static_gate,
                    install=mcp_adapter_install,
                    list_servers=mcp_adapter_list,
                    tools_list=mcp_adapter_tools_list,
                    discover=mcp_adapter_discover,
                    execute=mcp_adapter_execute,
                    ability_name=ability_name,
                    expected_output=mcp_adapter_expected_output,
                )
                ai_client_gate = ai_client_provider_call_gate(
                    requested=ai_client_smoke,
                    static_gate=ai_client_static_gate,
                    command=ai_client_call,
                    provider_id=ai_client_provider_id,
                    model_id=ai_client_model_id,
                    helper_function=ai_client_helper_function,
                    expected_output=ai_client_expected_output,
                )
    finally:
        if npx and start and start.ok and not keep_running:
            stop = run_command([npx, "--yes", "@wordpress/env", "stop"], temp_root, timeout_sec)
        artifact_retention_receipts.extend(
            _release_prepared_runtime(
                prepared_artifact,
                prepared_hold_context,
                keep_artifacts or keep_running,
            )
        )
        prepared_hold_context = None
        if not keep_artifacts and not keep_running:
            try:
                cleanup_workspace(lease, repository_root=ROOT)
            except WorkspaceCleanupError as exc:
                cleanup_error = str(exc)

    status = status_from_gates(
        npx=npx,
        provision_full_profile=provision_full_profile,
        provisioning=provisioning,
        start=start,
        activation=activation,
        narrow_gate=narrow_gate,
        full_profile=full_profile,
        ability_smoke=ability_smoke,
        block_smoke=block_smoke,
        editor_smoke=editor_smoke_run,
        interactivity_static_gate=interactivity_static_gate,
        interactivity_smoke=interactivity_smoke,
        block_deprecation_static_gate=block_deprecation_static_gate,
        block_deprecation_smoke=block_deprecation_smoke,
        block_deprecation_post=block_deprecation_post,
        block_build_gate=block_build_gate,
        block_build_smoke=block_build_smoke,
        phpunit_gate=phpunit_gate,
        phpunit_smoke=phpunit_smoke,
        mcp_adapter_gate=mcp_adapter_gate,
        mcp_adapter_smoke=mcp_adapter_smoke,
        ai_client_gate=ai_client_gate,
        ai_client_smoke=ai_client_smoke,
        stop=stop,
        strict_full_profile=strict_full_profile,
    )
    if cleanup_error:
        status = "blocked"
    expected_synth_state = "retained" if keep_artifacts or keep_running else "removed"
    for receipt in artifact_retention_receipts:
        unexpected = receipt.component == "sandbox_output" and receipt.state != "removed"
        unexpected = unexpected or receipt.component == "synthesized_runtime" and receipt.state != expected_synth_state
        if unexpected or (receipt.error and "held runtime proof changed" in receipt.error):
            status = "blocked"
    retained = keep_artifacts or keep_running or cleanup_error is not None
    negative_space = list(BASE_NEGATIVE_SPACE)
    if phpunit_smoke and gate_status(phpunit_gate) == "pass":
        negative_space.remove("not PHPUnit proof")
    if artifact_check_status(full_profile, "phpcs_wpcs") != "pass":
        negative_space.insert(0, "not WPCS proof")
    if artifact_check_status(full_profile, "plugin_check") != "pass":
        negative_space.insert(0, "not Plugin Check proof")
    if not ability_name:
        negative_space.append("not Abilities API registration proof")
    elif ability_smoke_status(ability_smoke) != "pass":
        negative_space.append("not Abilities API registration proof")
    if not execute_post_summary_ability or ability_smoke_status(ability_smoke) != "pass":
        negative_space.append("not Abilities API execution proof")
    if not block_name:
        negative_space.append("not block runtime registration proof")
    elif block_smoke_status(block_smoke) == "pass":
        negative_space.remove("not block validation proof")
        if block_build_smoke and gate_status(block_build_gate) == "pass":
            pass
        else:
            negative_space.append("not full block validation proof")
    else:
        negative_space.append("not block runtime registration proof")
    interactivity_passed = interactivity_smoke_status(editor_smoke_run, interactivity_smoke, interactivity_static_gate) == "pass"
    block_deprecation_passed = (
        block_deprecation_smoke_status(
            editor_smoke_run,
            block_deprecation_smoke,
            block_deprecation_static_gate,
            block_deprecation_post,
        )
        == "pass"
    )
    if editor_smoke_status(editor_smoke_run) == "pass":
        negative_space.remove("not editor or browser smoke proof")
        if editor_insert_render_smoke or block_deprecation_smoke:
            if not block_deprecation_passed:
                negative_space.append("not block deprecation proof")
            if not interactivity_passed:
                negative_space.append("not Interactivity API proof")
        else:
            negative_space.append("not full editor interaction proof")
    if mcp_adapter_smoke_status(mcp_adapter_gate) != "pass":
        negative_space.append("not MCP Adapter runtime proof")
    if ai_client_smoke_status(ai_client_gate) != "pass":
        negative_space.append("not AI Client provider-call proof")
    return {
        "status": status,
        "pass": status == "pass",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_artifact_path": staged_artifact.source_path if staged_artifact and staged_artifact.source_attested else None,
        "source_artifact_attested": bool(staged_artifact and staged_artifact.source_attested),
        "claimed_source_artifact_path": str(artifact_source_path) if artifact_source_path else None,
        "artifact_kind": artifact_kind,
        "input_artifact_digest": staged_artifact_digest,
        "fixture_root": str(temp_root),
        "runtime_root": str(temp_root),
        "workdir_parent": str(lease.caller_parent) if lease.caller_parent else None,
        "fixture_retained": retained,
        "cleanup_error": cleanup_error,
        "artifact_path": str(plugin_dir),
        "wrapped_block_artifact": wrapped_block_artifact_summary(wrapped_block_artifact),
        "npx": npx,
        "ability_name": ability_name,
        "execute_post_summary_ability": execute_post_summary_ability,
        "block_name": block_name,
        "fixture_kind": fixture_kind,
        "editor_smoke_requested": editor_smoke,
        "editor_insert_render_smoke_requested": editor_insert_render_smoke,
        "interactivity_smoke_requested": interactivity_smoke,
        "block_deprecation_smoke_requested": block_deprecation_smoke,
        "block_build_smoke_requested": block_build_smoke,
        "phpunit_smoke_requested": phpunit_smoke,
        "mcp_adapter_smoke_requested": mcp_adapter_smoke,
        "mcp_adapter_execute_args": mcp_adapter_execute_args or {},
        "mcp_adapter_expected_output": mcp_adapter_expected_output,
        "ai_client_smoke_requested": ai_client_smoke,
        "ai_client_provider_id": ai_client_provider_id,
        "ai_client_model_id": ai_client_model_id,
        "ai_client_helper_function": ai_client_helper_function,
        "ai_client_prompt": ai_client_prompt,
        "ai_client_expected_output": ai_client_expected_output,
        "provision_full_profile": provision_full_profile,
        "strict_full_profile": strict_full_profile,
        "provisioning": {key: asdict(value) for key, value in provisioning.items()},
        "commands": {
            "start": asdict(start) if start else None,
            "activation": asdict(activation) if activation else None,
            "ability_smoke": asdict(ability_smoke) if ability_smoke else None,
            "mcp_adapter_install": asdict(mcp_adapter_install) if mcp_adapter_install else None,
            "mcp_adapter_list": asdict(mcp_adapter_list) if mcp_adapter_list else None,
            "mcp_adapter_tools_list": asdict(mcp_adapter_tools_list) if mcp_adapter_tools_list else None,
            "mcp_adapter_discover": asdict(mcp_adapter_discover) if mcp_adapter_discover else None,
            "mcp_adapter_execute": asdict(mcp_adapter_execute) if mcp_adapter_execute else None,
            "ai_client_call": asdict(ai_client_call) if ai_client_call else None,
            "block_smoke": asdict(block_smoke) if block_smoke else None,
            "block_deprecation_post": asdict(block_deprecation_post) if block_deprecation_post else None,
            "editor_smoke": asdict(editor_smoke_run) if editor_smoke_run else None,
            "stop": asdict(stop) if stop else None,
        },
        "ability_smoke_status": ability_smoke_status(ability_smoke),
        "mcp_adapter_smoke_status": mcp_adapter_smoke_status(mcp_adapter_gate),
        "ai_client_smoke_status": ai_client_smoke_status(ai_client_gate),
        "block_smoke_status": block_smoke_status(block_smoke),
        "block_build_smoke_status": gate_status(block_build_gate),
        "interactivity_smoke_status": interactivity_smoke_status(
            editor_smoke_run,
            interactivity_smoke,
            interactivity_static_gate,
        ),
        "block_deprecation_smoke_status": block_deprecation_smoke_status(
            editor_smoke_run,
            block_deprecation_smoke,
            block_deprecation_static_gate,
            block_deprecation_post,
        ),
        "phpunit_smoke_status": gate_status(phpunit_gate),
        "editor_smoke_status": editor_smoke_status(editor_smoke_run),
        "narrow_gate": narrow_gate,
        "block_gate": block_gate,
        "block_build_gate": block_build_gate,
        "interactivity_static_gate": interactivity_static_gate,
        "block_deprecation_static_gate": block_deprecation_static_gate,
        "mcp_adapter_static_gate": mcp_adapter_static_gate,
        "mcp_adapter_gate": mcp_adapter_gate,
        "ai_client_static_gate": ai_client_static_gate,
        "ai_client_gate": ai_client_gate,
        "phpunit_gate": phpunit_gate,
        "full_plugin_runtime_profile": full_profile,
        "negative_space": negative_space,
        "_artifact_retention_receipts": artifact_retention_receipts,
    }


def write_result(summary: dict[str, Any], run_id: str, results_root: Path = RESULTS_ROOT) -> Path:
    lease = create_named(results_root, run_id, WorkspacePurpose.RESULT)
    out_dir = lease.root
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    temporary = out_dir / ".runtime-smoke.json.tmp"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, out_dir / "runtime-smoke.json")

    full_status = (summary.get("full_plugin_runtime_profile") or {}).get("status", "not_run")
    fixture_retained = str(summary["fixture_retained"]).lower()
    lines = [
        f"# WordPress Runtime Smoke ({run_id})",
        "",
        f"- Status: `{summary['status']}`",
        f"- Narrow gate: `{(summary.get('narrow_gate') or {}).get('status', 'not_run')}`",
        f"- Full plugin runtime profile: `{full_status}`",
        f"- Artifact kind: `{summary.get('artifact_kind', 'plugin')}`",
        f"- Plugin activation: `{(summary.get('commands', {}).get('activation') or {}).get('returncode', 'not_run')}`",
        f"- Abilities smoke: `{summary.get('ability_smoke_status', 'not_run')}`",
        f"- MCP Adapter smoke: `{summary.get('mcp_adapter_smoke_status', 'not_run')}`",
        f"- AI Client smoke: `{summary.get('ai_client_smoke_status', 'not_run')}`",
        f"- Block registration smoke: `{summary.get('block_smoke_status', 'not_run')}`",
        f"- Block build smoke: `{summary.get('block_build_smoke_status', 'not_run')}`",
        f"- Interactivity smoke: `{summary.get('interactivity_smoke_status', 'not_run')}`",
        f"- Block deprecation smoke: `{summary.get('block_deprecation_smoke_status', 'not_run')}`",
        f"- PHPUnit smoke: `{summary.get('phpunit_smoke_status', 'not_run')}`",
        f"- Editor/browser smoke: `{summary.get('editor_smoke_status', 'not_run')}`",
        f"- Editor insert/render requested: `{str(summary.get('editor_insert_render_smoke_requested', False)).lower()}`",
        f"- Provisioned full profile: `{str(summary.get('provision_full_profile', False)).lower()}`",
        f"- Fixture retained: `{fixture_retained}`",
        "",
        "## Negative Space",
        "",
    ]
    lines.extend(f"- {item}" for item in summary["negative_space"])
    lines.append("")
    (out_dir / "scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a disposable WordPress wp-env runtime smoke.")
    parser.add_argument("--timeout-sec", type=int, default=300)
    parser.add_argument(
        "--workdir",
        help="Optional parent for a newly created unique run directory; files are not written at the parent root.",
    )
    parser.add_argument("--artifact-path", help="Existing generated artifact directory or PHP file to copy into the wp-env project.")
    parser.add_argument("--artifact-kind", choices=("plugin", "block"), default="plugin", help="Interpret --artifact-path as a full plugin or generated block files.")
    parser.add_argument("--fixture-kind", choices=("plugin", "block"), default="plugin", help="Disposable fixture type to create when --artifact-path is omitted.")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep the generated fixture directory after stopping.")
    parser.add_argument("--keep-running", action="store_true", help="Leave wp-env running for manual debugging.")
    parser.add_argument("--provision-full-profile", action="store_true", help="Install WPCS locally and Plugin Check inside wp-env, then require the full plugin runtime profile to pass.")
    parser.add_argument("--strict-full-profile", action="store_true", help="Require full plugin runtime profile to pass.")
    parser.add_argument("--ability-name", help="Named Abilities API ability to verify with wp_get_ability().")
    parser.add_argument("--execute-post-summary-ability", action="store_true", help="Create a post and execute --ability-name with a post_id input.")
    parser.add_argument("--block-name", help="Named block to verify in WP_Block_Type_Registry after plugin activation.")
    parser.add_argument("--editor-smoke", action="store_true", help="Open the block editor with Playwright and verify --block-name is available to the editor registry.")
    parser.add_argument("--editor-insert-render-smoke", action="store_true", help="Extend --editor-smoke by inserting the block, publishing a post, and verifying frontend render text.")
    parser.add_argument("--interactivity-smoke", action="store_true", help="Require Interactivity API static surfaces and a frontend click/state assertion. Requires --editor-insert-render-smoke.")
    parser.add_argument("--deprecation-smoke", action="store_true", help="Create a post with legacy serialized block content, open it in the editor, save the migrated block, and verify frontend output.")
    parser.add_argument(
        "--block-build-smoke",
        action="store_true",
        help="Require the generated block build through the approved package sandbox; never run npm on the host.",
    )
    parser.add_argument(
        "--phpunit-smoke",
        action="store_true",
        help="Require artifact-local PHPUnit through the approved package sandbox; never run Composer/PHPUnit on the host.",
    )
    parser.add_argument("--mcp-adapter-smoke", action="store_true", help="Install the MCP Adapter plugin and verify STDIO tools/list, discover, and execute for --ability-name.")
    parser.add_argument("--mcp-adapter-execute-args-json", default="{}", help="JSON object passed as parameters to mcp-adapter-execute-ability.")
    parser.add_argument("--mcp-adapter-expected-output", help="Substring expected in the MCP execute response.")
    parser.add_argument("--ai-client-smoke", action="store_true", help="Verify a generated deterministic provider call through wp_ai_client_prompt().")
    parser.add_argument("--ai-client-provider-id", help="Provider ID expected to be registered for --ai-client-smoke.")
    parser.add_argument("--ai-client-model-id", help="Model ID expected to be used for --ai-client-smoke.")
    parser.add_argument("--ai-client-helper-function", help="Generated helper function to call for --ai-client-smoke, e.g. Vendor\\Plugin\\generate_summary.")
    parser.add_argument("--ai-client-prompt", default="Runtime AI Client smoke", help="Prompt string passed to --ai-client-helper-function.")
    parser.add_argument("--ai-client-expected-output", help="Substring expected in the AI Client provider-call output.")
    parser.add_argument("--write", action="store_true", help="Write evals/results output.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--results-root", type=Path, default=RESULTS_ROOT)
    parser.add_argument("--evidence-id", help="Opaque caller identity persisted with runtime evidence.")
    parser.add_argument("--expected-artifact-digest", help="Expected digest of --artifact-path for repair certification.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_safe_name(args.run_id)
    except ValueError as exc:
        parser.error(str(exc))
    if bool(args.evidence_id) != bool(args.expected_artifact_digest):
        parser.error("--evidence-id and --expected-artifact-digest must be supplied together")
    expected_artifact_digest = None
    if args.expected_artifact_digest:
        if not args.artifact_path:
            parser.error("--expected-artifact-digest requires --artifact-path")
        try:
            expected_artifact_digest = str(args.expected_artifact_digest)
            digest_regular_tree(Path(args.artifact_path))
        except (OSError, ValueError) as exc:
            parser.error(f"cannot digest --artifact-path: {exc}")
    try:
        results_root = validate_output_parent(args.results_root)
    except ValueError as exc:
        parser.error(str(exc))
    if args.artifact_path:
        artifact_resolved = Path(args.artifact_path).expanduser().resolve()
        if results_root == artifact_resolved or artifact_resolved in results_root.parents:
            parser.error("--results-root must not be inside --artifact-path")
    if args.execute_post_summary_ability and not args.ability_name:
        parser.error("--execute-post-summary-ability requires --ability-name")
    if args.mcp_adapter_smoke and not args.ability_name:
        parser.error("--mcp-adapter-smoke requires --ability-name")
    if args.ai_client_smoke:
        missing = [
            flag
            for flag, value in (
                ("--ai-client-provider-id", args.ai_client_provider_id),
                ("--ai-client-model-id", args.ai_client_model_id),
                ("--ai-client-helper-function", args.ai_client_helper_function),
            )
            if not value
        ]
        if missing:
            parser.error("--ai-client-smoke requires " + ", ".join(missing))
    try:
        mcp_adapter_execute_args = json.loads(args.mcp_adapter_execute_args_json)
    except json.JSONDecodeError as exc:
        parser.error(f"--mcp-adapter-execute-args-json must be valid JSON: {exc}")
    if not isinstance(mcp_adapter_execute_args, dict):
        parser.error("--mcp-adapter-execute-args-json must decode to a JSON object")
    can_infer_block_name = bool(
        (args.fixture_kind == "block" and not args.artifact_path)
        or (args.artifact_kind == "block" and args.artifact_path)
    )
    if args.editor_smoke and not args.block_name and not can_infer_block_name:
        parser.error("--editor-smoke requires --block-name")
    if args.editor_insert_render_smoke and not args.block_name and not can_infer_block_name:
        parser.error("--editor-insert-render-smoke requires --block-name")
    if args.interactivity_smoke and not args.editor_insert_render_smoke:
        parser.error("--interactivity-smoke requires --editor-insert-render-smoke")
    if args.deprecation_smoke and not args.block_name and not can_infer_block_name:
        parser.error("--deprecation-smoke requires --block-name")
    summary = run_smoke(
        timeout_sec=args.timeout_sec,
        workdir=Path(args.workdir) if args.workdir else None,
        artifact_path=Path(args.artifact_path) if args.artifact_path else None,
        artifact_kind=args.artifact_kind,
        expected_artifact_digest=expected_artifact_digest,
        evidence_id=args.evidence_id,
        keep_artifacts=args.keep_artifacts,
        keep_running=args.keep_running,
        provision_full_profile=args.provision_full_profile,
        strict_full_profile=args.strict_full_profile,
        ability_name=args.ability_name,
        execute_post_summary_ability=args.execute_post_summary_ability,
        block_name=args.block_name,
        fixture_kind=args.fixture_kind,
        editor_smoke=args.editor_smoke or args.editor_insert_render_smoke,
        editor_insert_render_smoke=args.editor_insert_render_smoke,
        interactivity_smoke=args.interactivity_smoke,
        block_deprecation_smoke=args.deprecation_smoke,
        block_build_smoke=args.block_build_smoke,
        phpunit_smoke=args.phpunit_smoke,
        mcp_adapter_smoke=args.mcp_adapter_smoke,
        mcp_adapter_execute_args=mcp_adapter_execute_args,
        mcp_adapter_expected_output=args.mcp_adapter_expected_output,
        ai_client_smoke=args.ai_client_smoke,
        ai_client_provider_id=args.ai_client_provider_id,
        ai_client_model_id=args.ai_client_model_id,
        ai_client_helper_function=args.ai_client_helper_function,
        ai_client_prompt=args.ai_client_prompt,
        ai_client_expected_output=args.ai_client_expected_output,
    )
    summary.update({
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": args.run_id,
        "evidence_id": args.evidence_id,
        "input_artifact_digest": summary.get("input_artifact_digest"),
    })
    if args.write:
        out_dir = write_result(summary, args.run_id, results_root)
        summary["result_dir"] = str(out_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] == "pass":
        return 0
    if summary["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
