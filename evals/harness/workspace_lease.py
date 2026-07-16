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
HOST_UID = os.getuid()
HOST_GID = os.getgid()


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


def validate_safe_name(name: str) -> None:
    if not NAME_PATTERN.fullmatch(name) or name in {".", ".."}:
        raise ValueError(f"unsafe workspace name: {name!r}")
    if Path(name).is_absolute() or Path(name).drive or "/" in name or "\\" in name:
        raise ValueError(f"unsafe workspace name: {name!r}")


def validate_output_parent(parent: Path) -> Path:
    """Resolve an output parent only after rejecting symlinked ancestors."""
    absolute = parent.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError(f"output parent contains symlink component: {current}")
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise ValueError(f"output parent ancestor is not a directory: {current}")
    return absolute.resolve()


def _verify_identity(info: os.stat_result, mode: int, *, directory: bool) -> None:
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
        raise RuntimeError("workspace entry type or mode drift")
    if (info.st_uid, info.st_gid) != (HOST_UID, HOST_GID):
        raise RuntimeError("workspace entry owner drift")
    if not directory and info.st_nlink != 1:
        raise RuntimeError("workspace file link-count drift")


def _validate_component(name: str) -> None:
    if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("unsafe workspace entry name")


def open_secure_directory(parent_fd: int, name: str, mode: int = 0o700) -> int:
    _validate_component(name)
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    _verify_identity(before, mode, directory=True)
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        os.fchmod(descriptor, mode)
        after = os.fstat(descriptor)
        _verify_identity(after, mode, directory=True)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise RuntimeError("workspace directory identity changed while opening")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def create_secure_directory(parent_fd: int, name: str, mode: int = 0o700) -> int:
    _validate_component(name)
    os.mkdir(name, mode, dir_fd=parent_fd)
    os.chmod(name, mode, dir_fd=parent_fd, follow_symlinks=False)
    return open_secure_directory(parent_fd, name, mode)


def create_secure_file(parent_fd: int, name: str, mode: int) -> int:
    _validate_component(name)
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent_fd)
    try:
        os.fchmod(descriptor, mode)
        _verify_identity(os.fstat(descriptor), mode, directory=False)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short workspace file write")
        view = view[written:]


def _open_directory_nofollow(path: Path) -> int:
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _create(parent: Path, name: str, purpose: WorkspacePurpose, caller_parent: Path | None) -> WorkspaceLease:
    validate_safe_name(name)
    resolved_parent = validate_output_parent(parent)
    resolved_parent.mkdir(parents=True, exist_ok=True)
    root = resolved_parent / name
    parent_fd = _open_directory_nofollow(resolved_parent)
    lease_id = uuid.uuid4().hex
    payload = f"{lease_id}\n{purpose.value}\n"
    root_fd = sentinel_fd = None
    created_identity = None
    try:
        root_fd = create_secure_directory(parent_fd, name)
        created = os.fstat(root_fd); created_identity = (created.st_dev, created.st_ino)
        sentinel_fd = create_secure_file(root_fd, SENTINEL_NAME, 0o600)
        _write_all(sentinel_fd, payload.encode("utf-8")); os.fsync(sentinel_fd)
        os.close(sentinel_fd); sentinel_fd = None
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False); opened = os.fstat(root_fd)
        _verify_identity(current, 0o700, directory=True); _verify_identity(opened, 0o700, directory=True)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino): raise RuntimeError("workspace root changed after sentinel creation")
    except Exception:
        if sentinel_fd is not None: os.close(sentinel_fd)
        if root_fd is not None: os.close(root_fd)
        if created_identity is not None:
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == created_identity:
                    shutil.rmtree(name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)
        raise
    os.close(root_fd); os.close(parent_fd)
    lease = WorkspaceLease(root, caller_parent, purpose, lease_id, True)
    _LIVE_LEASES[lease_id] = lease
    return lease


def create_ephemeral(parent: Path | None, purpose: WorkspacePurpose) -> WorkspaceLease:
    caller_parent = validate_output_parent(parent) if parent is not None else None
    actual_parent = caller_parent or Path(tempfile.gettempdir()).resolve()
    for _attempt in range(100):
        name = f"wp-meta-skills-{purpose.value}-{uuid.uuid4().hex[:12]}"
        try:
            return _create(actual_parent, name, purpose, caller_parent)
        except FileExistsError:
            continue
    raise RuntimeError("could not create a unique workspace lease")


def create_named(parent: Path, safe_name: str, purpose: WorkspacePurpose) -> WorkspaceLease:
    resolved_parent = validate_output_parent(parent)
    return _create(resolved_parent, safe_name, purpose, resolved_parent)


def cleanup(lease: WorkspaceLease, *, repository_root: Path | None = None) -> None:
    try:
        if not isinstance(lease, WorkspaceLease) or not lease.cleanup_allowed:
            raise WorkspaceCleanupError("workspace cleanup requires a live lease")
        if _LIVE_LEASES.get(lease.lease_id) is not lease:
            raise WorkspaceCleanupError("workspace cleanup requires factory-issued live authority")
        root = lease.root
        root_stat = root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode) or stat.S_IMODE(root_stat.st_mode) != 0o700 or (root_stat.st_uid,root_stat.st_gid)!=(HOST_UID,HOST_GID):
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
            or sentinel_stat.st_nlink != 1
            or (sentinel_stat.st_uid,sentinel_stat.st_gid) != (HOST_UID,HOST_GID)
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
