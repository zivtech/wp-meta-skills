"""Strict fixture-owned assertion loading for conditional block runtime."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import runtime_assertions  # noqa: E402


def _pair(tmp_path: Path, assertions: dict | None = None) -> tuple[Path, Path]:
    fixtures = tmp_path / "wordpress-block-executor" / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    fixture = fixtures / "card.md"
    metadata = fixtures / "card.metadata.yaml"
    fixture.write_text("Build the card block.\n", encoding="utf-8")
    payload = {"name": "card", "suite": "wordpress-block-executor"}
    if assertions is not None:
        payload["runtime_assertions"] = assertions
    metadata.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return fixture, metadata


def _valid() -> dict[str, str]:
    return {
        "block_name": "acme/runtime-card",
        "frontend_selector": ".wp-block-acme-runtime-card",
        "expected_frontend_text": "Exact fixture-owned visible text",
    }


def test_loads_exact_regular_fixture_pair_and_immutable_assertion(tmp_path):
    fixture, metadata = _pair(tmp_path, _valid())
    pair = runtime_assertions.load_block_runtime_fixture(
        tmp_path, "wordpress-block-executor", "card"
    )
    assert pair.fixture_path == fixture.resolve()
    assert pair.metadata_path == metadata.resolve()
    assert pair.assertion.block_name == "acme/runtime-card"
    with pytest.raises(Exception):
        pair.assertion.block_name = "changed"


@pytest.mark.parametrize("missing", tuple(_valid()))
def test_rejects_each_missing_assertion_field(tmp_path, missing):
    values = _valid()
    values.pop(missing)
    _pair(tmp_path, values)
    with pytest.raises(ValueError, match="exactly"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )


def test_rejects_missing_mapping_unknown_keys_and_wrong_types(tmp_path):
    _pair(tmp_path)
    with pytest.raises(ValueError, match="runtime_assertions"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )
    values = _valid() | {"inferred_text": "forbidden"}
    _pair(tmp_path, values)
    with pytest.raises(ValueError, match="exactly"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )
    values = _valid() | {"expected_frontend_text": 42}
    _pair(tmp_path, values)
    with pytest.raises(ValueError, match="string"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("block_name", "Acme/card", "block_name"),
        ("block_name", "acme/" + "x" * 124, "128"),
        ("frontend_selector", "#wp-block-acme-runtime-card", "selector"),
        ("frontend_selector", ".wp-block-acme-other", "deterministic"),
        ("expected_frontend_text", " leading", "whitespace"),
        ("expected_frontend_text", "trailing ", "whitespace"),
        ("expected_frontend_text", "<strong>HTML</strong>", "HTML"),
        ("expected_frontend_text", "line\nbreak", "control"),
        ("expected_frontend_text", "format\u200bcharacter", "format"),
        ("expected_frontend_text", "surrogate\ud800", "surrogate"),
        ("expected_frontend_text", "x" * 501, "500"),
    ),
)
def test_rejects_unsafe_or_overlong_values(tmp_path, field, value, message):
    values = _valid() | {field: value}
    _pair(tmp_path, values)
    with pytest.raises(ValueError, match=message):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )


def test_accepts_exact_utf8_byte_ceiling(tmp_path):
    _pair(tmp_path, _valid() | {"expected_frontend_text": "\U0001f600" * 500})
    pair = runtime_assertions.load_block_runtime_fixture(
        tmp_path, "wordpress-block-executor", "card"
    )
    assert len(pair.assertion.expected_frontend_text.encode("utf-8")) == 2_000


def test_rejects_metadata_identity_mismatch(tmp_path):
    _fixture, metadata = _pair(tmp_path, _valid())
    payload = yaml.safe_load(metadata.read_text(encoding="utf-8"))
    payload["name"] = "another"
    metadata.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )


@pytest.mark.parametrize("target_name", ("card.md", "card.metadata.yaml"))
def test_rejects_symlinked_pair_member(tmp_path, target_name):
    fixture, metadata = _pair(tmp_path, _valid())
    target = fixture if target_name.endswith(".md") else metadata
    real = target.with_name(target.name + ".real")
    target.rename(real)
    target.symlink_to(real)
    with pytest.raises(ValueError, match="regular"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )


def test_rejects_non_regular_pair_member_and_path_escape(tmp_path):
    fixture, _metadata = _pair(tmp_path, _valid())
    fixture.unlink()
    fixture.mkdir()
    with pytest.raises(ValueError, match="regular"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "wordpress-block-executor", "card"
        )
    with pytest.raises(ValueError, match="identifier"):
        runtime_assertions.load_block_runtime_fixture(
            tmp_path, "../escape", "card"
        )


def test_rejects_parent_symlink_containment_escape(tmp_path):
    outside = tmp_path / "outside"
    fixtures = outside / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "card.md").write_text("fixture", encoding="utf-8")
    (fixtures / "card.metadata.yaml").write_text(
        yaml.safe_dump({
            "name": "card", "suite": "wordpress-block-executor",
            "runtime_assertions": _valid(),
        }),
        encoding="utf-8",
    )
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "wordpress-block-executor")
    with pytest.raises(ValueError, match="containment"):
        runtime_assertions.load_block_runtime_fixture(
            root, "wordpress-block-executor", "card"
        )
