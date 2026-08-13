"""Unit tests for the baseline API-leakage measurement (PURE logic, no corpus I/O).

`collect()` walks the real suites and is exercised by running the tool; the scoring and
summary logic is what needs pinning, because the review conclusion rests on it.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import measure_baseline_api_leakage as leak


def test_leakage_is_zero_when_the_prompt_names_nothing():
    row = leak.leakage_for_fixture(["esc_like", "wpdb::prepare"], "Review the code carefully.")
    assert math.isclose(row["coverage"], 0.0)
    assert row["named"] == [] and row["n_expected"] == 2


def test_leakage_is_total_when_the_prompt_supplies_the_whole_key():
    prompt = "A LIKE term must go through $wpdb->esc_like, and SQL must use $wpdb->prepare."
    row = leak.leakage_for_fixture(["esc_like", "wpdb::prepare"], prompt)
    assert math.isclose(row["coverage"], 1.0)
    assert set(row["named"]) == {"esc_like", "wpdb::prepare"}


def test_leakage_reports_which_apis_were_supplied():
    row = leak.leakage_for_fixture(["esc_like", "wpdb::prepare", "sanitize_text_field"],
                                   "Use $wpdb->prepare with placeholders.")
    assert math.isclose(row["coverage"], 1 / 3)
    assert row["named"] == ["wpdb::prepare"]


def test_leakage_uses_the_scorers_own_matcher_not_a_raw_substring():
    # api_match normalizes `$wpdb->prepare` / `wpdb::prepare`; a naive `in` test would miss it.
    row = leak.leakage_for_fixture(["wpdb::prepare"], "always call $wpdb->prepare()")
    assert math.isclose(row["coverage"], 1.0)


def test_summarize_means_per_condition_and_flags_high_leakage():
    rows = [
        {"condition": "baseline-few-shot", "fixture": "f1", "coverage": 1.0},
        {"condition": "baseline-few-shot", "fixture": "f2", "coverage": 0.5},
        {"condition": "baseline-few-shot", "fixture": "f3", "coverage": 0.0},
        {"condition": "baseline-zero-shot", "fixture": "f1", "coverage": 0.0},
    ]
    out = leak.summarize(rows, flag_at=0.5)
    few = out["by_condition"]["baseline-few-shot"]
    assert math.isclose(few["mean_coverage"], 0.5)
    assert few["n_fixtures"] == 3
    # the flag is inclusive: a prompt supplying half the key already makes the axis murky
    assert few["flagged_fixtures"] == ["f1", "f2"] and few["n_flagged"] == 2
    assert out["by_condition"]["baseline-zero-shot"]["n_flagged"] == 0


def test_summarize_tolerates_a_condition_with_no_scored_fixtures():
    out = leak.summarize([{"condition": "baseline-few-shot", "fixture": "f1", "coverage": None}])
    assert out["by_condition"]["baseline-few-shot"]["mean_coverage"] is None
