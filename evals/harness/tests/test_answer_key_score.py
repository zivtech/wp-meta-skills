"""Unit tests for the answer-key diagnostic PURE logic (no LLM I/O).

Covers the span guard, deterministic API matching, parsing, per-output scoring, the
discrimination self-check, the cluster bootstrap (fixture-resampled), aggregation, and
judge agreement. The I/O transports (check_item_via_cli/codex) and orchestrate()/main()
are exercised only during a real run, after this passes.
"""
import json
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
# critic-corpus additive extension (§5 grounding sidecar + tranche reports)
# --------------------------------------------------------------------------- #

def test_grounding_for_items_maps_by_description_and_ignores_unlisted():
    sidecar = {"grounding": [
        {"description": "public REST permission_callback on a mutation", "cwe": "CWE-862",
         "file": "plugin.php", "line": 21, "severity": "CRITICAL"},
        {"description": "not in must_detect", "cwe": "CWE-79", "severity": "MINOR"},
        "malformed-non-dict-entry",
    ]}
    md = ["public REST permission_callback on a mutation", "some other item"]
    g = ak.grounding_for_items(sidecar, md)
    assert set(g) == {"public REST permission_callback on a mutation"}
    assert g["public REST permission_callback on a mutation"] == {
        "cwe": "CWE-862", "file": "plugin.php", "line": 21, "severity": "CRITICAL"}
    # a plain-string must_detect with no grounding entry is simply absent, never an error
    assert ak.grounding_for_items({}, ["x"]) == {}


def test_severity_recall_buckets_confirmed_by_grounding_severity():
    answer_keys = {"f": {"grounding": {
        "crit item": {"severity": "CRITICAL"}, "major item": {"severity": "MAJOR"}}}}
    detect_confirms = {
        ("f", "skill", 1): {"crit item": True, "major item": False, "ungrounded item": True},
    }
    sr = ak.severity_recall(detect_confirms, answer_keys, ["skill"],
                            {"f": "J"}, only_tranche="J")
    assert math.isclose(sr["skill"]["CRITICAL"]["recall"], 1.0)
    assert math.isclose(sr["skill"]["MAJOR"]["recall"], 0.0)
    assert math.isclose(sr["skill"]["UNGROUNDED"]["recall"], 1.0)
    # a non-J fixture is excluded when only_tranche='J'
    assert ak.severity_recall(detect_confirms, answer_keys, ["skill"],
                              {"f": "T"}, only_tranche="J")["skill"] == {}


def test_false_positive_rate_from_clean_tranche():
    scores = {
        ("clean1", "skill", 1): {"committed_anti": 1, "n_anti": 3},
        ("clean2", "skill", 1): {"committed_anti": 0, "n_anti": 2},
        ("riskyJ", "skill", 1): {"committed_anti": 5, "n_anti": 5},  # not tranche C -> ignored
    }
    tranche = {"clean1": "C", "clean2": "C", "riskyJ": "J"}
    fpr = ak.false_positive_rate(scores, ["skill"], tranche, clean_tranche="C")
    assert math.isclose(fpr["skill"]["false_positive_rate"], 1 / 5)
    assert fpr["skill"]["committed"] == 1 and fpr["skill"]["n_checks"] == 5


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


# --------------------------------------------------------------------------- #
# judge-family balance (prereg §4 confound control)
# --------------------------------------------------------------------------- #

def test_judge_family_mirrors_the_cli_routing_rule():
    # The CLI sends `claude*` to check_item_via_cli and everything else to codex.
    assert ak.judge_family("claude-sonnet-4-6") == ak.CLAUDE_FAMILY
    assert ak.judge_family("Claude-Opus-5") == ak.CLAUDE_FAMILY
    assert ak.judge_family("gpt-5.5") == ak.NON_CLAUDE_FAMILY


def test_condition_family_splits_skill_from_baseline_lanes():
    # generate_missing_critic: skill lane -> local Claude agent, baseline-* -> local Codex.
    assert ak.condition_family("skill") == ak.CLAUDE_FAMILY
    assert ak.condition_family("zivtech_prototype") == ak.CLAUDE_FAMILY
    assert ak.condition_family("baseline-zero-shot") == ak.NON_CLAUDE_FAMILY
    assert ak.condition_family("baseline-few-shot") == ak.NON_CLAUDE_FAMILY


def test_judges_span_families_requires_both_sides():
    assert not ak.judges_span_families(["gpt-5.5"])
    assert not ak.judges_span_families(["gpt-5.5", "gpt-5-mini"])
    assert ak.judges_span_families(["gpt-5.5", "claude-sonnet-4-6"])


