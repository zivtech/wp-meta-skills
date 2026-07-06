"""Tests for deterministic high-risk WordPress answer-key scoring."""

from __future__ import annotations

import json
from pathlib import Path

import score_wordpress_high_risk_answer_keys as scorer


def test_item_detected_uses_content_token_overlap():
    result = scorer.item_detected(
        "permission_callback => __return_true is public on a mutating route",
        "The REST route uses __return_true as its permission_callback, so this mutating route is public.",
    )

    assert result.matched is True
    assert result.score >= 0.55


def test_anti_claimed_respects_negative_space():
    result = scorer.anti_claimed(
        "production exploit proof",
        "This is not production exploit proof; it is only a static authorization review.",
    )

    assert result.matched is False
    assert result.negated is True


def test_anti_claimed_does_not_use_loose_token_overlap():
    result = scorer.anti_claimed(
        "all rich text must be stripped",
        "The response says rich HTML needs a wp_kses_post policy; text fields should be escaped.",
    )

    assert result.matched is False


def test_api_detected_handles_wordpress_wildcards():
    result = scorer.api_detected(
        "wp_ajax_nopriv_*",
        "Remove the wp_ajax_nopriv_acme_clear_flag hook for this editorial mutation.",
    )

    assert result.matched is True


def test_score_output_reads_rubric_domain_signals(tmp_path, monkeypatch):
    suites = tmp_path / "suites"
    results = tmp_path / "results"
    suite = "wordpress-security-critic"
    fixture = "fixture-a"
    rubric = suites / suite / "rubrics" / f"{fixture}.rubric.yaml"
    output = results / "saved-run" / "raw" / suite / "skill" / f"{fixture}.md"
    rubric.parent.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    rubric.write_text(
        """\
fixture: fixture-a
skill_under_test: wordpress-security-critic
domain_signals:
  expected_wordpress_apis:
    - "current_user_can"
    - "wp_ajax_nopriv_*"
  must_detect:
    - "nonce validation is not authorization"
    - "wp_ajax_nopriv_* should not expose privileged mutation"
  must_not_claim:
    - "production exploit proof"
""",
        encoding="utf-8",
    )
    output.write_text(
        """\
The review says nonce validation is not authorization. Remove the
wp_ajax_nopriv_acme_clear_flag hook because wp_ajax_nopriv should not expose
privileged mutation, and add current_user_can() for the post.
This is not production exploit proof.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(scorer, "SUITES_ROOT", suites)
    monkeypatch.setattr(scorer, "RESULTS_ROOT", results)

    score = scorer.score_output(suite, "saved-run", fixture, "skill")

    assert score.detected_count == 2
    assert score.api_matched_count == 2
    assert score.anti_claim_count == 0
    assert score.recall == 1
    assert score.api_coverage == 1
    assert score.specificity == 1
    assert score.composite == 1


def test_summary_and_scorecard_are_written(tmp_path):
    score = scorer.OutputScore(
        suite="wordpress-security-critic",
        fixture_id="fixture-a",
        condition="skill",
        output_path="out.md",
        rubric_path="rubric.yaml",
        recall=1.0,
        api_coverage=0.5,
        specificity=1.0,
        composite=0.8333333333,
        detected_count=2,
        must_detect_count=2,
        api_matched_count=1,
        api_count=2,
        anti_claim_count=0,
        anti_count=1,
        must_detect=[],
        expected_apis=[],
        must_not_claim=[],
    )
    summary = {
        "run_id": "run-a",
        "created_at": "2026-06-21T00:00:00Z",
        "suites": ["wordpress-security-critic"],
        "saved_runs": {"wordpress-security-critic": "saved-run"},
        "conditions": ["skill"],
        "include_smoke": False,
        "fixtures_by_suite": {"wordpress-security-critic": ["fixture-a"]},
        "evidence_boundary": "Deterministic lexical answer-key coverage only.",
        "by_suite_condition": scorer.summarize([score]),
        "scores": [score.__dict__],
    }

    scorer.write_json(tmp_path / "answer-key-summary.json", summary)
    scorer.write_scorecard(tmp_path / "scorecard.md", summary)

    assert json.loads((tmp_path / "answer-key-summary.json").read_text(encoding="utf-8"))["run_id"] == "run-a"
    assert "Deterministic lexical answer-key coverage only." in (tmp_path / "scorecard.md").read_text(encoding="utf-8")
