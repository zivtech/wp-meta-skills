"""Regression tests for the evidence-log gate.

The log's whole value is that a reader can follow any row back to a committed
artifact. These tests prove the gate enforces that rather than declaring it —
including the check that caught a real defect in the log's own first draft: a
row that said what its result licensed and never said what it did not.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "docs" / "wordpress" / "negative-results.md"


def load_validator():
    path = ROOT / "scripts" / "validate-evidence-log.py"
    spec = importlib.util.spec_from_file_location("evidence_log", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evidence_log_gate_passes_on_the_committed_tree():
    result = subprocess.run(
        [sys.executable, "scripts/validate-evidence-log.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_cited_analysis_path_exists():
    """The rule the log states about itself: no row survives a dangling path."""
    validator = load_validator()
    text = LOG.read_text(encoding="utf-8")

    rows = (
        validator._table_rows(text, validator.NULL_TABLE_HEADER)
        + validator._table_rows(text, validator.POSITIVE_TABLE_HEADER)
    )
    assert rows, "expected the log to contain rows"

    for cells in rows:
        analysis = validator._first_path(cells[5] if len(cells) == 8 else cells[4])
        assert analysis, f"{cells[0]} cites no analysis path"
        assert (ROOT / analysis).exists(), f"{cells[0]} cites missing {analysis}"


def test_both_tables_are_populated():
    """A log carrying only nulls misleads as badly as one carrying only wins."""
    validator = load_validator()
    text = LOG.read_text(encoding="utf-8")

    nulls = validator._table_rows(text, validator.NULL_TABLE_HEADER)
    positives = validator._table_rows(text, validator.POSITIVE_TABLE_HEADER)

    assert len(nulls) >= validator.MIN_NULL_ROWS
    assert len(positives) >= validator.MIN_POSITIVE_ROWS


def test_every_claim_states_its_boundary():
    validator = load_validator()
    text = LOG.read_text(encoding="utf-8")

    for cells in validator._table_rows(text, validator.NULL_TABLE_HEADER):
        assert not validator._check_claim(cells[0], cells[4]), cells[0]
    for cells in validator._table_rows(text, validator.POSITIVE_TABLE_HEADER):
        assert not validator._check_claim(cells[0], cells[3]), cells[0]


def test_claim_without_negative_space_is_rejected():
    """The defect the gate caught in the log's own first draft."""
    validator = load_validator()

    only_positive = "Licenses: the suite is production ready and beats every baseline."
    assert validator._check_claim("N9", only_positive)

    with_boundary = only_positive + " Does **not** license a superiority claim."
    assert not validator._check_claim("N9", with_boundary)


@pytest.mark.parametrize(
    "cell",
    [
        "`docs/wordpress/does-not-exist.md`",
        "`/etc/passwd`",
        "`../../../etc/passwd`",
        "no path at all",
    ],
)
def test_bad_analysis_citations_are_rejected(cell):
    validator = load_validator()

    assert validator._check_cited_path("N9", cell, "analysis")


@pytest.mark.parametrize(
    "cell",
    [
        "in-repo",
        "somewhere else",
        "`evals/results/does-not-exist/`",
        "`../outside`",
    ],
)
def test_bad_archive_states_are_rejected(cell):
    validator = load_validator()

    assert validator._check_archive("N9", cell)


@pytest.mark.parametrize("cell", ["monorepo-internal", "`evals/harness`"])
def test_valid_archive_states_are_accepted(cell):
    validator = load_validator()

    assert not validator._check_archive("N9", cell)


def test_missing_rerun_harness_is_rejected_unless_declared_absent():
    validator = load_validator()

    assert validator._check_rerun("N9", "`evals/harness/no-such-harness.py`")
    assert not validator._check_rerun("N9", "not applicable — never executed")
    assert not validator._check_rerun("N9", "`evals/harness/answer_key_score.py`")


def test_shrinking_the_null_table_fails_the_gate():
    """The failure mode this gate exists for: nulls quietly disappearing."""
    validator = load_validator()

    assert validator.validate_null_rows([])
    assert validator.validate_positive_rows([])


def test_evidence_index_must_point_at_the_log():
    validator = load_validator()

    assert not validator.validate_index()
    assert "docs/wordpress/negative-results.md" in (ROOT / "EVIDENCE.md").read_text(encoding="utf-8")


def test_required_sections_are_enforced():
    validator = load_validator()

    assert validator.validate_structure("# Log\n\nno sections here")
    assert not validator.validate_structure(LOG.read_text(encoding="utf-8"))