def test_resolve_judge_panel_adds_the_counterpart_only_for_balanced():
    # primary mode is unchanged -- archived candidate-eval runs stay reproducible.
    assert ak.resolve_judge_panel("gpt-5.5", None, "primary") == ["gpt-5.5"]
    # balanced without --judge-2 must not silently degrade to a single-family panel.
    panel = ak.resolve_judge_panel("gpt-5.5", None, "balanced")
    assert ak.judges_span_families(panel)
    assert panel[0] == "gpt-5.5"
    # an explicit cross-family --judge-2 is respected as given.
    assert ak.resolve_judge_panel("gpt-5.5", "claude-sonnet-4-6", "balanced") == [
        "gpt-5.5", "claude-sonnet-4-6"]
    # a same-family --judge-2 still gets a counterpart appended.
    assert ak.judges_span_families(ak.resolve_judge_panel("gpt-5.5", "gpt-5-mini", "balanced"))


def test_balance_scores_means_judged_axes_and_keeps_deterministic_ones():
    per_judge = {
        "gpt-5.5": {("f1", "skill", 1): {
            "recall": 1.0, "api_coverage": 0.4, "specificity": 1.0, "composite": 0.8,
            "confirmed_detect": 2, "committed_anti": 0, "n_must_detect": 2, "n_anti": 1,
            "unsupported_spans": 1, "parse_failures": 0}},
        "claude-sonnet-4-6": {("f1", "skill", 1): {
            "recall": 0.5, "api_coverage": 0.4, "specificity": 1.0, "composite": 0.6,
            "confirmed_detect": 1, "committed_anti": 0, "n_must_detect": 2, "n_anti": 1,
            "unsupported_spans": 2, "parse_failures": 1}},
    }
    merged = ak.balance_scores(per_judge)[("f1", "skill", 1)]
    assert math.isclose(merged["recall"], 0.75)
    assert math.isclose(merged["composite"], 0.7)
    assert math.isclose(merged["confirmed_detect"], 1.5)
    # API coverage is deterministic, so averaging must not perturb it.
    assert math.isclose(merged["api_coverage"], 0.4)
    # counts of judge events are summed, not averaged
    assert merged["unsupported_spans"] == 3 and merged["parse_failures"] == 1
    # item counts are judge-invariant
    assert merged["n_must_detect"] == 2 and merged["n_anti"] == 1
    # nothing is hidden behind the mean
    assert math.isclose(merged["per_judge"]["gpt-5.5"]["recall"], 1.0)
    assert math.isclose(merged["per_judge"]["claude-sonnet-4-6"]["recall"], 0.5)


def test_balance_scores_uses_only_keys_every_judge_scored():
    per_judge = {
        "gpt-5.5": {("f1", "skill", 1): {"composite": 0.8}, ("f2", "skill", 1): {"composite": 0.2}},
        "claude-sonnet-4-6": {("f1", "skill", 1): {"composite": 0.6}},
    }
    merged = ak.balance_scores(per_judge)
    assert set(merged) == {("f1", "skill", 1)}


def test_balance_scores_empty_panel_is_not_an_error():
    assert ak.balance_scores({}) == {}


def test_mean_severity_recall_averages_across_judges():
    a = {"skill": {"CRITICAL": {"recall": 1.0, "n": 2}, "MAJOR": {"recall": 0.5, "n": 4}}}
    b = {"skill": {"CRITICAL": {"recall": 0.0, "n": 2}}}
    out = ak.mean_severity_recall([a, b])
    assert math.isclose(out["skill"]["CRITICAL"]["recall"], 0.5)
    # n counts checks, not judges
    assert out["skill"]["CRITICAL"]["n"] == 2
    # a severity only one judge bucketed still reports that judge's rate
    assert math.isclose(out["skill"]["MAJOR"]["recall"], 0.5)


def test_judge_self_preference_signs_the_confound_per_condition():
    # Each judge favours the family that generated the output: the exact asymmetry that
    # a single non-Claude judge would have charged entirely to the Claude-generated skill.
    per_judge = {
        "gpt-5.5": {  # non-Claude judge
            ("f1", "skill", 1): {"composite": 0.5},
            ("f1", "baseline-zero-shot", 1): {"composite": 0.9},
        },
        "claude-sonnet-4-6": {  # Claude judge
            ("f1", "skill", 1): {"composite": 0.7},
            ("f1", "baseline-zero-shot", 1): {"composite": 0.6},
        },
    }
    pref = ak.judge_self_preference(per_judge, ["skill", "baseline-zero-shot"])
    skill = pref["by_condition"]["skill"]
    assert skill["generated_by"] == ak.CLAUDE_FAMILY
    # same-family (claude judge) 0.7 - cross-family (gpt judge) 0.5
    assert math.isclose(skill["self_preference_delta"], 0.2)
    base = pref["by_condition"]["baseline-zero-shot"]
    assert base["generated_by"] == ak.NON_CLAUDE_FAMILY
    # same-family (gpt judge) 0.9 - cross-family (claude judge) 0.6
    assert math.isclose(base["self_preference_delta"], 0.3)
    assert math.isclose(pref["mean_self_preference_delta"], 0.25)


