"""Strict fixture-owned assertion loading for conditional block runtime."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
import yaml

HARNESS = Path(__file__).resolve().parents[1]
ROOT = HARNESS.parents[1]
SUITES = ROOT / "evals" / "suites"
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


def test_tracked_block_executor_fixture_is_exact_runtime_card_contract():
    pair = runtime_assertions.load_block_runtime_fixture(
        SUITES, "wordpress-block-executor", "smoke-wordpress-v1"
    )
    assert pair.assertion.block_name == "acme/runtime-card"
    assert pair.assertion.frontend_selector == ".wp-block-acme-runtime-card"
    assert pair.assertion.expected_frontend_text == "Runtime block smoke"

    fixture = pair.fixture_path.read_text(encoding="utf-8")
    required_fixture_contract = (
        "# Smoke Fixture: Acme Runtime Card",
        "`acme/runtime-card`",
        "`blocks/runtime-card/block.json`",
        "`blocks/runtime-card/index.asset.php`",
        "`blocks/runtime-card/index.js`",
        "`blocks/runtime-card/render.php`",
        "`block-scripts-32.4.1-smoke`",
        "`990d9a67783977a5a4c54035666ebc48f7aaac8cdf69f2313caf2a17b317fa33`",
        "`e2259282345ac90cb5645507efd0daba536b2742be3eab676db10fd7fc1fb4f6`",
        "`get_block_wrapper_attributes()`",
        "`.wp-block-acme-runtime-card`",
        "`Runtime block smoke`",
        "--strict-full-profile",
    )
    for marker in required_fixture_contract:
        assert marker in fixture

    rubric_path = (
        SUITES / "wordpress-block-executor" / "rubrics"
        / "smoke-wordpress-v1.rubric.yaml"
    )
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    assert rubric["max_score"] == 10
    assert [criterion["id"] for criterion in rubric["criteria"]] == [
        "exact_runtime_card_contract",
        "materializable_packet_contract",
        "wordpress_safety_and_quality",
        "bound_runtime_evidence",
        "calibration_and_handoff",
    ]


@pytest.mark.parametrize(
    ("relative_path", "block_name", "selector", "text"),
    (
        ("README.md", "acme/runtime-card", ".wp-block-acme-runtime-card", "Runtime block smoke"),
        (
            "examples/smoke-wordpress-v1.materializable-packet.md",
            "acme/runtime-card", ".wp-block-acme-runtime-card", "Runtime block smoke",
        ),
        (
            "examples/interactivity-wordpress-v1.materializable-packet.md",
            "acme/interactive-counter", ".wp-block-acme-interactive-counter",
            "Runtime block smoke",
        ),
        (
            "examples/deprecation-wordpress-v1.materializable-packet.md",
            "acme/deprecated-card", ".wp-block-acme-deprecated-card",
            "Runtime block smoke:",
        ),
    ),
)
def test_current_block_runtime_docs_bind_identity_digest_and_full_profile(
    relative_path, block_name, selector, text,
):
    suite = SUITES / "wordpress-block-executor"
    document = (suite / relative_path).read_text(encoding="utf-8")
    commands = [
        block for block in re.findall(r"```bash\n(.*?)```", document, re.DOTALL)
        if "run_wordpress_runtime_smoke.py" in block
    ]
    assert len(commands) == 1
    command = commands[0]
    for marker in (
        'artifact="<generated-block-dir>"',
        '--expected-artifact-digest "$digest"',
        "--evidence-id ",
        "--artifact-kind block",
        "--block-build-smoke",
        f"--block-name {block_name}",
        "--editor-insert-render-smoke",
        f"--expected-frontend-selector {selector}",
        f'--expected-frontend-text "{text}"',
        "--provision-full-profile",
        "--strict-full-profile",
        "--write",
        "--run-id ",
        "--timeout-sec 300",
    ):
        assert marker in command

    if "interactivity" in relative_path or "deprecation" in relative_path:
        assert "unsupported by the current isolated artifact path" in document
        assert "historical" in document
    assert "--interactivity-smoke" not in command
    assert "--deprecation-smoke" not in command


def test_eval_config_exposes_only_supported_bound_external_runtime_command():
    path = SUITES / "wordpress-block-executor" / "eval.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    oracle = config["artifact_oracle"]
    command = oracle["runtime_command"]
    for marker in (
        "--expected-artifact-digest <artifact-digest>",
        "--evidence-id <evidence-id>",
        "--block-name acme/runtime-card",
        "--expected-frontend-selector .wp-block-acme-runtime-card",
        "--expected-frontend-text 'Runtime block smoke'",
        "--provision-full-profile",
        "--strict-full-profile",
    ):
        assert marker in command
    assert "unsupported" in oracle["interactivity_runtime_status"]
    assert "historical" in oracle["interactivity_runtime_status"]
    assert "unsupported" in oracle["deprecation_runtime_status"]
    assert "historical" in oracle["deprecation_runtime_status"]
