"""Unit tests for the answer-key diagnostic PURE logic (no LLM I/O).

Covers the span guard, deterministic API matching, parsing, per-output scoring, the
discrimination self-check, the cluster bootstrap (fixture-resampled), aggregation, and
judge agreement. The I/O transports (check_item_via_cli/codex) and orchestrate()/main()
are exercised only during a real run, after this passes.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import answer_key_score as ak
import invoke
import isolation
import run_pairwise_pilot as rpp


# --------------------------------------------------------------------------- #
# span guard
# --------------------------------------------------------------------------- #

def test_span_supported_exact_and_normalized():
    resp = "The handler is registered for wp_ajax_nopriv_update_member_status."
    assert ak.span_supported("wp_ajax_nopriv_update_member_status", resp)
    # case + whitespace insensitivity
    assert ak.span_supported("WP_AJAX_NOPRIV_update_member_status", resp)
    assert ak.span_supported("registered   for\n wp_ajax_nopriv_update_member_status", resp)


def test_span_supported_rejects_empty_and_fabricated():
    resp = "Use $wpdb->prepare and current_user_can checks."
    assert not ak.span_supported("", resp)
    assert not ak.span_supported("   ", resp)
    # judge fabricated a quote that is NOT in the response
    assert not ak.span_supported("the response recommends disabling all nonces", resp)


def test_span_supported_head_prefix_tolerance():
    resp = "x" * 100 + " the quick brown fox jumps over the lazy dog and then keeps going forever"
    long_quote = "the quick brown fox jumps over the lazy dog and then keeps going" + " EXTRA TAIL NOT PRESENT"
    # first 40 non-space chars are present -> tolerated truncation
    assert ak.span_supported(long_quote, resp)
    # but a short fabricated quote is not
    assert not ak.span_supported("totally different text", resp)


# --------------------------------------------------------------------------- #
# deterministic API matching
# --------------------------------------------------------------------------- #

def test_api_match_normalizes_sigils():
    assert ak.api_match("$wpdb->prepare", "always use $wpdb->prepare() for queries")
    assert ak.api_match("current_user_can", "call current_user_can() first")
    assert ak.api_match("wp_kses_post", "escape rich html with wp_kses_post")


def test_api_match_normalizes_paths_packages_and_commands():
    assert ak.api_match("@wordpress/scripts", "build with @wordpress/scripts")
    assert ak.api_match("templates/*.html", "review templates/*.html and parts/*.html")
    assert ak.api_match("WP-CLI", "run WP-CLI smoke commands")


def test_api_match_multitoken_requires_all():
    resp_both = "register a route via register_rest_route with a permission_callback"
    resp_one = "register a route via register_rest_route only"
    assert ak.api_match("register_rest_route permission_callback", resp_both)
    assert not ak.api_match("register_rest_route permission_callback", resp_one)


def test_api_match_miss():
    assert not ak.api_match("wp_kses_post", "we sanitize with sanitize_text_field everywhere")


def test_api_coverage_fraction():
    resp = "use current_user_can and $wpdb->prepare"
    cov = ak.api_coverage(["current_user_can", "$wpdb->prepare", "wp_kses_post"], resp)
    assert cov["n_matched"] == 2 and cov["n_total"] == 3
    assert math.isclose(cov["coverage"], 2 / 3)
    assert ak.api_coverage([], resp)["coverage"] is None


# --------------------------------------------------------------------------- #
# parsing + span-guarded confirmation
# --------------------------------------------------------------------------- #

def test_parse_check_clean_fenced_and_stringbool():
    assert ak.parse_check('{"present": true, "span": "x"}') == {"present": True, "span": "x", "parse_ok": True}
    fenced = "```json\n{\"present\": false, \"span\": \"\"}\n```"
    assert ak.parse_check(fenced)["present"] is False and ak.parse_check(fenced)["parse_ok"]
    assert ak.parse_check('{"present": "yes", "span": "q"}')["present"] is True


def test_parse_check_unparseable_is_flagged_not_silent_tie():
    out = ak.parse_check("the model rambled with no json")
    assert out["present"] is False and out["parse_ok"] is False


def test_confirm_item_span_guard_downgrades():
    resp = "Flags the unauthenticated wp_ajax_nopriv mutation as critical."
    # present + supported span -> confirmed
    good = ak.confirm_item({"present": True, "span": "unauthenticated wp_ajax_nopriv mutation", "parse_ok": True}, resp)
    assert good["confirmed"] and not good["unsupported_span"]
    # present + fabricated span -> downgraded to not-confirmed, flagged
    bad = ak.confirm_item({"present": True, "span": "recommends turning off auth", "parse_ok": True}, resp)
    assert not bad["confirmed"] and bad["unsupported_span"]
    # absent -> not confirmed, not flagged
    absent = ak.confirm_item({"present": False, "span": "", "parse_ok": True}, resp)
    assert not absent["confirmed"] and not absent["unsupported_span"]


# --------------------------------------------------------------------------- #
# per-output scoring
# --------------------------------------------------------------------------- #

def _conf(b, unsupported=False):
    return {"confirmed": b, "unsupported_span": unsupported, "parse_ok": True}


def test_score_output_three_axes():
    ak_key = {"must_detect": ["A", "B", "C"], "anti_patterns": ["X", "Y"],
              "expected_apis": ["current_user_can", "$wpdb->prepare"]}
    resp = "we call current_user_can here"  # matches 1 of 2 APIs
    detect = {"A": _conf(True), "B": _conf(False), "C": _conf(True)}   # recall 2/3
    anti = {"X": _conf(True), "Y": _conf(False)}                       # committed 1/2 -> spec 0.5
    s = ak.score_output(ak_key, resp, detect, anti)
    assert math.isclose(s["recall"], 2 / 3)
    assert math.isclose(s["api_coverage"], 0.5)
    assert math.isclose(s["specificity"], 0.5)
    assert math.isclose(s["composite"], (2 / 3 + 0.5 + 0.5) / 3)
    assert s["confirmed_detect"] == 2 and s["committed_anti"] == 1


def test_score_output_handles_empty_axes():
    s = ak.score_output({"must_detect": [], "anti_patterns": [], "expected_apis": []}, "x", {}, {})
    assert s["recall"] is None and s["specificity"] is None and s["api_coverage"] is None
    assert s["composite"] is None


# --------------------------------------------------------------------------- #
# discrimination self-check + bootstrap + aggregate + agreement
# --------------------------------------------------------------------------- #

def _scores_fixture(comp_by_key):
    """comp_by_key: {(fixture,cond,run): composite} -> scores dict of score_output-shaped rows."""
    return {k: {"recall": v, "api_coverage": v, "specificity": v, "composite": v} for k, v in comp_by_key.items()}


def test_discrimination_averages_runs_within_fixture():
    scores = _scores_fixture({
        ("f1", "zivtech_prototype", 1): 0.8, ("f1", "zivtech_prototype", 2): 0.8,
        ("f1", "baseline-zero-shot", 1): 0.5,
        ("f2", "zivtech_prototype", 1): 0.6,
        ("f2", "baseline-zero-shot", 1): 0.5,
    })
    d = ak.discrimination_check(scores, ["f1", "f2"])
    assert math.isclose(d["mean_delta"], 0.2)   # (0.3 + 0.1)/2
    assert d["discriminates"] is True           # >= 0.20 inclusive


def test_discrimination_below_threshold_flags_saturation():
    scores = _scores_fixture({
        ("f1", "zivtech_prototype", 1): 0.81, ("f1", "baseline-zero-shot", 1): 0.80,
        ("f2", "zivtech_prototype", 1): 0.79, ("f2", "baseline-zero-shot", 1): 0.80,
    })
    d = ak.discrimination_check(scores, ["f1", "f2"])
    assert d["discriminates"] is False


def test_cluster_bootstrap_is_deterministic_and_point_correct():
    scores = _scores_fixture({
        ("f1", "zivtech_prototype", 1): 0.8, ("f1", "baseline-few-shot", 1): 0.5,
        ("f2", "zivtech_prototype", 1): 0.6, ("f2", "baseline-few-shot", 1): 0.4,
    })
    a = ak.cluster_bootstrap_delta(scores, ["f1", "f2"], "zivtech_prototype", "baseline-few-shot", seed="t", n_boot=500)
    b = ak.cluster_bootstrap_delta(scores, ["f1", "f2"], "zivtech_prototype", "baseline-few-shot", seed="t", n_boot=500)
    assert a == b                                # deterministic under fixed seed
    assert math.isclose(a["mean_delta"], 0.25)   # (0.3 + 0.2)/2
    assert a["n_fixtures"] == 2
    assert a["ci95"][0] <= a["mean_delta"] <= a["ci95"][1]


def test_aggregate_by_condition_and_tier():
    scores = _scores_fixture({
        ("security-boundary-risk", "zivtech_prototype", 1): 0.9,
        ("performance-ops-clean", "zivtech_prototype", 1): 0.7,
    })
    tiers = {"security-boundary-risk": "HAS_RISK", "performance-ops-clean": "CLEAN_CONTROL"}
    agg = ak.aggregate(scores, ["zivtech_prototype"], tiers)
    assert math.isclose(agg["by_condition"]["zivtech_prototype"]["composite"], 0.8)
    assert math.isclose(agg["by_condition_tier"]["zivtech_prototype::HAS_RISK"]["composite"], 0.9)
    assert math.isclose(agg["by_condition_tier"]["zivtech_prototype::CLEAN_CONTROL"]["composite"], 0.7)


def test_judge_agreement_counts_and_lists_splits():
    p = {("f", "c", 1, "detect", "A"): _conf(True), ("f", "c", 1, "detect", "B"): _conf(False)}
    q = {("f", "c", 1, "detect", "A"): _conf(True), ("f", "c", 1, "detect", "B"): _conf(True)}
    ag = ak.judge_agreement(p, q)
    assert ag["n_items"] == 2 and math.isclose(ag["raw_agreement"], 0.5)
    assert len(ag["disagreements"]) == 1


# --------------------------------------------------------------------------- #
# prompt hygiene
# --------------------------------------------------------------------------- #

def test_build_check_prompt_kind_wording_and_blindness():
    detect = ak.build_check_prompt("FIXTURE", "RESPONSE", "SQL injection", "detect")
    anti = ak.build_check_prompt("FIXTURE", "RESPONSE", "invent bottlenecks", "anti")
    assert "identifies" in detect and "COMMITS this mistake" in anti
    assert '"present"' in detect and '"span"' in detect
    # never leaks a condition name (only fixture/item/response are passed in)
    for name in ("zivtech", "baseline", "few-shot", "zero-shot", "upstream"):
        assert name not in detect.lower()


def test_generate_missing_routes_baseline_to_codex(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(ak, "fixture_text", lambda fixture: f"fixture {fixture}")
    monkeypatch.setattr(rpp, "build_condition_prompt", lambda condition, fixture, text, upstream: ("baseline prompt", None))

    def fake_run_codex(prompt, *, timeout_sec, max_retries, model, effort):
        calls.append((prompt, timeout_sec, max_retries, model, effort))
        return "codex generated baseline", "", 0, 0.1

    monkeypatch.setattr(invoke, "_run_codex", fake_run_codex)
    monkeypatch.setattr(isolation, "run_isolated_generation", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Claude path should not run for baselines")))

    ak.generate_missing(
        ["security-boundary-risk"],
        ["baseline-zero-shot"],
        1,
        tmp_path,
        "claude-sonnet-4-6",
        tmp_path,
        123,
        lambda *_: None,
        baseline_model="gpt-5.5",
        baseline_effort="medium",
    )

    assert (tmp_path / "r1__security-boundary-risk__baseline-zero-shot.txt").read_text(encoding="utf-8") == "codex generated baseline"
    assert calls == [("baseline prompt", 123, 2, "gpt-5.5", "medium")]


def test_generate_missing_keeps_skill_lane_on_isolated_claude(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(ak, "fixture_text", lambda fixture: f"fixture {fixture}")
    monkeypatch.setattr(rpp, "build_condition_prompt", lambda condition, fixture, text, upstream: ("skill prompt", "agent prompt"))
    monkeypatch.setattr(invoke, "_run_codex", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Codex path should not run for skill lanes")))

    def fake_isolated(prompt, model, base, *, agent_prompt_text=None, timeout_sec=600):
        calls.append((prompt, model, agent_prompt_text, timeout_sec))
        return "claude generated skill", "", 0, {}

    monkeypatch.setattr(isolation, "run_isolated_generation", fake_isolated)

    ak.generate_missing(
        ["security-boundary-risk"],
        ["zivtech_prototype"],
        1,
        tmp_path,
        "claude-sonnet-4-6",
        tmp_path,
        321,
        lambda *_: None,
    )

    assert (tmp_path / "r1__security-boundary-risk__zivtech_prototype.txt").read_text(encoding="utf-8") == "claude generated skill"
    assert calls == [("skill prompt", "claude-sonnet-4-6", "agent prompt", 321)]
