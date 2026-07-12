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
from certify_wordpress_executor_artifact import (EVIDENCE_SCHEMA_VERSION, EXECUTION_CLOSURE_IGNORE,
                                                  digest_regular_tree, snapshot_regular_tree)
from workspace_lease import (WorkspaceCleanupError, WorkspacePurpose, cleanup as cleanup_workspace,
                             create_ephemeral, create_named, validate_safe_name)
from workspace_lease import validate_output_parent


ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = ROOT / "evals" / "results" / "wordpress-skill-candidate-eval"
DEFAULT_RUN_ID = "wp-env-runtime-smoke"
MCP_ADAPTER_PLUGIN_ZIP = "https://github.com/WordPress/mcp-adapter/releases/latest/download/mcp-adapter.zip"
WPCS_REQUIRE_DEV = {
    "dealerdirect/phpcodesniffer-composer-installer": "^1.0",
    "phpcompatibility/phpcompatibility-wp": "^2.1",
    "wp-coding-standards/wpcs": "^3.1",
}


def create_wp_env_temp_root() -> Path:
    """Create a temp root whose basename is safe for wp-env Docker names."""
    return create_ephemeral(Path(tempfile.gettempdir()), WorkspacePurpose.RUNTIME).root
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
    config = {
        "plugins": [f"./{plugin_path}"],
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


def copy_plugin_artifact(source: Path, root: Path) -> Path:
    if stat.S_ISLNK(source.lstat().st_mode):
        raise ValueError(f"artifact root is a symlink: {source}")
    source = source.resolve(strict=True)
    if not source.exists():
        raise FileNotFoundError(f"artifact path does not exist: {source}")

    root.mkdir(parents=True, exist_ok=True)
    plugin_dir = root / source.name
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)

    if stat.S_ISDIR(source.lstat().st_mode):
        plugin_dir.mkdir()
        for relative, content, _info in snapshot_regular_tree(source):
            destination = plugin_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _write_staged_file(destination, content)
    else:
        plugin_dir.mkdir()
        _relative, content, _info = snapshot_regular_tree(source)[0]
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


