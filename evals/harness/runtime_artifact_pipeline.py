"""Capability-preserving preparation of generated artifacts for runtime proof."""
from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import artifact_execution
import artifact_staging
import workspace_lease


@dataclass(frozen=True)
class BuildResult:
    status: str
    detail: str
    command: tuple[str, ...]
    output: artifact_staging.StagedTree | None
    staging_cleanup_receipts: tuple[artifact_staging.StagingCleanupReceipt, ...] = ()


@dataclass(frozen=True)
class SynthesizedRuntime:
    staged: artifact_staging.StagedTree
    source_role: artifact_staging.StageRole
    plugin_slug: str
    block_name: str | None = None
    textdomain: str | None = None
    block_relative: Path | None = None

    @property
    def plugin_dir(self) -> Path:
        return self.staged.root / self.plugin_slug


@dataclass(frozen=True)
class CleanupReceipt:
    component: str
    state: str
    exists: bool
    live: bool
    recovery_path: str | None
    error: str | None
    resource_path: str | None = None


def cleanup_receipt_from_staging(component: str, receipt: artifact_staging.StagingCleanupReceipt) -> CleanupReceipt:
    return CleanupReceipt(
        component,receipt.state,receipt.exists,receipt.live,
        receipt.recovery_path,receipt.error,str(receipt.root),
    )


class RuntimePreparationError(RuntimeError):
    def __init__(self, primary: Exception, receipts):
        self.primary=primary; self.receipts=tuple(receipts)
        super().__init__(f"{type(primary).__name__}: {primary}")


class RuntimeInputCleanupError(RuntimeError):
    def __init__(self, primary: Exception, receipt):
        self.primary=primary; self.receipt=receipt
        cleanup=receipt.error or f"input copy remains {receipt.state}"
        super().__init__(f"{type(primary).__name__}: {primary}; cleanup: {cleanup}")


def _authentic_role(staged: artifact_staging.StagedTree, role: artifact_staging.StageRole) -> bool:
    try:
        artifact_staging.verify_staged_tree(staged)
    except (TypeError, ValueError, RuntimeError, OSError):
        return False
    return artifact_staging.has_stage_authority(staged, role)


def build_block(staged: artifact_staging.StagedTree, timeout: int) -> BuildResult:
    artifact_staging.verify_staged_tree(staged)
    outcome = artifact_execution.run_generated(staged, "npm-build", timeout)
    if outcome.status != "pass":
        return BuildResult(outcome.status,outcome.detail,outcome.command,None,outcome.staging_cleanup_receipts)
    if outcome.output is None:
        return BuildResult(
            "blocked","npm-build passed without a sandbox output capability",outcome.command,None,
            outcome.staging_cleanup_receipts,
        )
    if not _authentic_role(outcome.output, artifact_staging.StageRole.SANDBOX_OUTPUT):
        return BuildResult(
            "blocked","npm-build returned an unauthenticated sandbox output",outcome.command,None,
            outcome.staging_cleanup_receipts,
        )
    return BuildResult("pass",outcome.detail,outcome.command,outcome.output,outcome.staging_cleanup_receipts)


def _safe_slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part)[:48] or "generated-block"


