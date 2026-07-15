"""Approved generated npm and PHPUnit execution through the package sandbox."""
from __future__ import annotations

import platform
from dataclasses import dataclass

import artifact_staging
import dependency_egress_proxy
import runtime_image_provision
import sandbox_evidence
import sandboxed_package_runner
from sandbox_runner_types import SandboxRequest
from wp_runtime_evidence import scrub_tail

DIAGNOSTIC_PREFIX = "generated command diagnostic: "
DIAGNOSTIC_TAIL_LIMIT = 1000


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    detail: str
    command: tuple[str, ...]
    output: artifact_staging.StagedTree | None
    staging_cleanup_receipts: tuple[artifact_staging.StagingCleanupReceipt, ...] = ()


def _profile(staged: artifact_staging.StagedTree, kind: str) -> str | None:
    entries = {item.path: item.sha256 for item in staged.manifest}
    matches = [
        name
        for name, profile in dependency_egress_proxy.ACQUISITION_PROFILES.items()
        if profile.kind == kind
        and entries.get(profile.manifest_path) == profile.manifest_sha256
        and entries.get(profile.lock_path) == profile.lock_sha256
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _image(kind: str) -> str:
    image_name = "node" if kind == "npm" else "composer"
    item = runtime_image_provision.inventory()["images"][image_name]
    digest = runtime_image_provision.platform_digest(item, platform.machine())
    return f"{item['tag'].split(':')[0]}@{digest}"


def _diagnostic_detail(result) -> str:
    if result.status == "pass":
        return result.detail
    output = result.stderr or result.stdout
    if not output:
        return result.detail
    sanitized = scrub_tail(output, len(output))
    diagnostic = DIAGNOSTIC_PREFIX + sanitized[-DIAGNOSTIC_TAIL_LIMIT:]
    return sandbox_evidence.finalize(result.detail, error=diagnostic)


def run_generated(
    staged: artifact_staging.StagedTree,
    phase: str,
    timeout: int,
) -> ExecutionOutcome:
    artifact_staging.verify_staged_tree(staged)
    if phase == "npm-build":
        kind, command = "npm", ("npm", "run", "build")
    elif phase == "phpunit":
        kind, command = "composer", ("php", "vendor/bin/phpunit")
    else:
        raise ValueError("unsupported generated execution phase")
    profile = _profile(staged, kind)
    if profile is None:
        detail = f"{phase} requires an exact approved manifest and lock profile"
        return ExecutionOutcome("blocked", detail, command, None)
    request = SandboxRequest(
        staged,
        _image(kind),
        command,
        workspace_bytes=1200 * 1024**2,
        workspace_inodes=100000,
        timeout=min(max(1, timeout), 900),
        acquisition=profile,
    )
    try:
        result = sandboxed_package_runner.run_sandbox(request)
    except Exception as exc:
        detail = f"{phase} sandbox boundary raised {type(exc).__name__}"
        return ExecutionOutcome("blocked", detail, command, None)
    return ExecutionOutcome(
        result.status,_diagnostic_detail(result),command,result.output,
        result.staging_cleanup_receipts,
    )
