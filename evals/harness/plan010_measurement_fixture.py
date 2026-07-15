"""Exact fixture construction for Plan 010 boundary measurements."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    entry_count: int
    output_bytes: int
    runtime_bytes: int
    php_candidate_count: int
    php_candidate_bytes: int
    asset_count: int
    metadata_bytes: int
    metadata_edges: int
    metadata_depth: int
    outside_php_candidates: int
    maximum_asset_bytes: int | None = None

    def validate(self) -> None:
        fixed = 2 + self.php_candidate_count + self.asset_count
        ignored = {"name", "maximum_asset_bytes", "outside_php_candidates"}
        values = {key: value for key, value in asdict(self).items() if key not in ignored}
        if not self.name or not isinstance(self.name, str):
            raise ValueError("fixture name must be non-empty")
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
               for value in values.values()):
            raise ValueError("fixture values must be positive integers")
        if self.entry_count < fixed:
            raise ValueError("entry count cannot contain the required fixture files")
        if self.runtime_bytes >= self.output_bytes:
            raise ValueError("runtime bytes must leave bounded outside-root filler")
        if self.php_candidate_bytes >= self.runtime_bytes:
            raise ValueError("PHP bytes must leave bounded runtime metadata/assets")
        if self.metadata_edges not in {self.asset_count * 2 + 1, self.asset_count * 2 + 2}:
            raise ValueError("fixture metadata edge count is inconsistent")
        if not 0 <= self.outside_php_candidates < self.php_candidate_count:
            raise ValueError("outside PHP candidate count is invalid")
        if self.maximum_asset_bytes is not None:
            if self.asset_count < 2 or self.maximum_asset_bytes <= 0:
                raise ValueError("maximum asset profile needs two assets and a byte target")


def _depth_value(target_depth: int):
    if target_depth < 2:
        raise ValueError("metadata depth must include the object and one value")
    value: Any = 0
    for _index in range(target_depth - 2):
        value = [value]
    return value


def metadata(
    name: str, scripts: list[str] | None = None,
    target_bytes: int | None = None, target_depth: int = 2,
) -> bytes:
    data: dict[str, Any] = {
        "apiVersion": 3,
        "name": name,
        "title": "Plan 010 Boundary Fixture",
        "category": "widgets",
        "textdomain": "plan010-boundary",
        "plan010Depth": _depth_value(target_depth),
    }
    if scripts is not None:
        data.update({"script": scripts, "render": "file:./render.php"})
    if target_bytes is None:
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    data["description"] = ""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    padding = target_bytes - len(encoded)
    if padding < 0:
        raise ValueError("metadata target is smaller than its required fields")
    data["description"] = "x" * padding
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) != target_bytes:
        raise RuntimeError("metadata padding arithmetic drifted")
    return encoded


def json_depth(value, depth: int = 1) -> int:
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return max([depth, *(json_depth(child, depth + 1) for child in children)])


def sizes(total: int, count: int, minimum: int = 1) -> list[int]:
    if count < 1 or total < count * minimum:
        raise ValueError("byte allocation cannot satisfy its minimum")
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _padded(prefix: bytes, size: int, fill: bytes) -> bytes:
    if len(fill) != 1 or len(prefix) > size:
        raise ValueError("fixture member cannot fit its valid prefix")
    return prefix + fill * (size - len(prefix))


def _write_sized_files(
    root: Path, names: list[str], byte_sizes: list[int], prefix: bytes, fill: bytes
) -> None:
    for name, size in zip(names, byte_sizes, strict=True):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_padded(prefix, size, fill))


def asset_sizes(spec: FixtureSpec, available: int) -> list[int]:
    maximum = spec.maximum_asset_bytes
    if maximum is None:
        return sizes(available, spec.asset_count, 32)
    if available <= maximum:
        raise ValueError("maximum asset leaves no bytes for remaining assets")
    return [maximum] + sizes(available - maximum, spec.asset_count - 1, 32)


def _php_names(spec: FixtureSpec) -> list[str]:
    inside_count = spec.php_candidate_count - spec.outside_php_candidates
    names = ["render.php"] + [
        f"php/candidate-{index:04d}.inc" for index in range(1, inside_count)
    ]
    names.extend(
        f"../../../outside/candidate-{index:04d}.inc"
        for index in range(spec.outside_php_candidates)
    )
    if len(names) != spec.php_candidate_count:
        raise RuntimeError("PHP candidate path arithmetic drifted")
    return names


def write_fixture(root: Path, spec: FixtureSpec) -> tuple[Path, Path]:
    spec.validate()
    source = root / "fixture-source"
    output = root / "fixture-output"
    source_block = source / "blocks" / "card"
    built_block = output / "blocks" / "card" / "build"
    source_block.mkdir(parents=True)
    built_block.mkdir(parents=True)
    source_metadata = metadata("plan010/boundary")
    asset_names = [f"assets/asset-{index:04d}.js" for index in range(spec.asset_count)]
    script_values = [f"file:./{name}" for name in asset_names]
    if spec.metadata_edges == spec.asset_count * 2 + 2:
        script_values.append("plan010-boundary-handle")
    built_metadata = metadata(
        "plan010/boundary", script_values, spec.metadata_bytes, spec.metadata_depth
    )
    (source_block / "block.json").write_bytes(source_metadata)
    output.joinpath("blocks/card").mkdir(parents=True, exist_ok=True)
    output.joinpath("blocks/card/block.json").write_bytes(source_metadata)
    (built_block / "block.json").write_bytes(built_metadata)
    php_names = _php_names(spec)
    php_sizes = sizes(spec.php_candidate_bytes, spec.php_candidate_count, 32)
    _write_sized_files(built_block, php_names, php_sizes, b"<?php\nreturn null;\n", b" ")
    asset_bytes = spec.runtime_bytes - spec.php_candidate_bytes - len(built_metadata)
    _write_sized_files(
        built_block, asset_names, asset_sizes(spec, asset_bytes),
        b"/* plan010 runtime asset */\n", b"a",
    )
    filler_count = spec.entry_count - 2 - spec.php_candidate_count - spec.asset_count
    filler_bytes = spec.output_bytes - spec.runtime_bytes - len(source_metadata)
    filler_names = [f"outside/filler-{index:04d}.txt" for index in range(filler_count)]
    _write_sized_files(
        output, filler_names, sizes(filler_bytes, filler_count, 16), b"outside filler\n", b"z"
    )
    return source, output