def _block_metadata(snapshot) -> tuple[Path, dict]:
    candidates = sorted((path, content) for path, content, _info in snapshot if path.name == "block.json")
    if not candidates:
        raise FileNotFoundError("no block.json found in held artifact")
    preferred = [entry for entry in candidates if "build" in entry[0].parts] or candidates
    path, content = preferred[0]
    metadata = json.loads(content.decode("utf-8"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise ValueError("block.json must contain a block name")
    return path, metadata


def _regular_info(executable: bool = False):
    return SimpleNamespace(st_mode=stat.S_IFREG | (0o700 if executable else 0o600))


def _block_wrapper(textdomain: str, block_relative: str) -> bytes:
    return f"""<?php
/**
 * Plugin Name: Generated Block Runtime Wrapper
 * Version: 0.1.0
 * Text Domain: {textdomain}
 * License: GPL-2.0-or-later
 */
if ( ! defined( 'ABSPATH' ) ) {{ exit; }}
add_action( 'init', 'generated_block_runtime_wrapper_register_block' );
function generated_block_runtime_wrapper_register_block(): void {{
\t$source = __DIR__ . '/{block_relative}';
\t$built = $source . '/build';
\tregister_block_type( file_exists( $built . '/block.json' ) ? $built : $source );
}}
""".encode("utf-8")


def _block_snapshot(source_snapshot, block_json: Path, metadata: dict, textdomain: str):
    generated = [(Path(textdomain) / "generated" / path, content, info) for path, content, info in source_snapshot]
    block_dir = block_json.parent
    block_relative = (Path("generated") / block_dir).as_posix()
    wrapper = Path(textdomain) / f"{textdomain}.php"
    readme = Path(textdomain) / "readme.txt"
    generated.append((wrapper, _block_wrapper(textdomain, block_relative), _regular_info()))
    generated.append((readme, f"Generated runtime wrapper for {metadata['name']}.\n".encode(), _regular_info()))
    return generated


def _owned_synthesized(staged, *args) -> SynthesizedRuntime:
    try:
        return SynthesizedRuntime(staged,*args)
    except Exception as primary:
        receipt=cleanup_component("synthesized_runtime",staged)
        raise RuntimePreparationError(primary,[receipt]) from primary


def _stage_synthesized(snapshot, parent):
    try:
        return artifact_staging._stage_synthesized_snapshot(snapshot,parent)
    except artifact_staging.StagingCleanupError as error:
        receipt=cleanup_receipt_from_staging("synthesized_runtime",error.receipt)
        raise RuntimePreparationError(error.primary,[receipt]) from error


def synthesize_block_runtime(output: artifact_staging.StagedTree, parent: Path | None = None) -> SynthesizedRuntime:
    with artifact_staging.hold_staged_tree(output) as held:
        source_snapshot = artifact_staging.snapshot_held_tree(held)
        block_json, metadata = _block_metadata(source_snapshot)
        textdomain = _safe_slug(str(metadata.get("textdomain") or metadata["name"].split("/")[-1]))
        snapshot = _block_snapshot(source_snapshot, block_json, metadata, textdomain)
    staged = _stage_synthesized(snapshot,parent)
    return _owned_synthesized(staged,output.role,textdomain,str(metadata["name"]),textdomain,block_json.parent)


def synthesize_plugin_runtime(source: artifact_staging.StagedTree, plugin_slug: str, parent: Path | None = None) -> SynthesizedRuntime:
    slug = _safe_slug(plugin_slug)
    with artifact_staging.hold_staged_tree(source) as held:
        snapshot = [
            (Path(slug) / path, content, info)
            for path, content, info in artifact_staging.snapshot_held_tree(held)
        ]
    staged = _stage_synthesized(snapshot,parent)
    return _owned_synthesized(staged,source.role,slug)


def _retention_state(staged: artifact_staging.StagedTree) -> tuple[str, bool, bool]:
    exists = staged.lease.root.exists() or staged.lease.root.is_symlink()
    live = workspace_lease._LIVE_LEASES.get(staged.lease.lease_id) is staged.lease
    state = "retained" if exists else "unknown" if live else "removed"
    return state, exists, live


def _sanitized_recovery_path(staged: artifact_staging.StagedTree, retained: bool) -> str | None:
    if not retained:
        return None
    return str(staged.root)


def cleanup_component(component: str, staged: artifact_staging.StagedTree) -> CleanupReceipt:
    error = None
    try:
        workspace_lease.cleanup(staged.lease)
    except Exception as exc:
        error = f"{type(exc).__name__}: cleanup did not complete normally"
    state, exists, live = _retention_state(staged)
    retained = exists or live
    return CleanupReceipt(component, state, exists, live, _sanitized_recovery_path(staged, retained), error, str(staged.root))


def observe_component(component: str, staged: artifact_staging.StagedTree) -> CleanupReceipt:
    state, exists, live = _retention_state(staged)
    retained = exists or live
    return CleanupReceipt(component, state, exists, live, _sanitized_recovery_path(staged, retained), None, str(staged.root))


def cleanup_preparation(synthesized, output):
    receipts=[]
    if synthesized is not None:
        receipts.append(cleanup_component("synthesized_runtime",synthesized.staged))
    if output is not None:
        receipts.append(cleanup_component("sandbox_output",output))
    return receipts


def _receipt_dict(receipt: CleanupReceipt) -> dict:
    return {
        "component": receipt.component, "state": receipt.state,
        "exists": receipt.exists, "live": receipt.live,
        "resource_path": receipt.resource_path,
        "recovery_path": receipt.recovery_path, "error": receipt.error,
    }


def _component_summary(component: str, receipts: list[CleanupReceipt]) -> dict:
    matches = [receipt for receipt in receipts if receipt.component == component]
    if not matches:
        return _receipt_dict(CleanupReceipt(component,"not_created",False,False,None,None))
    retained = [receipt for receipt in matches if receipt.exists or receipt.live]
    selected = retained[0] if retained else matches[-1]
    summary = _receipt_dict(selected)
    summary["resources"] = [_receipt_dict(receipt) for receipt in matches]
    summary["errors"] = [receipt.error for receipt in matches if receipt.error]
    return summary


def retention_summary(receipts: list[CleanupReceipt]) -> dict:
    materialized = list(receipts)
    return {
        "retained": any(receipt.exists or receipt.live for receipt in materialized),
        "components": {
            component: _component_summary(component, materialized)
            for component in ("input_copy", "sandbox_output", "synthesized_runtime")
        },
        "resources": [_receipt_dict(receipt) for receipt in materialized],
    }


def staging_failure_result(
    *, artifact_type, artifact_path, source_path, profile, required_tools,
    runtime_roots, detail, receipts=(),
):
    items=list(receipts); retention=retention_summary(items)
    cleanup=[receipt for receipt in items if receipt.state!="removed" or receipt.error]
    checks=[{"id":"artifact_staging","status":"blocked","required":True,"detail":detail,"command":None}]
    checks.extend({
        "id":"artifact_cleanup","status":"blocked","required":True,
        "detail":receipt.error or f"input copy remains {receipt.state}","command":None,
    } for receipt in cleanup)
    execution_copy=(items[0].recovery_path or items[0].resource_path) if items else None
    return {
        "artifact_type":artifact_type,"artifact_path":artifact_path,"source_path":source_path,
        "execution_copy":execution_copy,"manifest_sha256":None,
        "sandbox_posture":{
            "generated_execution":"blocked","host_fallback":False,"static_scan_root":"unavailable",
        },
        "execution_retained":retention["retained"],"artifact_retention":retention,
        "profile":profile,"required_tools":required_tools,"runtime_roots":runtime_roots,
        "status":"blocked","pass":False,"checks":checks,
        "artifact_execution_cleanup_error":cleanup[0].error if cleanup else None,
    }