def test_judge_self_preference_is_none_when_a_family_never_judged():
    per_judge = {"gpt-5.5": {("f1", "skill", 1): {"composite": 0.5}}}
    pref = ak.judge_self_preference(per_judge, ["skill"])
    assert pref["by_condition"]["skill"]["self_preference_delta"] is None
    assert pref["mean_self_preference_delta"] is None


def _self_preferring_check_fn(response_marker="DETECTED"):
    """A judge panel that favours its own family: the Claude judge confirms only for the
    Claude-generated lane, the codex judge only for the codex-generated lane. This is the
    confound in its purest form, so the two modes must visibly differ."""
    def check_fn(judge, prompt):
        # The prompt embeds the response; recover which lane it came from by marker.
        lane = ak.CLAUDE_FAMILY if response_marker + "-claude" in prompt else ak.NON_CLAUDE_FAMILY
        present = ak.judge_family(judge) == lane
        return json.dumps({"present": present, "span": "the nonce result is discarded here"})
    return check_fn


def _orchestrate_kwargs():
    span = "the nonce result is discarded here"
    answer_keys = {"f1": {"must_detect": [span], "anti_patterns": [],
                          "expected_apis": [], "grounding": {}}}
    return {
        "fixtures": ["f1"],
        "conditions": ["skill", "baseline-zero-shot"],
        "runs": 1,
        "answer_keys": answer_keys,
        "fixture_texts": {"f1": "fixture body"},
        "tiers": {"f1": "J"},
        "gens": {
            ("f1", "skill", 1): f"DETECTED-claude: {span}",
            ("f1", "baseline-zero-shot", 1): f"DETECTED-codex: {span}",
        },
        "check_fn": _self_preferring_check_fn(),
        "strong": "skill",
        "weak": "baseline-zero-shot",
    }


def test_orchestrate_primary_mode_charges_the_confound_to_the_cross_family_lane():
    """One non-Claude judge + a Claude-generated skill lane = the pilot's setup. The skill
    scores 0 and the codex-generated baseline scores 1 purely from judge family."""
    out = ak.orchestrate(judges=["gpt-5.5", "claude-sonnet-4-6"], judge_mode="primary",
                         **_orchestrate_kwargs())
    agg = out["aggregate"]["by_condition"]
    assert out["judge_mode"] == "primary"
    assert math.isclose(agg["skill"]["recall"], 0.0)
    assert math.isclose(agg["baseline-zero-shot"]["recall"], 1.0)


def test_orchestrate_balanced_mode_cancels_the_family_asymmetry():
    """Same panel, same generations, balanced scoring: each lane gets one same-family and
    one cross-family judgment, so the family-driven gap disappears."""
    out = ak.orchestrate(judges=["gpt-5.5", "claude-sonnet-4-6"], judge_mode="balanced",
                         **_orchestrate_kwargs())
    agg = out["aggregate"]["by_condition"]
    assert out["judge_mode"] == "balanced"
    assert out["judge_family_balanced"] is True
    assert math.isclose(agg["skill"]["recall"], 0.5)
    assert math.isclose(agg["baseline-zero-shot"]["recall"], 0.5)
    # and the effect it cancelled is reported rather than buried
    pref = out["judge_self_preference"]
    assert math.isclose(pref["by_condition"]["skill"]["self_preference_delta"], 1.0)
    assert math.isclose(pref["by_condition"]["baseline-zero-shot"]["self_preference_delta"], 1.0)


def test_orchestrate_balanced_falls_back_to_primary_on_a_single_judge():
    """Balanced is meaningless with one judge; it must degrade to primary and say so
    rather than pretend the confound is controlled."""
    out = ak.orchestrate(judges=["gpt-5.5"], judge_mode="balanced", **_orchestrate_kwargs())
    assert out["judge_mode"] == "primary"
    assert out["judge_family_balanced"] is False
    assert "judge_self_preference" not in out