def write_wpcs_composer_file(root: Path, plugin_slug: str) -> None:
    composer_json = {
        "require-dev": WPCS_REQUIRE_DEV,
        "config": {
            "allow-plugins": {
                "dealerdirect/phpcodesniffer-composer-installer": True,
            },
        },
        "scripts": {
            "phpcs": f"phpcs --standard=WordPress --extensions=php {plugin_slug}",
        },
    }
    (root / "composer.json").write_text(json.dumps(composer_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def status_from_gates(
    *,
    npx: str | None,
    provision_full_profile: bool,
    provisioning: dict[str, CommandRun],
    start: CommandRun | None,
    activation: CommandRun | None,
    narrow_gate: dict[str, Any] | None,
    full_profile: dict[str, Any] | None,
    ability_smoke: CommandRun | None,
    block_smoke: CommandRun | None,
    editor_smoke: CommandRun | None,
    interactivity_static_gate: dict[str, Any] | None,
    interactivity_smoke: bool,
    block_deprecation_static_gate: dict[str, Any] | None,
    block_deprecation_smoke: bool,
    block_deprecation_post: CommandRun | None,
    block_build_gate: dict[str, Any] | None,
    block_build_smoke: bool,
    phpunit_gate: dict[str, Any] | None,
    phpunit_smoke: bool,
    mcp_adapter_gate: dict[str, Any] | None,
    mcp_adapter_smoke: bool,
    ai_client_gate: dict[str, Any] | None,
    ai_client_smoke: bool,
    stop: CommandRun | None,
    strict_full_profile: bool,
) -> str:
    require_full_profile = strict_full_profile or provision_full_profile
    if provision_full_profile and any(not command.ok for command in provisioning.values()):
        return "blocked"
    artifact_composer_install = provisioning.get("artifact_composer_install")
    if phpunit_smoke and artifact_composer_install and not artifact_composer_install.ok:
        return "blocked"
    if block_build_smoke:
        block_build_status = gate_status(block_build_gate)
        if block_build_status in {"blocked", "fail"}:
            return block_build_status
        if block_build_status != "pass":
            return "fail"
    interactivity_status = interactivity_smoke_status(editor_smoke, interactivity_smoke, interactivity_static_gate)
    if interactivity_status in {"blocked", "fail"}:
        return interactivity_status
    deprecation_status = block_deprecation_smoke_status(
        editor_smoke,
        block_deprecation_smoke,
        block_deprecation_static_gate,
        block_deprecation_post,
    )
    if deprecation_status in {"blocked", "fail"}:
        return deprecation_status
    if not npx:
        return "blocked"
    if not start or not start.ok:
        return "blocked"
    if not activation or not activation.ok:
        return "fail"
    ability_status = ability_smoke_status(ability_smoke)
    if ability_status in {"blocked", "fail"}:
        return ability_status
    if block_smoke_status(block_smoke) == "fail":
        return "fail"
    if phpunit_smoke:
        phpunit_status = gate_status(phpunit_gate)
        if phpunit_status in {"blocked", "fail"}:
            return phpunit_status
        if phpunit_status != "pass":
            return "fail"
    if mcp_adapter_smoke:
        mcp_status = mcp_adapter_smoke_status(mcp_adapter_gate)
        if mcp_status in {"blocked", "fail"}:
            return mcp_status
        if mcp_status != "pass":
            return "fail"
    if ai_client_smoke:
        ai_client_status = ai_client_smoke_status(ai_client_gate)
        if ai_client_status in {"blocked", "fail"}:
            return ai_client_status
        if ai_client_status != "pass":
            return "fail"
    editor_status = editor_smoke_status(editor_smoke)
    if editor_status in {"blocked", "fail"}:
        return editor_status
    if not narrow_gate:
        return "fail"
    if narrow_gate["status"] != "pass":
        return narrow_gate["status"]
    if require_full_profile and full_profile and full_profile["status"] != "pass":
        return full_profile["status"]
    if stop and not stop.ok:
        return "blocked"
    return "pass"


def run_smoke(
    *,
    timeout_sec: int,
    workdir: Path | None = None,
    artifact_path: Path | None = None,
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
    try:
        if artifact_path:
            if artifact_kind == "block":
                wrapped_block_artifact = copy_block_artifact_as_plugin(artifact_path, temp_root)
                plugin_dir = wrapped_block_artifact.plugin_dir
                source_block_artifact_path = artifact_path.resolve()
                block_name = block_name or wrapped_block_artifact.block_name
            else:
                plugin_dir = copy_plugin_artifact(artifact_path, temp_root)
        elif fixture_kind == "block":
            plugin_dir = write_block_runtime_fixture(temp_root)
            block_name = block_name or "acme/runtime-card"
        else:
            plugin_dir = write_runtime_fixture(temp_root)
    except Exception as setup_error:
        if not keep_artifacts and not keep_running:
            try:
                cleanup_workspace(lease, repository_root=ROOT)
            except WorkspaceCleanupError as cleanup_failure:
                raise cleanup_failure from setup_error
        raise
    staged_artifact_digest = digest_regular_tree(plugin_dir)
    if expected_artifact_digest and staged_artifact_digest != expected_artifact_digest:
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
    block_build_gate: dict[str, Any] | None = None
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
        if block_build_smoke:
            block_build_root = wrapped_block_artifact.copied_artifact_dir if wrapped_block_artifact else plugin_dir
            npm = shutil.which("npm")
            if npm:
                provisioning["block_npm_install"] = run_command(
                    [npm, "install", "--no-audit", "--no-fund"],
                    block_build_root,
                    timeout_sec,
                )
            else:
                provisioning["block_npm_install"] = missing_command("npm", block_build_root)
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

        if phpunit_smoke:
            composer_json = plugin_dir / "composer.json"
            composer = shutil.which("composer")
            if composer and composer_json.exists():
                provisioning["artifact_composer_install"] = run_command(
                    [composer, "install", "--no-interaction", "--no-progress", "--quiet"],
                    plugin_dir,
                    timeout_sec,
                )
            elif composer_json.exists():
                provisioning["artifact_composer_install"] = missing_command("composer", plugin_dir)

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
            composer = shutil.which("composer")
            if composer:
                write_wpcs_composer_file(temp_root, plugin_dir.name)
                provisioning["composer_install"] = run_command(
                    [composer, "install", "--no-interaction", "--no-progress", "--quiet"],
                    temp_root,
                    timeout_sec,
                )
            else:
                provisioning["composer_install"] = missing_command("composer", temp_root)

        if npx:
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
                narrow_gate = validate_wordpress_artifact.validate_artifact(
                    "plugin",
                    plugin_dir,
                    oracle_args(
                        profile="static",
                        require_tool=["php-lint", "wp-env"],
                        timeout_sec=timeout_sec,
                        wp_env_root=temp_root,
                    ),
                        )
                if block_name:
                    block_gate_path = source_block_artifact_path or plugin_dir
                    block_gate = validate_wordpress_artifact.validate_artifact(
                        "block",
                        block_gate_path,
                        oracle_args(
                            profile="static",
                            require_tool=["wp-env"],
                            timeout_sec=timeout_sec,
                            wp_env_root=temp_root,
                        ),
                    )
                if phpunit_smoke:
                    phpunit_gate = validate_wordpress_artifact.validate_artifact(
                        "plugin",
                        plugin_dir,
                        oracle_args(
                            profile="static",
                            require_tool=["phpunit"],
                            timeout_sec=timeout_sec,
                            wp_env_root=temp_root,
                        ),
                    )
                full_profile = validate_wordpress_artifact.validate_artifact(
                    "plugin",
                    plugin_dir,
                    oracle_args(
                        profile="runtime",
                        require_tool=[],
                        timeout_sec=timeout_sec,
                        wp_env_root=temp_root,
                    ),
                )
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
    retained = keep_artifacts or keep_running or cleanup_error is not None
    negative_space = [
        item for item in BASE_NEGATIVE_SPACE if not artifact_path or item != "not proof of executor-generated artifacts"
    ]
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
        "source_artifact_path": str(artifact_path.resolve()) if artifact_path else None,
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
    parser.add_argument("--block-build-smoke", action="store_true", help="Run npm install and require npm-build for the generated block artifact copy.")
    parser.add_argument("--phpunit-smoke", action="store_true", help="Run composer install when composer.json exists and require PHPUnit for the generated plugin artifact copy.")
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
