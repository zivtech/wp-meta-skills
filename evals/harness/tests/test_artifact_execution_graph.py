"""Authenticated block execution-graph and proof contracts."""
from __future__ import annotations

import dataclasses
import io
import json
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_execution_graph as graph
import artifact_layout
import artifact_staging


def _tar(files: dict[str, bytes]) -> io.BytesIO:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    stream.seek(0)
    return stream


def _source_manifest(path: str = "blocks/card/block.json"):
    content = b"{}"
    return (
        artifact_staging.ManifestEntry(
            path, "regular", len(content), graph.sha256_bytes(content)
        ),
    )


@contextmanager
def _held_proof(tmp_path: Path, files: dict[str, bytes]):
    staged = artifact_staging.import_tar_stream(_tar(files), tmp_path / "output")
    source = artifact_layout.select_source_layout(_source_manifest())
    layout = artifact_layout.select_post_build_layout(staged.manifest, source)
    try:
        with artifact_staging.hold_staged_tree(staged) as held:
            yield held, layout
    finally:
        artifact_staging.cleanup_staged_tree(staged)


def _metadata(**overrides) -> bytes:
    payload = {
        "name": "test/card",
        "title": "Card",
        "category": "widgets",
        **overrides,
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _valid_files(metadata: bytes | None = None) -> dict[str, bytes]:
    return {
        "blocks/card/block.json": _metadata(),
        "blocks/card/build/block.json": metadata
        or _metadata(
            render="file:./render.php",
            variations="file:../variations.inc",
            editorScript=["file:./index.js", "wp-element"],
            viewScriptModule="file:./view.js",
            style=["file:./style.css", "global-style"],
            viewStyle="file:../shared.css",
        ),
        "blocks/card/build/render.php": b"<?php echo 'safe';",
        "blocks/card/variations.inc": b"<?PHP return [];",
        "blocks/card/build/index.js": b"void 0;",
        "blocks/card/build/index.asset.php": b"<?php return [];",
        "blocks/card/build/view.js": b"export {};",
        "blocks/card/build/view.asset.php": b"<?php return [];",
        "blocks/card/build/style.css": b".card{}",
        "blocks/card/build/style-rtl.css": b".card{}",
        "blocks/card/build/chunk.js": b"export const chunk = true;",
        "blocks/card/shared.css": b".shared{}",
        "blocks/card/notes.txt": b"not part of the selected runtime closure",
        "blocks/card/generated.PHP": b"short-tag negative space",
        "blocks/card/payload.txt": b"prefix <?Php echo 'found'; suffix",
    }


def _edges(proof, field: str):
    return tuple(edge for edge in proof.edges if edge.field == field)


def _wrapper_bytes(selected_block_json: str, suffix: bytes = b"") -> bytes:
    return graph.block_runtime_wrapper.build("test-card", selected_block_json) + suffix


def _bind_runtime(proof, wrapper_bytes: bytes, manifest: str = "a" * 64):
    validation = graph.build_wrapper_validation(
        wrapper_bytes, proof.selected_block_json, php_syntax_passed=True
    )
    return graph.bind_runtime_proof(
        proof, "plugin/block-wrapper.php", wrapper_bytes, manifest, validation
    )


def test_builds_frozen_canonical_proof_from_held_output(tmp_path):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        proof = graph.build_execution_proof(held, layout)
        repeated = graph.build_execution_proof(held, layout)

    assert proof == repeated
    assert proof.selection_reason == "built_block_json"
    assert proof.selected_block_json == "blocks/card/build/block.json"
    assert proof.output_manifest_sha256 == layout.manifest_sha256
    assert proof.core == graph.PINNED_WORDPRESS_CORE
    assert proof.rule_digest == graph.WORDPRESS_7_0_1_RULE_DIGEST
    assert len(proof.metadata_graph_digest) == 64
    assert len(proof.php_set_digest) == 64
    assert len(proof.artifact_proof_digest) == 64
    assert {candidate.path for candidate in proof.php_candidates} >= {
        "blocks/card/build/render.php",
        "blocks/card/variations.inc",
        "blocks/card/generated.PHP",
        "blocks/card/payload.txt",
        "blocks/card/build/index.asset.php",
        "blocks/card/build/view.asset.php",
    }
    assert ("editorScript", "handle", "wp-element") in {
        (edge.field, edge.kind, edge.reference) for edge in proof.edges
    }
    assert any(
        edge.kind == "asset_php" and edge.state == "present"
        for edge in _edges(proof, "editorScript")
    )
    assert any(
        edge.kind == "rtl_style" and edge.state == "present"
        for edge in _edges(proof, "style")
    )
    assert any(
        edge.kind == "rtl_style" and edge.state == "absent"
        for edge in _edges(proof, "viewStyle")
    )
    payload_scan = next(
        scan for scan in proof.scan_files if scan.path == "blocks/card/payload.txt"
    )
    assert payload_scan.scan_ids == graph.PHP_SCAN_IDS
    chunk = next(
        item for item in proof.files if item.path == "blocks/card/build/chunk.js"
    )
    assert "runtime_asset" in chunk.classifications
    assert "blocks/card/notes.txt" not in {item.path for item in proof.files}
    with pytest.raises(dataclasses.FrozenInstanceError):
        proof.selected_root = "changed"


def test_source_fallback_uses_the_same_authenticated_graph_path(tmp_path):
    files = {
        "blocks/card/block.json": _metadata(render="file:./render.php"),
        "blocks/card/render.php": b"<?php return '';",
    }
    with _held_proof(tmp_path, files) as (held, layout):
        proof = graph.build_execution_proof(held, layout)

    assert proof.selection_reason == "source_block_json"
    assert proof.selected_root == "blocks/card"
    assert _edges(proof, "render")[0].target == "blocks/card/render.php"


@pytest.mark.parametrize(
    "metadata,match",
    [
        (b'{"name":"test/card","name":"duplicate"}', "duplicate"),
        (b'{"name":"test/card","value":NaN}', "constant"),
        (b"\xff", "UTF-8"),
        (json.dumps([[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]).encode(), "depth"),
    ],
)
def test_rejects_non_strict_or_overdeep_metadata(tmp_path, metadata, match):
    files = _valid_files(metadata)
    with _held_proof(tmp_path, files) as (held, layout):
        with pytest.raises(ValueError, match=match):
            graph.build_execution_proof(held, layout)


def test_rejects_metadata_over_one_mib(tmp_path):
    metadata = b'{"name":"test/card","padding":"' + b"x" * (1024 * 1024) + b'"}'
    with _held_proof(tmp_path, _valid_files(metadata)) as (held, layout):
        with pytest.raises(ValueError, match="1 MiB"):
            graph.build_execution_proof(held, layout)


def test_rejects_missing_required_block_metadata(tmp_path):
    metadata = b'{"name":"test/card"}'
    with _held_proof(tmp_path, _valid_files(metadata)) as (held, layout):
        with pytest.raises(ValueError, match="title, category"):
            graph.build_execution_proof(held, layout)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("render", "wp-handle", "render"),
        ("render", ["file:./render.php"], "render"),
        ("variations", "wp-handle", "variations"),
        ("script", [["wp-element"]], "flat"),
        ("script", ["wp-element", 7], "string"),
        ("style", "https://example.test/style.css", "scheme"),
        ("style", "//example.test/style.css", "scheme"),
        ("viewScriptModule", "fileish:module", "scheme"),
        ("editorScript", ["file:./index.js", "file:index.js"], "duplicate"),
    ],
)
def test_enforces_exact_field_shapes_and_handle_semantics(
    tmp_path, field, value, match
):
    metadata = _metadata(**{field: value})
    with _held_proof(tmp_path, _valid_files(metadata)) as (held, layout):
        with pytest.raises(ValueError, match=match):
            graph.build_execution_proof(held, layout)


