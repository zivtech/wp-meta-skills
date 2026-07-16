"""Unified bounded no-follow proofs for canonical Docker bind sources."""
from __future__ import annotations

import hashlib
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

import artifact_staging

HOST_PROOF_SECONDS = 180
ARTIFACT_PASS_LIMIT = 6
ARTIFACT_AGGREGATE_ENTRIES = 60_000
ARTIFACT_AGGREGATE_BYTES = 3 * 1024**3
PROXY_PASS_LIMIT = 6
PROXY_AGGREGATE_ENTRIES = 6
PROXY_AGGREGATE_BYTES = 6 * 1024**2


@dataclass(frozen=True)
class RootIdentity:
    device: int
    inode: int
    kind: str
    mode: int
    uid: int
    gid: int


@dataclass(frozen=True)
class SourceProof:
    root: RootIdentity
    manifest: tuple[artifact_staging.ManifestEntry, ...]
    path_kinds: tuple[tuple[str, str], ...]
    total_bytes: int
    entries: int


@dataclass(frozen=True)
class FileProof:
    root: RootIdentity
    size: int
    sha256: str


@dataclass
class ProofBudget:
    clock: object = time.monotonic
    deadline: float | None = None
    artifact_passes: int = 0
    artifact_entries: int = 0
    artifact_bytes: int = 0
    proxy_passes: int = 0
    proxy_entries: int = 0
    proxy_bytes: int = 0

    def check(self) -> None:
        now = self.clock()
        if self.deadline is None:
            self.deadline = now + HOST_PROOF_SECONDS
        if now >= self.deadline:
            raise TimeoutError("host source proof deadline exceeded")

    def begin(self, kind: str) -> None:
        self.check()
        attribute = f"{kind}_passes"
        limit = ARTIFACT_PASS_LIMIT if kind == "artifact" else PROXY_PASS_LIMIT
        value = getattr(self, attribute) + 1
        if value > limit:
            raise RuntimeError(f"{kind} source proof pass budget exceeded")
        setattr(self, attribute, value)

    def charge(self, kind: str, entries: int = 0, byte_count: int = 0) -> None:
        self.check()
        entry_attribute = f"{kind}_entries"; byte_attribute = f"{kind}_bytes"
        entry_limit = ARTIFACT_AGGREGATE_ENTRIES if kind == "artifact" else PROXY_AGGREGATE_ENTRIES
        byte_limit = ARTIFACT_AGGREGATE_BYTES if kind == "artifact" else PROXY_AGGREGATE_BYTES
        new_entries = getattr(self, entry_attribute) + entries; new_bytes = getattr(self, byte_attribute) + byte_count
        if new_entries > entry_limit or new_bytes > byte_limit:
            raise RuntimeError(f"{kind} source proof aggregate budget exceeded")
        setattr(self, entry_attribute, new_entries); setattr(self, byte_attribute, new_bytes)


@dataclass
class _WalkState:
    budget: ProofBudget
    policy: str
    manifest: list = field(default_factory=list)
    kinds: dict = field(default_factory=dict)
    seen: set = field(default_factory=set)
    folded: set = field(default_factory=set)
    total_bytes: int = 0
    entries: int = 0


def _identity(info: os.stat_result) -> RootIdentity:
    kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
    return RootIdentity(info.st_dev, info.st_ino, kind, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)


def _stable(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_canonical_directory(path: Path) -> int:
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}: raise ValueError("unsafe canonical source component")
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor); raise


def open_canonical_file(path: Path) -> int:
    parent = open_canonical_directory(path.parent)
    try: return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    finally: os.close(parent)


def _register(path: Path, kind: str, state: _WalkState) -> None:
    state.budget.check(); normalized = path.as_posix(); folded = normalized.casefold()
    state.entries += 1; state.budget.charge("artifact", entries=1)
    if state.entries > artifact_staging.MAX_ENTRIES or len(path.parts) > artifact_staging.MAX_DEPTH or len(normalized.encode()) > artifact_staging.MAX_PATH_BYTES:
        raise ValueError("artifact proof entry bounds exceeded")
    if normalized in state.seen or folded in state.folded: raise ValueError("artifact proof duplicate or case-fold collision")
    state.seen.add(normalized); state.folded.add(folded); state.kinds[normalized] = kind


