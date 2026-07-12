"""Capability-based ownership for disposable harness workspaces."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SENTINEL_NAME = ".workspace-lease"
_LIVE_LEASES: dict[str, "WorkspaceLease"] = {}


class WorkspaceCleanupError(RuntimeError):
    """A lease could not safely authorize cleanup."""


class WorkspacePurpose(str, Enum):
    RUNTIME = "runtime"
    REPAIR_RUN = "repair-run"
    RESULT = "result"
    ARTIFACT_EXECUTION = "artifact-execution"


@dataclass(frozen=True)
class WorkspaceLease:
    root: Path
    caller_parent: Path | None
    purpose: WorkspacePurpose
    lease_id: str
    cleanup_allowed: bool


def _validate_name(name: str) -> None:
    if not NAME_PATTERN.fullmatch(name) or name in {".", ".."}:
        raise ValueError(f"unsafe workspace name: {name!r}")
    if Path(name).is_absolute() or Path(name).drive or "/" in name or "\\" in name:
        raise ValueError(f"unsafe workspace name: {name!r}")


def _create(parent: Path, name: str, purpose: WorkspacePurpose, caller_parent: Path | None) -> WorkspaceLease:
    _validate_name(name)
    resolved_parent = parent.expanduser().resolve()
    resolved_parent.mkdir(parents=True, exist_ok=True)
    root = resolved_parent / name
    root.mkdir(exist_ok=False)
    lease_id = uuid.uuid4().hex
    sentinel = root / SENTINEL_NAME
    payload = f"{lease_id}\n{purpose.value}\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(sentinel, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        if not stat.S_ISREG(sentinel.lstat().st_mode) or stat.S_IMODE(sentinel.stat().st_mode) != 0o600:
            raise RuntimeError("workspace lease sentinel is not a mode-0600 regular file")
    except Exception:
        shutil.rmtree(root)
        raise
    lease = WorkspaceLease(root, caller_parent, purpose, lease_id, True)
    _LIVE_LEASES[lease_id] = lease
    return lease


def create_ephemeral(parent: Path | None, purpose: WorkspacePurpose) -> WorkspaceLease:
    caller_parent = parent.expanduser().resolve() if parent is not None else None
    actual_parent = caller_parent or Path(tempfile.gettempdir()).resolve()
    for _attempt in range(100):
        name = f"wp-meta-skills-{purpose.value}-{uuid.uuid4().hex[:12]}"
        try:
            return _create(actual_parent, name, purpose, caller_parent)
        except FileExistsError:
            continue
    raise RuntimeError("could not create a unique workspace lease")


def create_named(parent: Path, safe_name: str, purpose: WorkspacePurpose) -> WorkspaceLease:
    resolved_parent = parent.expanduser().resolve()
    return _create(resolved_parent, safe_name, purpose, resolved_parent)


def cleanup(lease: WorkspaceLease, *, repository_root: Path | None = None) -> None:
    try:
        if not isinstance(lease, WorkspaceLease) or not lease.cleanup_allowed:
            raise WorkspaceCleanupError("workspace cleanup requires a live lease")
        if _LIVE_LEASES.get(lease.lease_id) is not lease:
            raise WorkspaceCleanupError("workspace cleanup requires factory-issued live authority")
        root = lease.root
        root_stat = root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise WorkspaceCleanupError("workspace lease root is not a real directory")
        resolved_root = root.resolve()
        parent = (lease.caller_parent or Path(tempfile.gettempdir())).resolve()
        dangerous = {Path(resolved_root.anchor), Path.home().resolve(), parent}
        if repository_root is not None:
            dangerous.add(repository_root.resolve())
        if resolved_root in dangerous or resolved_root.parent != parent:
            raise WorkspaceCleanupError("workspace lease root is outside its authorized parent or is dangerous")
        sentinel = root / SENTINEL_NAME
        sentinel_stat = sentinel.lstat()
        if (
            stat.S_ISLNK(sentinel_stat.st_mode)
            or not stat.S_ISREG(sentinel_stat.st_mode)
            or stat.S_IMODE(sentinel_stat.st_mode) != 0o600
        ):
            raise WorkspaceCleanupError("workspace lease sentinel is not a mode-0600 regular file")
        expected = f"{lease.lease_id}\n{lease.purpose.value}\n"
        if sentinel.read_text(encoding="utf-8") != expected:
            raise WorkspaceCleanupError("workspace lease sentinel does not match the lease")
        shutil.rmtree(root)
        del _LIVE_LEASES[lease.lease_id]
    except WorkspaceCleanupError:
        raise
    except Exception as exc:
        raise WorkspaceCleanupError(f"workspace cleanup validation failed: {exc}") from exc