@pytest.mark.parametrize(
    "target,match",
    [
        ("file:../../../../escape.php", "escape"),
        ("file:/absolute.php", "absolute"),
        ("file:.\\render.php", "backslash"),
        ("file:https://example.test/render.php", "scheme"),
        ("file:./missing.php", "missing"),
        ("file:../../../vendor/package/render.php", "excluded"),
        ("file:./bad\n.php", "control"),
    ],
)
def test_rejects_unsafe_or_unverified_local_targets(tmp_path, target, match):
    metadata = _metadata(render=target)
    with _held_proof(tmp_path, _valid_files(metadata)) as (held, layout):
        with pytest.raises(ValueError, match=match):
            graph.build_execution_proof(held, layout)


def test_uses_exact_core_asset_and_rtl_transformations(tmp_path):
    metadata = _metadata(
        script="file:./module.mjs", style="file:./name.css.map.css"
    )
    files = _valid_files(metadata)
    files.update(
        {
            "blocks/card/build/module.mjs": b"export {};",
            "blocks/card/build/module..asset.php": b"<?php return [];",
            "blocks/card/build/name.css.map.css": b"body{}",
            "blocks/card/build/name-rtl.css.map-rtl.css": b"body{}",
        }
    )
    with _held_proof(tmp_path, files) as (held, layout):
        proof = graph.build_execution_proof(held, layout)

    assert any(
        edge.kind == "asset_php"
        and edge.target == "blocks/card/build/module..asset.php"
        for edge in proof.edges
    )
    assert any(
        edge.kind == "rtl_style"
        and edge.target == "blocks/card/build/name-rtl.css.map-rtl.css"
        for edge in proof.edges
    )


