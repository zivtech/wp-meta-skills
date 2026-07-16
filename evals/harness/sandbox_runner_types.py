"""Value types shared by the sandbox runner and its boundary helpers."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import artifact_staging
import sandbox_source_proof as source_proof
import workspace_lease


@dataclass(frozen=True)
class SandboxRequest:
    staged: artifact_staging.StagedTree; image: str; argv: tuple[str, ...]
    user: str = f"{os.getuid()}:{os.getgid()}"; environment: tuple[tuple[str, str], ...] = ()
    workspace_bytes: int = 536870912; workspace_inodes: int = 50000
    memory: str = "1g"; pids: int = 128; cpus: str = "1.0"; timeout: int = 300
    stdout_limit: int = 131072; stderr_limit: int = 131072; result_parent: Path | None = None
    acquisition: str | None = None


@dataclass(frozen=True)
class SandboxResult:
    status: str; returncode: int | None; stdout: str; stderr: str
    output: artifact_staging.StagedTree | None; detail: str; container_name: str
    runtime_identity: dict[str, object] | None = None
    staging_cleanup_receipts: tuple[artifact_staging.StagingCleanupReceipt, ...] = ()


@dataclass(frozen=True)
class StagedCapability:
    lease_fd: int; root_fd: int; source: str; device: int; inode: int
    path_kinds: tuple[tuple[str, str], ...]; proof: source_proof.SourceProof; budget: source_proof.ProofBudget


@dataclass(frozen=True)
class ProxyCapability:
    lease: workspace_lease.WorkspaceLease; lease_fd: int; file_fd: int; source: str; sha256: str
    proof: source_proof.FileProof | None = None; budget: source_proof.ProofBudget | None = None


@dataclass(frozen=True)
class ResourceEvent:
    kind: str; name: str; state: str


class ResourceLedger:
    def __init__(self): self.events = (); self.daemon_id = None; self.identity_tainted = False; self.targets = {}
    def record(self, kind, name, state): self.events = self.events + (ResourceEvent(kind, name, state),)
    def bind(self, name, target):
        if not re.fullmatch(r"[0-9a-f]{64}", target): raise ValueError("resource target identity is malformed")
        if name in self.targets and self.targets[name] != target: raise RuntimeError("resource target identity cannot be rebound")
        self.targets = {**self.targets, name: target}
    def target(self, name): return self.targets.get(name, name)
    def created(self, kind, name): return any(item.kind == kind and item.name == name and item.state == "created" for item in self.events)
    def needs_cleanup(self, kind, name):
        states = [item.state for item in self.events if item.kind == kind and item.name == name]
        terminal = {"removed", "retained"} | ({"detached"} if kind == "container" else set())
        return "created" in states and states[-1] not in terminal


@dataclass(frozen=True)
class AcquisitionContext:
    internal: str; egress: str; proxy: str; nonce: str; package_ip: str; proxy_ip: str
    gateway_ip: str; proxy_image: str; proxy_code: ProxyCapability; memory_available: int
    ledger: ResourceLedger; supervisor: object | None = None; proxy_target: str = ""


@dataclass(frozen=True)
class DetachedIdentity:
    container_id: str; started_at: str; network_mode: str; daemon_id: str; network_id: str
    package_image_id: str; proxy_container_id: str; proxy_image_id: str


class SandboxBoundaryError(RuntimeError):
    def __init__(self, message, timings, metrics, resources, staging_cleanup_receipts=()):
        super().__init__(message); self.timings = dict(timings); self.metrics = dict(metrics); self.resources = list(resources)
        self.staging_cleanup_receipts=tuple(staging_cleanup_receipts)
