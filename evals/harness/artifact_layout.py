"""Deterministic block metadata layout selection from staged manifests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Literal

import artifact_staging


EXCLUDED_ROOTS = frozenset(
    {".git", ".wp-env", "node_modules", "vendor", "sandbox-cache", "coverage"}
)


@dataclass(frozen=True)
class BlockSourceLayout:
    manifest_sha256: str
    source_root: PurePosixPath
    source_block_json: PurePosixPath
    candidate_build_root: PurePosixPath


@dataclass(frozen=True)
class BlockArtifactLayout:
    manifest_sha256: str
    source: BlockSourceLayout
    selected_root: PurePosixPath
    selected_block_json: PurePosixPath
    selection_reason: Literal["built_block_json", "source_block_json"]


def _normalized_manifest(
    manifest: Iterable[artifact_staging.ManifestEntry],
) -> tuple[tuple[PurePosixPath, ...], str]:
    entries = tuple(manifest)
    digest = artifact_staging.manifest_sha256(entries)
    paths = []
    for entry in entries:
        path = PurePosixPath(entry.path)
        unsafe = (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != entry.path
        )
        if unsafe:
            raise ValueError(f"unsafe manifest path: {entry.path!r}")
        paths.append(path)
    return tuple(paths), digest


def _block_candidates(paths: Iterable[PurePosixPath]) -> tuple[PurePosixPath, ...]:
    return tuple(
        sorted(
            path
            for path in paths
            if path.name == "block.json"
            and not any(part in EXCLUDED_ROOTS for part in path.parts[:-1])
        )
    )


def select_source_layout(
    manifest: Iterable[artifact_staging.ManifestEntry],
) -> BlockSourceLayout:
    paths, digest = _normalized_manifest(manifest)
    candidates = _block_candidates(paths)
    if not candidates:
        raise ValueError("source artifact must contain exactly one block.json")
    if len(candidates) != 1:
        rendered = ", ".join(path.as_posix() for path in candidates)
        raise ValueError(f"ambiguous source block.json roots: {rendered}")
    block_json = candidates[0]
    source_root = block_json.parent
    return BlockSourceLayout(
        digest, source_root, block_json, source_root / "build"
    )


def _require_consistent_source(source: BlockSourceLayout) -> None:
    if not isinstance(source, BlockSourceLayout):
        raise TypeError("source layout must be a BlockSourceLayout")
    expected_json = source.source_root / "block.json"
    expected_build = source.source_root / "build"
    valid_digest = len(source.manifest_sha256) == 64 and all(
        character in "0123456789abcdef" for character in source.manifest_sha256
    )
    if (
        source.source_block_json != expected_json
        or source.candidate_build_root != expected_build
        or not valid_digest
    ):
        raise ValueError("source layout is inconsistent")


def select_post_build_layout(
    manifest: Iterable[artifact_staging.ManifestEntry], source: BlockSourceLayout
) -> BlockArtifactLayout:
    _require_consistent_source(source)
    paths, digest = _normalized_manifest(manifest)
    candidates = set(_block_candidates(paths))
    built_json = source.candidate_build_root / "block.json"
    allowed = {source.source_block_json, built_json}
    unexpected = sorted(candidates - allowed)
    if unexpected:
        rendered = ", ".join(path.as_posix() for path in unexpected)
        raise ValueError(f"ambiguous post-build block.json roots: {rendered}")
    if source.source_block_json not in candidates:
        raise ValueError("post-build output is missing source block.json")
    selected = built_json if built_json in candidates else source.source_block_json
    reason = "built_block_json" if selected == built_json else "source_block_json"
    return BlockArtifactLayout(digest, source, selected.parent, selected, reason)