def test_asset_transform_runs_on_core_relative_path_before_resolution(tmp_path):
    files = _valid_files(_metadata(script="file:./a"))
    files["blocks/card/build/a"] = b"script"
    files["blocks/card/build/.asset.php"] = b"<?php return [];"
    with _held_proof(tmp_path, files) as (held, layout):
        proof = graph.build_execution_proof(held, layout)

    assert any(
        edge.kind == "asset_php"
        and edge.target == "blocks/card/build/.asset.php"
        and edge.state == "present"
        for edge in proof.edges
    )


def test_rejects_an_implicit_companion_that_is_a_directory(tmp_path):
    files = _valid_files()
    files.pop("blocks/card/build/index.asset.php")
    files["blocks/card/build/index.asset.php/inside.txt"] = b"not a companion"
    with _held_proof(tmp_path, files) as (held, layout):
        with pytest.raises(ValueError, match="directory"):
            graph.build_execution_proof(held, layout)


def test_rejects_executable_php_candidates_in_excluded_roots(tmp_path):
    files = _valid_files()
    # Dependency roots are discarded by the authenticated import seam; coverage
    # remains present in the held manifest and must be rejected here.
    files["coverage/report/payload.txt"] = b"<?php echo 'unsafe';"
    with _held_proof(tmp_path, files) as (held, layout):
        with pytest.raises(ValueError, match="excluded"):
            graph.build_execution_proof(held, layout)


def test_selected_root_non_php_excluded_namespaces_stay_out_of_proof(tmp_path):
    files = _valid_files()
    excluded = {
        "blocks/card/build/coverage/report.js",
        "blocks/card/build/.git/config",
        "blocks/card/build/.wp-env/state.json",
    }
    files.update({path: b"not executable" for path in excluded})
    with _held_proof(tmp_path, files) as (held, layout):
        proof = graph.build_execution_proof(held, layout)

    assert excluded.isdisjoint(item.path for item in proof.files)
    assert excluded.isdisjoint(item.path for item in proof.scan_files)


def test_rejects_unsupported_executable_php_candidate_names(tmp_path):
    files = _valid_files()
    files["blocks/card/bad\nname.php"] = b"<?php echo 'unsafe';"
    with _held_proof(tmp_path, files) as (held, layout):
        with pytest.raises(ValueError, match="candidate path"):
            graph.build_execution_proof(held, layout)


def test_candidate_and_edge_caps_are_fail_closed(tmp_path, monkeypatch):
    files = _valid_files(_metadata())
    with _held_proof(tmp_path, files) as (held, layout):
        monkeypatch.setattr(graph, "MAX_PHP_CANDIDATES", 1)
        with pytest.raises(ValueError, match="candidate count"):
            graph.build_execution_proof(held, layout)

    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        monkeypatch.setattr(graph, "MAX_PHP_CANDIDATES", 2048)
        monkeypatch.setattr(graph, "MAX_METADATA_EDGES", 1)
        with pytest.raises(ValueError, match="edge count"):
            graph.build_execution_proof(held, layout)


def test_candidate_byte_cap_is_fail_closed(tmp_path, monkeypatch):
    with _held_proof(tmp_path, _valid_files(_metadata())) as (held, layout):
        monkeypatch.setattr(graph, "MAX_PHP_BYTES", 1)
        with pytest.raises(ValueError, match="candidate bytes"):
            graph.build_execution_proof(held, layout)


def test_block_output_byte_cap_is_fail_closed(tmp_path, monkeypatch):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        monkeypatch.setattr(graph, "MAX_BLOCK_OUTPUT_BYTES", 1)
        with pytest.raises(ValueError, match="block output"):
            graph.build_execution_proof(held, layout)


def test_block_output_entry_cap_is_fail_closed(tmp_path, monkeypatch):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        monkeypatch.setattr(graph, "MAX_BLOCK_ENTRIES", 1)
        with pytest.raises(ValueError, match="1024-file"):
            graph.build_execution_proof(held, layout)


@pytest.mark.parametrize(
    "limit_name,match",
    [
        ("MAX_RUNTIME_FILE_BYTES", "runtime closure member"),
        ("MAX_RUNTIME_CLOSURE_BYTES", "runtime closure exceeds"),
    ],
)
def test_runtime_closure_byte_caps_are_fail_closed(
    tmp_path, monkeypatch, limit_name, match
):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        monkeypatch.setattr(graph, limit_name, 1)
        with pytest.raises(ValueError, match=match):
            graph.build_execution_proof(held, layout)


