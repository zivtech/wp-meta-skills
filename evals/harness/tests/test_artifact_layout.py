"""Manifest-only block metadata layout selection contracts."""
from __future__ import annotations

import dataclasses
import hashlib
import sys
from pathlib import Path, PurePosixPath

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_layout
import artifact_staging


def manifest(*paths: str) -> tuple[artifact_staging.ManifestEntry, ...]:
    entries = []
    for path in paths:
        content = path.encode("utf-8")
        entries.append(
            artifact_staging.ManifestEntry(
                path, "regular", len(content), hashlib.sha256(content).hexdigest()
            )
        )
    return tuple(entries)


def test_source_layout_selects_the_only_unexcluded_block_metadata():
    entries = manifest(
        "blocks/card/block.json",
        "blocks/card/render.php",
        "vendor/package/block.json",
        "coverage/report/block.json",
    )

    layout = artifact_layout.select_source_layout(entries)

    assert layout.source_root == PurePosixPath("blocks/card")
    assert layout.source_block_json == PurePosixPath("blocks/card/block.json")
    assert layout.candidate_build_root == PurePosixPath("blocks/card/build")
    assert layout.manifest_sha256 == artifact_staging.manifest_sha256(entries)


def test_source_layout_supports_metadata_at_the_artifact_root():
    layout = artifact_layout.select_source_layout(manifest("block.json", "render.php"))

    assert layout.source_root == PurePosixPath(".")
    assert layout.candidate_build_root == PurePosixPath("build")


@pytest.mark.parametrize(
    "paths,match",
    [
        (("readme.txt",), "exactly one"),
        (("one/block.json", "two/block.json"), "ambiguous"),
        (("../block.json",), "unsafe manifest path"),
        (("/absolute/block.json",), "unsafe manifest path"),
    ],
)
def test_source_layout_rejects_missing_ambiguous_or_unsafe_metadata(paths, match):
    with pytest.raises(ValueError, match=match):
        artifact_layout.select_source_layout(manifest(*paths))


def test_layout_values_are_frozen_and_use_pure_paths():
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))
    selected = artifact_layout.select_post_build_layout(
        manifest("blocks/card/block.json"), source
    )

    assert isinstance(source.source_root, PurePosixPath)
    assert isinstance(selected.selected_root, PurePosixPath)
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.source_root = PurePosixPath("elsewhere")
    with pytest.raises(dataclasses.FrozenInstanceError):
        selected.selected_root = PurePosixPath("elsewhere")


def test_post_build_layout_falls_back_to_the_exact_source_root():
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))
    entries = manifest("blocks/card/block.json", "blocks/card/render.php")

    layout = artifact_layout.select_post_build_layout(entries, source)

    assert layout.selected_root == PurePosixPath("blocks/card")
    assert layout.selected_block_json == PurePosixPath("blocks/card/block.json")
    assert layout.selection_reason == "source_block_json"
    assert layout.manifest_sha256 == artifact_staging.manifest_sha256(entries)


def test_post_build_layout_prefers_only_the_exact_child_build_metadata():
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))
    entries = manifest(
        "blocks/card/block.json",
        "blocks/card/build/block.json",
        "blocks/card/build/render.php",
    )

    layout = artifact_layout.select_post_build_layout(entries, source)

    assert layout.selected_root == PurePosixPath("blocks/card/build")
    assert layout.selected_block_json == PurePosixPath("blocks/card/build/block.json")
    assert layout.selection_reason == "built_block_json"


@pytest.mark.parametrize(
    "extra",
    [
        "blocks/other/block.json",
        "blocks/card/dist/block.json",
        "blocks/card/build/nested/block.json",
    ],
)
def test_post_build_layout_rejects_every_other_plausible_metadata_root(extra):
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))
    entries = manifest(
        "blocks/card/block.json", "blocks/card/build/block.json", extra
    )

    with pytest.raises(ValueError, match="ambiguous"):
        artifact_layout.select_post_build_layout(entries, source)


def test_post_build_layout_ignores_metadata_below_excluded_roots():
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))
    entries = manifest(
        "blocks/card/block.json",
        "blocks/card/build/block.json",
        "node_modules/package/block.json",
        ".git/objects/block.json",
    )

    layout = artifact_layout.select_post_build_layout(entries, source)

    assert layout.selection_reason == "built_block_json"


def test_post_build_layout_requires_the_anchored_source_metadata_to_remain():
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))

    with pytest.raises(ValueError, match="missing source block.json"):
        artifact_layout.select_post_build_layout(
            manifest("blocks/card/build/block.json"), source
        )


def test_post_build_layout_rejects_a_forged_source_layout():
    source = artifact_layout.select_source_layout(manifest("blocks/card/block.json"))
    forged = dataclasses.replace(
        source, candidate_build_root=PurePosixPath("somewhere/build")
    )

    with pytest.raises(ValueError, match="source layout is inconsistent"):
        artifact_layout.select_post_build_layout(
            manifest("blocks/card/block.json"), forged
        )
