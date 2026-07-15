"""Stream an exact held runtime closure into a prefixed synthesized stage."""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import artifact_staging
import workspace_lease


@dataclass(frozen=True)
class ExtraFile:
    path: str
    content: bytes
    executable: bool = False


def _safe_relative(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("runtime path must be a string")
    path = PurePosixPath(raw)
    unsafe = (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
        or "\\" in raw
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    )
    if unsafe:
        raise ValueError("runtime path is not a normalized safe relative path")
    if len(path.parts) > artifact_staging.MAX_DEPTH:
        raise ValueError("runtime path exceeds depth bound")
    if len(raw.encode()) > artifact_staging.MAX_PATH_BYTES:
        raise ValueError("runtime path exceeds byte bound")
    return raw


def _selection(held, members) -> tuple[artifact_staging.ManifestEntry, ...]:
    artifact_staging._require_held(held)
    if isinstance(members, (str, Path, PurePosixPath)):
        raise TypeError("runtime members must be an iterable of paths")
    selected = {}
    for member in members:
        path, entry = artifact_staging._normalized_held_file(held, member)
        if path in selected:
            raise ValueError("duplicate runtime member")
        selected[path] = entry
    return tuple(selected[path] for path in sorted(selected))


def _destinations(prefix: str, selected, extras) -> tuple:
    prefix = _safe_relative(prefix)
    extra_files = tuple(extras)
    mapped = [
        (entry, _safe_relative(f"{prefix}/{entry.path}"))
        for entry in selected
    ]
    for extra in extra_files:
        if not isinstance(extra, ExtraFile) or not isinstance(extra.content, bytes):
            raise TypeError("runtime extra is invalid")
        _safe_relative(extra.path)
        if len(extra.content) > artifact_staging.MAX_TARGET_MEMBER_BYTES:
            raise ValueError("runtime extra exceeds targeted member bound")
    paths = [path for _entry, path in mapped] + [item.path for item in extra_files]
    if len(paths) > artifact_staging.MAX_ENTRIES:
        raise ValueError("runtime entry count exceeds bound")
    if len(paths) != len(set(paths)) or len(paths) != len({path.casefold() for path in paths}):
        raise ValueError("runtime paths collide")
    return tuple(mapped), extra_files


def _copy_member(held, entry, destination: str, root_fd: int, total: list[int]):
    source, before = artifact_staging._open_verified_held_file(
        held, entry.path, entry, artifact_staging.MAX_FILE_BYTES
    )
    parent_fds = []
    output = None
    digest = hashlib.sha256()
    copied = 0
    try:
        parent, parent_fds = artifact_staging._destination_parent(
            root_fd, PurePosixPath(destination).parts[:-1]
        )
        mode = 0o700 if entry.mode_class == "executable" else 0o600
        output = workspace_lease.create_secure_file(
            parent, PurePosixPath(destination).name, mode
        )
        while chunk := os.read(source, artifact_staging.SCAN_HANDOFF_CHUNK_BYTES):
            held.proof_budget.check()
            copied += len(chunk)
            total[0] += len(chunk)
            held.proof_budget.charge("artifact", byte_count=len(chunk))
            if copied > entry.size or total[0] > artifact_staging.MAX_TOTAL_BYTES:
                raise ValueError("runtime streaming copy exceeds bounds")
            artifact_staging._write_all(output, chunk)
            digest.update(chunk)
        after = os.fstat(source)
        if artifact_staging._stable_member(after) != artifact_staging._stable_member(before):
            raise ValueError("runtime source changed while streaming")
        source_entry = artifact_staging.ManifestEntry(
            entry.path, artifact_staging._member_mode(after), copied, digest.hexdigest()
        )
        if source_entry != entry:
            raise ValueError("runtime source manifest mismatch")
        return artifact_staging.ManifestEntry(
            destination, entry.mode_class, copied, digest.hexdigest()
        )
    finally:
        if output is not None:
            os.close(output)
        for descriptor in reversed(parent_fds):
            os.close(descriptor)
        os.close(source)


def _write_extra(root_fd: int, extra: ExtraFile, total: list[int]):
    parent_fds = []
    output = None
    try:
        path = PurePosixPath(extra.path)
        parent, parent_fds = artifact_staging._destination_parent(
            root_fd, path.parts[:-1]
        )
        output = workspace_lease.create_secure_file(
            parent, path.name, 0o700 if extra.executable else 0o600
        )
        total[0] += len(extra.content)
        if total[0] > artifact_staging.MAX_TOTAL_BYTES:
            raise ValueError("runtime extras exceed total bound")
        artifact_staging._write_all(output, extra.content)
        return artifact_staging.ManifestEntry(
            extra.path,
            "executable" if extra.executable else "regular",
            len(extra.content),
            hashlib.sha256(extra.content).hexdigest(),
        )
    finally:
        if output is not None:
            os.close(output)
        for descriptor in reversed(parent_fds):
            os.close(descriptor)


def _expected_kinds(manifest) -> dict[str, str]:
    kinds = {}
    for entry in manifest:
        parts = PurePosixPath(entry.path).parts
        for index in range(1, len(parts)):
            kinds[PurePosixPath(*parts[:index]).as_posix()] = "directory"
        kinds[entry.path] = "file"
    return kinds


def _populate(held, root_fd, mapped, extras):
    held.proof_budget.begin("artifact")
    total = [0]
    observed = []
    for entry, destination in mapped:
        held.proof_budget.check()
        held.proof_budget.charge("artifact", entries=1)
        observed.append(_copy_member(held, entry, destination, root_fd, total))
    observed.extend(_write_extra(root_fd, extra, total) for extra in extras)
    return tuple(sorted(observed, key=lambda item: item.path))


def _verify_destination(lease_fd, root_fd, expected) -> None:
    manifest = artifact_staging._manifest_from_fd(root_fd, "canonical")
    if manifest != expected:
        raise ValueError("synthesized runtime manifest mismatch")
    if artifact_staging._filesystem_kinds_from_fd(root_fd) != _expected_kinds(expected):
        raise ValueError("synthesized runtime filesystem graph mismatch")
    current = os.stat("artifact", dir_fd=lease_fd, follow_symlinks=False)
    opened = os.fstat(root_fd)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise ValueError("synthesized runtime root changed")


def stage_prefixed_runtime(held, prefix: str, members, extras=(), parent=None):
    """Stream exact held members plus bounded trusted extras into runtime."""
    selected = _selection(held, members)
    mapped, extra_files = _destinations(prefix, selected, extras)
    role = artifact_staging.StageRole.SYNTHESIZED_RUNTIME
    lease = workspace_lease.create_ephemeral(
        parent, workspace_lease.WorkspacePurpose.ARTIFACT_EXECUTION
    )
    root = lease.root / "artifact"
    try:
        lease_fd = artifact_staging._verified_lease_fd(lease)
        root_fd = artifact_staging._create_artifact_root(lease_fd)
        expected = _populate(held, root_fd, mapped, extra_files)
        held.proof_budget.check()
        _verify_destination(lease_fd, root_fd, expected)
        held.proof_budget.check()
        os.close(root_fd)
        os.close(lease_fd)
        staged = artifact_staging.StagedTree(lease, root, expected, role, None, False)
        return artifact_staging._register_staged(staged, role)
    except Exception as primary:
        for name in ("root_fd", "lease_fd"):
            if name in locals():
                try:
                    os.close(locals()[name])
                except OSError:
                    pass
        artifact_staging._raise_after_staging_cleanup(
            primary, "synthesized_runtime", role, lease, root
        )