def test_unknown_core_or_blocks_source_drift_stops(tmp_path):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        drifted = dataclasses.replace(graph.PINNED_WORDPRESS_CORE, version="7.0.2")
        with pytest.raises(ValueError, match="unreviewed WordPress core"):
            graph.build_execution_proof(held, layout, core=drifted)


def test_layout_manifest_mismatch_and_forged_held_capability_fail(tmp_path):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        mismatch = dataclasses.replace(layout, manifest_sha256="0" * 64)
        with pytest.raises(ValueError, match="layout manifest"):
            graph.build_execution_proof(held, mismatch)
        forged = dataclasses.replace(held)
        with pytest.raises(ValueError, match="authentic"):
            graph.build_execution_proof(forged, layout)


def test_bind_runtime_proof_binds_wrapper_and_synthesized_manifest(tmp_path):
    with _held_proof(tmp_path, _valid_files()) as (held, layout):
        proof = graph.build_execution_proof(held, layout)

    wrapper = _wrapper_bytes(proof.selected_block_json)
    bound = _bind_runtime(proof, wrapper)
    changed = _bind_runtime(proof, wrapper, "b" * 64)
    assert bound.artifact == proof
    assert bound.wrapper_sha256 == changed.wrapper_sha256
    assert bound.execution_proof_digest != changed.execution_proof_digest
    assert bound.synthesized_manifest_sha256 == "a" * 64
    graph.validate_runtime_proof(bound)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bound.wrapper_path = "changed"
    with pytest.raises(ValueError, match="wrapper path"):
        graph.bind_runtime_proof(
            proof, "../wrapper.php", wrapper, "a" * 64,
            graph.build_wrapper_validation(
                wrapper, proof.selected_block_json, php_syntax_passed=True
            ),
        )
    with pytest.raises(ValueError, match="manifest digest"):
        graph.bind_runtime_proof(
            proof, "wrapper.php", wrapper, "bad",
            graph.build_wrapper_validation(
                wrapper, proof.selected_block_json, php_syntax_passed=True
            ),
        )
    forged = dataclasses.replace(proof, artifact_proof_digest="0" * 64)
    with pytest.raises(ValueError, match="digest binding"):
        graph.bind_runtime_proof(
            forged, "wrapper.php", wrapper, "a" * 64,
            graph.build_wrapper_validation(
                wrapper, proof.selected_block_json, php_syntax_passed=True
            ),
        )
    forged_runtime = dataclasses.replace(bound, execution_proof_digest="0" * 64)
    with pytest.raises(ValueError, match="execution proof digest"):
        graph.validate_runtime_proof(forged_runtime)


def test_rule_digest_is_a_reviewed_literal():
    assert graph.PINNED_WORDPRESS_CORE.blocks_php_sha256 == (
        "b8b44cb18d6ae7526a36fd3a5fd08c411f3af6c07aba85b3feb34563ed0ad321"
    )
    assert len(graph.WORDPRESS_7_0_1_RULE_DIGEST) == 64
    assert graph.WORDPRESS_7_0_1_RULE_DIGEST == (
        "3e139b0744e41a23dd9638724d5d9c68238187770953765da98786ce6c674207"
    )


@pytest.mark.parametrize(
    "extra",
    [
        b"register_block_type ( 'other' );\n",
        b"\\register_block_type( 'other' );\n",
        b"/* register_block_type ( 'other' ); */\n",
        b"$text = 'register_block_type ( other )';\n",
        b"REGISTER_BLOCK_TYPE( 'other' );\n",
        b"Register_Block_Type ( 'other' );\n",
        b"register_block_type/**/( 'other' );\n",
        b"register_block_type /* drift */ ( 'other' );\n",
    ],
)
def test_wrapper_contract_rejects_extra_or_ambiguous_bootstraps(extra):
    selected = "blocks/card/build/block.json"
    with pytest.raises(ValueError, match="exact registration bootstrap"):
        graph.build_wrapper_validation(
            _wrapper_bytes(selected, extra), selected, php_syntax_passed=True
        )


@pytest.mark.parametrize(
    "replacement",
    [
        b"REGISTER_BLOCK_TYPE(",
        b"Register_Block_Type (",
        b"register_block_type/**/(",
        b"register_block_type /* drift */ (",
        b"// register_block_type(",
    ],
)
def test_wrapper_contract_requires_the_canonical_executable_call(replacement):
    selected = "blocks/card/build/block.json"
    wrapper = _wrapper_bytes(selected).replace(b"register_block_type(", replacement)
    with pytest.raises(ValueError, match="exact registration bootstrap"):
        graph.build_wrapper_validation(
            wrapper, selected, php_syntax_passed=True
        )
