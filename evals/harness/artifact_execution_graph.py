"""Immutable WordPress block execution graph from an authenticated held stage."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal

import artifact_layout
import artifact_staging
import block_runtime_wrapper


MAX_METADATA_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_METADATA_EDGES = 512
MAX_BLOCK_ENTRIES = 1024
MAX_BLOCK_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_PHP_CANDIDATES = 64
MAX_PHP_BYTES = 8 * 1024 * 1024
MAX_RUNTIME_FILE_BYTES = artifact_staging.MAX_TARGET_MEMBER_BYTES
MAX_RUNTIME_CLOSURE_BYTES = 16 * 1024 * 1024
MAX_WRAPPER_BYTES = 1024 * 1024
PROOF_SCHEMA_VERSION = 1

PHP_SUFFIXES = frozenset(
    {".php", ".php3", ".php4", ".php5", ".php7", ".php8", ".phtml",
     ".pht", ".phar", ".inc", ".module", ".ctp"}
)
PHP_SCAN_IDS = ("php_syntax", "secret", "structural", "wp_api", "wp_security")
ASSET_SCAN_IDS = ("secret", "structural")
METADATA_SCAN_IDS = ("metadata_json", "secret")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class CoreIdentity:
    version: str
    archive_sha256: str
    blocks_php_sha256: str


@dataclass(frozen=True)
class FieldRule:
    field: str
    family: Literal["script", "module", "style"]
    shape: Literal["scalar_or_flat_array"] = "scalar_or_flat_array"


@dataclass(frozen=True)
class MetadataEdge:
    field: str
    index: int
    kind: str
    reference: str
    target: str | None
    state: Literal["present", "absent", "registered"]
    sha256: str | None


@dataclass(frozen=True)
class ExecutionFile:
    path: str
    mode_class: str
    size: int
    sha256: str
    classifications: tuple[str, ...]


@dataclass(frozen=True)
class ScanFile:
    path: str
    scan_ids: tuple[str, ...]


@dataclass(frozen=True)
class BlockExecutionProof:
    schema_version: int
    output_manifest_sha256: str
    source_manifest_sha256: str
    selected_root: str
    selected_block_json: str
    selection_reason: str
    core: CoreIdentity
    rule_digest: str
    edges: tuple[MetadataEdge, ...]
    files: tuple[ExecutionFile, ...]
    php_candidates: tuple[ExecutionFile, ...]
    scan_files: tuple[ScanFile, ...]
    metadata_graph_digest: str
    php_set_digest: str
    artifact_proof_digest: str


@dataclass(frozen=True)
class RuntimeExecutionProof:
    schema_version: int
    artifact: BlockExecutionProof
    wrapper_path: str
    wrapper_size: int
    wrapper_sha256: str
    wrapper_validation_digest: str
    synthesized_manifest_sha256: str
    execution_proof_digest: str


@dataclass(frozen=True)
class WrapperValidation:
    checks: tuple[str, ...]
    digest: str


PINNED_WORDPRESS_CORE = CoreIdentity(
    "7.0.1",
    "dc10592da9b580c7525632850e0cced371b13081853ac29afe93b5d5bb00db98",
    "b8b44cb18d6ae7526a36fd3a5fd08c411f3af6c07aba85b3feb34563ed0ad321",
)
_FIELD_RULES = (
    FieldRule("editorScript", "script"),
    FieldRule("script", "script"),
    FieldRule("viewScript", "script"),
    FieldRule("viewScriptModule", "module"),
    FieldRule("editorStyle", "style"),
    FieldRule("style", "style"),
    FieldRule("viewStyle", "style"),
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_digest(payload) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    return sha256_bytes(encoded)


def _rule_payload() -> dict:
    return {
        "core": asdict(PINNED_WORDPRESS_CORE),
        "render": {"shape": "scalar", "semantics": "required_file_php"},
        "variations": {"shape": "inline_array_or_file_php"},
        "fields": [asdict(rule) for rule in _FIELD_RULES],
        "asset_php": "substr_replace(path,'.asset.php',-strlen('.js'))",
        "rtl_style": "str_replace('.css','-rtl.css',path)",
    }


WORDPRESS_7_0_1_RULE_DIGEST = _canonical_digest(_rule_payload())
_RULES_BY_CORE = MappingProxyType(
    {
        (
            PINNED_WORDPRESS_CORE.version,
            PINNED_WORDPRESS_CORE.archive_sha256,
            PINNED_WORDPRESS_CORE.blocks_php_sha256,
        ): (_FIELD_RULES, WORDPRESS_7_0_1_RULE_DIGEST)
    }
)


def _rules_for_core(core: CoreIdentity):
    if not isinstance(core, CoreIdentity):
        raise TypeError("core identity must be a CoreIdentity")
    key = (core.version, core.archive_sha256, core.blocks_php_sha256)
    rules = _RULES_BY_CORE.get(key)
    if rules is None:
        raise ValueError("unreviewed WordPress core or blocks.php source")
    return rules


def _reject_constant(value: str):
    raise ValueError(f"JSON constant is forbidden: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _check_depth(value, depth: int = 1) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("block.json exceeds maximum JSON depth")
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for child in children:
        _check_depth(child, depth + 1)


def _parse_metadata(content: bytes) -> dict:
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError("block.json exceeds 1 MiB")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("block.json is not strict UTF-8") from exc
    try:
        value = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"block.json is not strict JSON: {exc.msg}") from exc
    _check_depth(value)
    if not isinstance(value, dict):
        raise ValueError("block.json root must be an object")
    invalid = [
        key
        for key in ("name", "title", "category")
        if not isinstance(value.get(key), str) or not value[key].strip()
    ]
    if invalid:
        raise ValueError(
            "block.json missing non-empty string keys: " + ", ".join(invalid)
        )
    return value


def _manifest_index(held) -> dict[str, artifact_staging.ManifestEntry]:
    manifest = tuple(held.proof.manifest)
    index = {entry.path: entry for entry in manifest}
    if len(index) != len(manifest):
        raise ValueError("held manifest contains duplicate paths")
    return index


def _validate_layout(held, layout: artifact_layout.BlockArtifactLayout) -> None:
    if not isinstance(layout, artifact_layout.BlockArtifactLayout):
        raise TypeError("layout must be a BlockArtifactLayout")
    actual = artifact_staging.manifest_sha256(held.proof.manifest)
    if actual != layout.manifest_sha256:
        raise ValueError("layout manifest does not match held output")
    expected = layout.selected_root / "block.json"
    if layout.selected_block_json != expected:
        raise ValueError("layout selected block.json is inconsistent")


def _unsafe_text(value: str) -> str | None:
    if not value:
        return "empty"
    if "\\" in value:
        return "backslash"
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return "control character"
    if _SCHEME.match(value) or value.startswith("//") or "://" in value:
        return "scheme"
    return None


def _lexical_path(base: PurePosixPath, raw: str) -> str:
    problem = _unsafe_text(raw)
    if problem:
        raise ValueError(f"local metadata path contains {problem}")
    if raw.startswith("/"):
        raise ValueError("local metadata path is absolute")
    parts = [] if base.as_posix() == "." else list(base.parts)
    for component in raw.split("/"):
        if component in {"", "."}:
            if component == "":
                raise ValueError("local metadata path has an empty component")
            continue
        if component == "..":
            if not parts:
                raise ValueError("local metadata path escapes staged output")
            parts.pop()
        else:
            parts.append(component)
    if not parts:
        raise ValueError("local metadata path resolves to an empty target")
    target = PurePosixPath(*parts).as_posix()
    if any(part in artifact_layout.EXCLUDED_ROOTS for part in parts):
        raise ValueError("local metadata path targets an excluded namespace")
    return target


def _resolve_path(base: PurePosixPath, raw: str, index, path_kinds) -> str:
    target = _lexical_path(base, raw)
    if path_kinds.get(target) == "directory":
        raise ValueError(f"local metadata path is a directory: {target}")
    if target not in index:
        raise ValueError(f"local metadata path is missing: {target}")
    return target


def _edge(field, position, kind, reference, target, state, index):
    entry = index.get(target) if target is not None and state == "present" else None
    return MetadataEdge(
        field, position, kind, reference, target, state,
        entry.sha256 if entry is not None else None,
    )


def _append(edges: list[MetadataEdge], edge: MetadataEdge) -> None:
    edges.append(edge)
    if len(edges) > MAX_METADATA_EDGES:
        raise ValueError("metadata edge count exceeds limit")


def _optional_edge(field, position, kind, reference, target, index, path_kinds):
    if path_kinds.get(target) == "directory":
        raise ValueError(f"implicit metadata path is a directory: {target}")
    state = "present" if target in index else "absent"
    return _edge(field, position, kind, reference, target, state, index)


def _asset_companion(base, reference, path_kinds) -> str:
    raw = reference[len("file:"):]
    if raw.startswith("./"):
        raw = raw[2:]
    start = max(0, len(raw) - len(".js"))
    target = _lexical_path(base, raw[:start] + ".asset.php")
    if path_kinds.get(target) == "directory":
        raise ValueError(f"implicit metadata path is a directory: {target}")
    return target


def _rtl_companion(target: str) -> str:
    return target.replace(".css", "-rtl.css")


def _validate_handle(value: str) -> None:
    problem = _unsafe_text(value)
    if problem:
        raise ValueError(f"registered handle contains {problem}")
    if value != value.strip():
        raise ValueError("registered handle contains surrounding whitespace")


def _field_values(metadata: dict, rule: FieldRule) -> tuple[str, ...]:
    value = metadata[rule.field]
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise ValueError(f"{rule.field} must be a string or flat string array")
    if any(not isinstance(item, str) for item in value):
        detail = "flat" if any(isinstance(item, list) for item in value) else "string"
        raise ValueError(f"{rule.field} must be a {detail} string array")
    return tuple(value)


def _add_local_edges(edges, field, position, family, value, base, index, path_kinds):
    target = _resolve_path(base, value[len("file:"):], index, path_kinds)
    kind = {"script": "script", "module": "script_module", "style": "style"}[family]
    _append(edges, _edge(field, position, kind, value, target, "present", index))
    if family in {"script", "module"}:
        companion = _asset_companion(base, value, path_kinds)
        _append(edges, _optional_edge(
            field, position, "asset_php", target, companion, index, path_kinds
        ))
    if family == "style":
        companion = _rtl_companion(target)
        _append(edges, _optional_edge(
            field, position, "rtl_style", target, companion, index, path_kinds
        ))
    return target


def _add_asset_fields(metadata, rules, base, index, path_kinds, edges) -> None:
    for rule in rules:
        if rule.field not in metadata:
            continue
        seen = set()
        for position, value in enumerate(_field_values(metadata, rule)):
            if value.startswith("file:"):
                target = _add_local_edges(
                    edges, rule.field, position, rule.family, value, base, index,
                    path_kinds,
                )
                identity = ("file", target)
            else:
                _validate_handle(value)
                _append(
                    edges,
                    _edge(rule.field, position, "handle", value, None, "registered", index),
                )
                identity = ("handle", value)
            if identity in seen:
                raise ValueError(f"duplicate normalized target in {rule.field}")
            seen.add(identity)


def _add_php_metadata_edges(metadata, base, index, path_kinds, edges) -> None:
    if "render" in metadata:
        value = metadata["render"]
        if not isinstance(value, str) or not value.startswith("file:"):
            raise ValueError("render must be one scalar file: PHP target")
        target = _resolve_path(base, value[len("file:"):], index, path_kinds)
        _append(edges, _edge("render", 0, "render_php", value, target, "present", index))
    if "variations" not in metadata or isinstance(metadata["variations"], list):
        return
    value = metadata["variations"]
    if not isinstance(value, str) or not value.startswith("file:"):
        raise ValueError("variations must be an inline array or scalar file: PHP target")
    target = _resolve_path(base, value[len("file:"):], index, path_kinds)
    _append(edges, _edge("variations", 0, "variations_php", value, target, "present", index))


def _is_suffix_candidate(path: str) -> bool:
    lowered = path.casefold()
    return any(lowered.endswith(suffix) for suffix in PHP_SUFFIXES)


def _php_candidates(held, index) -> tuple[artifact_staging.ManifestEntry, ...]:
    candidates = []
    total = 0
    for path, entry in sorted(index.items()):
        is_candidate = _is_suffix_candidate(path)
        if not is_candidate:
            is_candidate = artifact_staging.held_member_has_php_tag(held, path)
        if not is_candidate:
            continue
        problem = _unsafe_text(path)
        if problem:
            raise ValueError(
                f"executable PHP candidate path contains {problem}: {path!r}"
            )
        if any(part in artifact_layout.EXCLUDED_ROOTS for part in PurePosixPath(path).parts):
            raise ValueError(f"executable PHP candidate is in excluded namespace: {path}")
        candidates.append(entry)
        total += entry.size
        if len(candidates) > MAX_PHP_CANDIDATES:
            raise ValueError("executable PHP candidate count exceeds limit")
        if total > MAX_PHP_BYTES:
            raise ValueError("executable PHP candidate bytes exceed limit")
    return tuple(candidates)


def _require_php_targets(edges, candidate_paths) -> None:
    for edge in edges:
        if edge.kind in {"render_php", "variations_php"} and edge.target not in candidate_paths:
            raise ValueError(f"{edge.field} target is not PHP-capable")


def _execution_files(
    index, edges, candidates, block_json, selected_root
) -> tuple[ExecutionFile, ...]:
    classes: dict[str, set[str]] = {block_json: {"metadata"}}
    root_prefix = selected_root.as_posix().rstrip("/") + "/"
    for path in index:
        if path.startswith(root_prefix):
            relative = PurePosixPath(path).relative_to(selected_root)
            if any(part in artifact_layout.EXCLUDED_ROOTS for part in relative.parts):
                continue
            classes.setdefault(path, set()).add("runtime_asset")
    for edge in edges:
        if edge.target is not None and edge.state == "present":
            classes.setdefault(edge.target, set()).add(edge.kind)
    for entry in candidates:
        classes.setdefault(entry.path, set()).add("php_candidate")
    return tuple(
        ExecutionFile(
            path, index[path].mode_class, index[path].size, index[path].sha256,
            tuple(sorted(labels)),
        )
        for path, labels in sorted(classes.items())
    )


def _scan_files(files: tuple[ExecutionFile, ...]) -> tuple[ScanFile, ...]:
    result = []
    for item in files:
        labels = set(item.classifications)
        if "php_candidate" in labels:
            scan_ids = PHP_SCAN_IDS
        elif "metadata" in labels:
            scan_ids = METADATA_SCAN_IDS
        else:
            scan_ids = ASSET_SCAN_IDS
        result.append(ScanFile(item.path, scan_ids))
    return tuple(result)


def _scanner_aliases(candidates) -> tuple[dict, ...]:
    return tuple(
        {
            "source_path": item.path,
            "alias_name": (
                f"php-{index:04d}-{sha256_bytes(item.path.encode())[:16]}.php"
            ),
            "size": item.size,
            "sha256": item.sha256,
        }
        for index, item in enumerate(candidates)
    )


def scanner_aliases(proof: BlockExecutionProof) -> tuple[dict, ...]:
    if not isinstance(proof, BlockExecutionProof):
        raise TypeError("scanner aliases require a BlockExecutionProof")
    return _scanner_aliases(proof.php_candidates)


def scanner_alias_digest(proof: BlockExecutionProof) -> str:
    return _canonical_digest(scanner_aliases(proof))


def _metadata_digest_payload(layout, core, rule_digest, edges, files):
    graph_files = [item for item in files if item.classifications != ("php_candidate",)]
    return {
        "schema": PROOF_SCHEMA_VERSION,
        "output_manifest": layout.manifest_sha256,
        "source_manifest": layout.source.manifest_sha256,
        "selected_root": layout.selected_root.as_posix(),
        "selected_block_json": layout.selected_block_json.as_posix(),
        "selection_reason": layout.selection_reason,
        "core": asdict(core),
        "rule_digest": rule_digest,
        "edges": [asdict(edge) for edge in edges],
        "files": [asdict(item) for item in graph_files],
    }


def _build_digests(layout, core, rule_digest, edges, files, candidates, scans):
    metadata_payload = _metadata_digest_payload(
        layout, core, rule_digest, edges, files
    )
    metadata_digest = _canonical_digest(metadata_payload)
    php_digest = _canonical_digest(
        {
            "schema": PROOF_SCHEMA_VERSION,
            "output_manifest": layout.manifest_sha256,
            "rule_digest": rule_digest,
            "candidates": [asdict(item) for item in candidates],
        }
    )
    artifact_digest = _canonical_digest(
        {
            "schema": PROOF_SCHEMA_VERSION,
            "metadata_graph_digest": metadata_digest,
            "php_set_digest": php_digest,
            "files": [asdict(item) for item in files],
            "scan_files": [asdict(item) for item in scans],
            "scanner_aliases": _scanner_aliases(candidates),
        }
    )
    return metadata_digest, php_digest, artifact_digest


def _proof_metadata_payload(proof: BlockExecutionProof):
    graph_files = [
        item for item in proof.files if item.classifications != ("php_candidate",)
    ]
    return {
        "schema": proof.schema_version,
        "output_manifest": proof.output_manifest_sha256,
        "source_manifest": proof.source_manifest_sha256,
        "selected_root": proof.selected_root,
        "selected_block_json": proof.selected_block_json,
        "selection_reason": proof.selection_reason,
        "core": asdict(proof.core),
        "rule_digest": proof.rule_digest,
        "edges": [asdict(edge) for edge in proof.edges],
        "files": [asdict(item) for item in graph_files],
    }


def _validate_artifact_proof(proof: BlockExecutionProof) -> None:
    _rules, expected_rule = _rules_for_core(proof.core)
    if proof.schema_version != PROOF_SCHEMA_VERSION or proof.rule_digest != expected_rule:
        raise ValueError("artifact proof schema or rule digest is invalid")
    metadata_digest = _canonical_digest(_proof_metadata_payload(proof))
    php_digest = _canonical_digest(
        {
            "schema": proof.schema_version,
            "output_manifest": proof.output_manifest_sha256,
            "rule_digest": proof.rule_digest,
            "candidates": [asdict(item) for item in proof.php_candidates],
        }
    )
    artifact_digest = _canonical_digest(
        {
            "schema": proof.schema_version,
            "metadata_graph_digest": metadata_digest,
            "php_set_digest": php_digest,
            "files": [asdict(item) for item in proof.files],
            "scan_files": [asdict(item) for item in proof.scan_files],
            "scanner_aliases": _scanner_aliases(proof.php_candidates),
        }
    )
    if (metadata_digest, php_digest, artifact_digest) != (
        proof.metadata_graph_digest, proof.php_set_digest, proof.artifact_proof_digest
    ):
        raise ValueError("artifact proof digest binding is invalid")


def build_execution_proof(
    held: artifact_staging.HeldStagedTree,
    layout: artifact_layout.BlockArtifactLayout,
    *,
    core: CoreIdentity = PINNED_WORDPRESS_CORE,
) -> BlockExecutionProof:
    """Build a canonical proof without reopening an untrusted host path."""
    rules, rule_digest = _rules_for_core(core)
    _validate_layout(held, layout)
    if len(held.proof.manifest) > MAX_BLOCK_ENTRIES:
        raise ValueError("block output exceeds the 1024-file reviewed bound")
    if held.proof.total_bytes > MAX_BLOCK_OUTPUT_BYTES:
        raise ValueError("block output exceeds the 32 MiB reviewed bound")
    index = _manifest_index(held)
    path_kinds = dict(held.proof.path_kinds)
    block_path = layout.selected_block_json.as_posix()
    metadata = _parse_metadata(artifact_staging.read_held_member(held, block_path))
    edges: list[MetadataEdge] = []
    base = layout.selected_block_json.parent
    _add_php_metadata_edges(metadata, base, index, path_kinds, edges)
    _add_asset_fields(metadata, rules, base, index, path_kinds, edges)
    raw_candidates = _php_candidates(held, index)
    candidate_paths = {entry.path for entry in raw_candidates}
    _require_php_targets(edges, candidate_paths)
    files = _execution_files(
        index, edges, raw_candidates, block_path, layout.selected_root
    )
    if any(item.size > MAX_RUNTIME_FILE_BYTES for item in files):
        raise ValueError("runtime closure member exceeds the 8 MiB reviewed bound")
    if sum(item.size for item in files) > MAX_RUNTIME_CLOSURE_BYTES:
        raise ValueError("runtime closure exceeds the 16 MiB reviewed bound")
    candidates = tuple(item for item in files if "php_candidate" in item.classifications)
    scans = _scan_files(files)
    digests = _build_digests(
        layout, core, rule_digest, tuple(edges), files, candidates, scans
    )
    return BlockExecutionProof(
        PROOF_SCHEMA_VERSION, layout.manifest_sha256, layout.source.manifest_sha256,
        layout.selected_root.as_posix(), block_path, layout.selection_reason, core,
        rule_digest, tuple(edges), files, candidates, scans, *digests,
    )


def _runtime_path(path: str) -> str:
    if not isinstance(path, str):
        raise TypeError("wrapper path must be a string")
    problem = _unsafe_text(path)
    pure = PurePosixPath(path)
    if problem or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("wrapper path must be a normalized safe relative path")
    if pure.as_posix() != path:
        raise ValueError("wrapper path must be a normalized safe relative path")
    return path


def _digest_string(value: str, label: str) -> str:
    valid = isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
    if not valid:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _wrapper_validation_digest(wrapper_sha: str, selected: str, checks) -> str:
    return _canonical_digest(
        {
            "schema": PROOF_SCHEMA_VERSION,
            "wrapper_sha256": wrapper_sha,
            "selected_block_json": selected,
            "checks": list(checks),
        }
    )


def build_wrapper_validation(
    wrapper_bytes: bytes, selected_block_json: str, *, php_syntax_passed: bool
) -> WrapperValidation:
    """Bind an exact generated bootstrap and an independently passing PHP lint."""
    block_runtime_wrapper.validate(wrapper_bytes, selected_block_json)
    if not php_syntax_passed:
        raise ValueError("wrapper PHP syntax did not pass")
    checks = ("bootstrap_exact", "php_syntax")
    digest = _wrapper_validation_digest(
        sha256_bytes(wrapper_bytes), selected_block_json, checks
    )
    return WrapperValidation(checks, digest)


def bind_runtime_proof(
    proof: BlockExecutionProof,
    wrapper_path: str,
    wrapper_bytes: bytes,
    synthesized_manifest_digest: str,
    wrapper_validation: WrapperValidation,
) -> RuntimeExecutionProof:
    """Bind generated wrapper bytes and synthesized runtime to the artifact proof."""
    if not isinstance(proof, BlockExecutionProof):
        raise TypeError("artifact proof must be a BlockExecutionProof")
    _validate_artifact_proof(proof)
    path = _runtime_path(wrapper_path)
    if not isinstance(wrapper_bytes, bytes):
        raise TypeError("wrapper bytes must be bytes")
    if not wrapper_bytes or len(wrapper_bytes) > MAX_WRAPPER_BYTES:
        raise ValueError("wrapper bytes are empty or exceed the reviewed limit")
    manifest = _digest_string(synthesized_manifest_digest, "manifest digest")
    wrapper_digest = sha256_bytes(wrapper_bytes)
    if not isinstance(wrapper_validation, WrapperValidation):
        raise TypeError("wrapper validation must be a WrapperValidation")
    expected_validation = build_wrapper_validation(
        wrapper_bytes, proof.selected_block_json, php_syntax_passed=True
    )
    if wrapper_validation != expected_validation:
        raise ValueError("wrapper validation binding is invalid")
    digest = _canonical_digest(
        {
            "schema": PROOF_SCHEMA_VERSION,
            "artifact_proof_digest": proof.artifact_proof_digest,
            "wrapper_path": path,
            "wrapper_size": len(wrapper_bytes),
            "wrapper_sha256": wrapper_digest,
            "wrapper_validation_digest": wrapper_validation.digest,
            "synthesized_manifest_sha256": manifest,
        }
    )
    return RuntimeExecutionProof(
        PROOF_SCHEMA_VERSION, proof, path, len(wrapper_bytes), wrapper_digest,
        wrapper_validation.digest, manifest, digest,
    )


def validate_runtime_proof(proof: RuntimeExecutionProof) -> None:
    """Recompute every digest available in a persisted runtime proof value."""
    if not isinstance(proof, RuntimeExecutionProof):
        raise TypeError("runtime proof must be a RuntimeExecutionProof")
    if proof.schema_version != PROOF_SCHEMA_VERSION:
        raise ValueError("runtime proof schema version is invalid")
    if proof.wrapper_size <= 0 or proof.wrapper_size > MAX_WRAPPER_BYTES:
        raise ValueError("runtime wrapper size is invalid")
    _validate_artifact_proof(proof.artifact)
    _runtime_path(proof.wrapper_path)
    _digest_string(proof.wrapper_sha256, "wrapper digest")
    _digest_string(proof.wrapper_validation_digest, "wrapper validation digest")
    manifest = _digest_string(
        proof.synthesized_manifest_sha256, "manifest digest"
    )
    expected_validation = _wrapper_validation_digest(
        proof.wrapper_sha256,
        proof.artifact.selected_block_json,
        ("bootstrap_exact", "php_syntax"),
    )
    if proof.wrapper_validation_digest != expected_validation:
        raise ValueError("runtime wrapper validation digest is invalid")
    expected = _canonical_digest(
        {
            "schema": proof.schema_version,
            "artifact_proof_digest": proof.artifact.artifact_proof_digest,
            "wrapper_path": proof.wrapper_path,
            "wrapper_size": proof.wrapper_size,
            "wrapper_sha256": proof.wrapper_sha256,
            "wrapper_validation_digest": proof.wrapper_validation_digest,
            "synthesized_manifest_sha256": manifest,
        }
    )
    if proof.execution_proof_digest != expected:
        raise ValueError("runtime execution proof digest is invalid")