def _read_file(parent_fd: int, name: str, path: Path, before: os.stat_result, state: _WalkState) -> None:
    if before.st_nlink != 1 or before.st_size > artifact_staging.MAX_FILE_BYTES: raise ValueError("artifact proof file bounds or link violation")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _stable(opened) != _stable(before): raise ValueError("artifact file changed while opening")
        digest = hashlib.sha256(); size = 0
        while True:
            state.budget.check(); chunk = os.read(descriptor, min(65536, artifact_staging.MAX_FILE_BYTES - size + 1))
            if not chunk: break
            size += len(chunk); state.total_bytes += len(chunk); state.budget.charge("artifact", byte_count=len(chunk))
            if size > artifact_staging.MAX_FILE_BYTES or state.total_bytes > artifact_staging.MAX_TOTAL_BYTES: raise ValueError("artifact proof byte bounds exceeded")
            digest.update(chunk)
        if _stable(os.fstat(descriptor)) != _stable(opened) or size != opened.st_size: raise ValueError("artifact file changed while reading")
        mode = "executable" if stat.S_IMODE(opened.st_mode) & 0o111 else "regular"
        state.manifest.append(artifact_staging.ManifestEntry(path.as_posix(), mode, size, digest.hexdigest()))
    finally: os.close(descriptor)


def _walk(descriptor: int, relative: Path, state: _WalkState) -> None:
    state.budget.check(); before_directory = os.fstat(descriptor)
    for name in sorted(os.listdir(descriptor)):
        state.budget.check(); path = relative / name
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if not relative.parts and name in artifact_staging.DEPENDENCY_ROOTS and state.policy == "exclude":
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or (info.st_uid, info.st_gid) != (os.getuid(), os.getgid()): raise ValueError("dependency exclusion root is not a real directory")
            continue
        if stat.S_ISLNK(info.st_mode): raise ValueError("artifact proof contains symlink")
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != 0o700 or (info.st_uid, info.st_gid) != (os.getuid(), os.getgid()): raise ValueError("artifact proof directory mode or owner is invalid")
            _register(path, "directory", state)
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                opened = os.fstat(child)
                if _stable(opened) != _stable(info): raise ValueError("artifact directory changed while opening")
                _walk(child, path, state)
                if _stable(os.fstat(child)) != _stable(opened): raise ValueError("artifact directory changed while traversing")
            finally: os.close(child)
        elif stat.S_ISREG(info.st_mode):
            mode = stat.S_IMODE(info.st_mode)
            if mode not in {0o600, 0o700} or (info.st_uid, info.st_gid) != (os.getuid(), os.getgid()): raise ValueError("artifact proof file mode or owner is invalid")
            _register(path, "file", state); _read_file(descriptor, name, path, info, state)
        else: raise ValueError("artifact proof contains special node")
    if _stable(os.fstat(descriptor)) != _stable(before_directory): raise ValueError("artifact directory changed while listing")


def prove_artifact(descriptor: int, budget: ProofBudget, policy: str = "canonical") -> SourceProof:
    if policy not in {"canonical", "exclude"}: raise ValueError("unknown artifact proof policy")
    budget.begin("artifact"); root_info = os.fstat(descriptor); root = _identity(root_info)
    if root.kind != "directory" or root.mode != 0o700 or (root.uid, root.gid) != (os.getuid(), os.getgid()): raise ValueError("artifact proof root identity is invalid")
    state = _WalkState(budget, policy); _walk(descriptor, Path(), state)
    return SourceProof(root, tuple(sorted(state.manifest, key=lambda item:item.path)), tuple(sorted(state.kinds.items())), state.total_bytes, state.entries)


def prove_proxy(descriptor: int, budget: ProofBudget) -> FileProof:
    budget.begin("proxy"); before = os.fstat(descriptor); root = _identity(before)
    if root.kind != "file" or root.mode != 0o400 or before.st_nlink != 1 or before.st_size > 1024**2 or (root.uid,root.gid)!=(os.getuid(),os.getgid()): raise ValueError("proxy source identity is invalid")
    duplicate = os.dup(descriptor); os.lseek(duplicate, 0, os.SEEK_SET); digest = hashlib.sha256(); size = 0
    try:
        budget.charge("proxy", entries=1)
        while True:
            budget.check(); chunk = os.read(duplicate, min(65536, 1024**2-size+1))
            if not chunk: break
            size += len(chunk); budget.charge("proxy", byte_count=len(chunk))
            if size > 1024**2: raise ValueError("proxy source exceeds one MiB")
            digest.update(chunk)
        if _stable(os.fstat(duplicate)) != _stable(before) or size != before.st_size: raise ValueError("proxy source changed while reading")
        return FileProof(root,size,digest.hexdigest())
    finally: os.close(duplicate)
