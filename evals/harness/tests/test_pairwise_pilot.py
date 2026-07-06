#!/usr/bin/env python3
"""Tests for the pairwise pilot orchestration core (no LLM calls).

Injects stub generate_fn / judge_fn to verify the wiring end to end:
refusal quarantine + half-invalid drop, two-judge reliability, the preference
gate (clear win passes; coin-flip does not), and the internal-only firewall.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import invoke  # noqa: E402
import run_pairwise_pilot as rpp  # noqa: E402
from run_pairwise_pilot import orchestrate, ALL_CONTRASTS  # noqa: E402

CONDS = ["baseline-zero-shot", "baseline-few-shot", "raw_upstream_candidate", "zivtech_prototype"]
FIXTURES = ["security-boundary-risk", "performance-ops-clean"]
STRONG, WEAK = "zivtech_prototype", "baseline-zero-shot"

VALID_BODY = "## Plan\n\n" + ("Register taxonomies with show_in_rest; tax_query is indexed. " * 25)


def test_codex_baseline_generation_uses_shared_codex_lane(monkeypatch):
    calls = []

    def fake_run_codex(prompt, *, timeout_sec, max_retries, model, effort):
        calls.append((prompt, timeout_sec, max_retries, model, effort))
        return "codex baseline output", "", 0, 0.1

    monkeypatch.setattr(invoke, "_run_codex", fake_run_codex)

    out = rpp.run_codex_baseline_generation(
        "baseline prompt",
        model="gpt-5.5",
        effort="medium",
        timeout_sec=123,
    )

    assert out == "codex baseline output"
    assert calls == [("baseline prompt", 123, 2, "gpt-5.5", "medium")]


def test_generation_model_summary_does_not_relabel_gen_from_outputs():
    args = SimpleNamespace(
        gen_from="historical-run",
        baseline_model="gpt-5.5",
        baseline_effort="medium",
        generation_model="claude-sonnet-4-6",
    )
    counts = {
        "current_run_cache": 0,
        "reused_from_source": 48,
        "generated_codex_baseline": 0,
        "generated_claude_candidate": 0,
    }

    summary = rpp.build_generation_models_summary(args, counts)

    assert summary["generation_source"] == "reused-checkpoint-with-current-run-fill"
    assert summary["reused_from"] == "historical-run"
    assert "warning" in summary
    assert summary["missing_generation_fill_models"]["baseline_model"] == "gpt-5.5"
    assert summary["provenance_counts"]["reused_from_source"] == 48


def gen_valid_with_one_refusal(fixture, cond, run):
    # one true refusal: zivtech on performance-ops-clean, run 1 -> should quarantine
    if fixture == "performance-ops-clean" and cond == "zivtech_prototype" and run == 1:
        return "No candidate response was included. Paste it and I'll score."
    return f"## Plan for {cond}\n\n" + VALID_BODY


def _slot_a_segment(prompt):
    return prompt.split("## Response A", 1)[1].split("## Response B", 1)[0]


def judge_strong_wins(judge_model, prompt):
    winner = "A" if STRONG in _slot_a_segment(prompt) else "B"
    return json.dumps({"winner": winner, "reasoning": "stub: prefers strong"})


def judge_always_A(judge_model, prompt):
    return json.dumps({"winner": "A", "reasoning": "stub: always A"})


def _run(generate_fn, judge_fn, judges=("opus", "opus2"), runs=3, progress_fn=None):
    return orchestrate(
        fixtures=FIXTURES, conditions=CONDS, contrasts=ALL_CONTRASTS,
        known_strong=STRONG, known_weak=WEAK, runs=runs, judges=list(judges),
        generate_fn=generate_fn, judge_fn=judge_fn,
        fixture_text_fn=lambda f: f"Fixture {f}", seed="t", progress_fn=progress_fn)


def test_progress_callback_counts():
    events = []
    _run(lambda f, c, r: f"## Plan for {c}\n\n" + VALID_BODY, judge_strong_wins,
         runs=1, progress_fn=lambda phase, i, n, label: events.append((phase, i, n)))
    gen = [e for e in events if e[0] == "generate"]
    judge = [e for e in events if e[0] == "judge"]
    # 1 run x 2 fixtures x 4 conditions = 8 generations
    assert gen[-1][1] == 8 and all(e[2] == 8 for e in gen)
    # 2 fixtures x 6 contrasts x 2 judges = 24 judge calls (clean run, none dropped)
    assert judge[-1][1] == 24 and all(e[2] == 24 for e in judge)
    # counters are monotonic 1..N
    assert [e[1] for e in gen] == list(range(1, 9))


def test_refusal_quarantined_and_pairs_dropped():
    s = _run(gen_valid_with_one_refusal, judge_strong_wins)
    assert s["review_queue_count"] == 1
    q = s["review_queue"][0]
    assert q["fixture"] == "performance-ops-clean" and q["condition"] == "zivtech_prototype"
    # the 3 contrasts involving zivtech in that (run1, perf) pairing are dropped
    assert len(s["dropped_pairs"]) == 3
    assert all("zivtech_prototype" in d["contrast"] for d in s["dropped_pairs"])


def test_clear_win_passes_both_gates():
    s = _run(gen_valid_with_one_refusal, judge_strong_wins)
    pref = s["preference_primary_judge"]
    assert pref["preference_passes"] is True
    assert pref["win_rate"] >= 0.6 and pref["ci_excludes_half"] is True
    assert pref["pairwise_saturated"] is False
    # two identical judges -> perfect reliability
    assert s["reliability"]["ac1_nominal"] == 1.0
    assert s["reliability_passes"] is True
    assert s["both_gates_clear"] is True
    assert s["twentyseven_fixture_unblock"] is True
    assert s["human_anchor_next"] is True  # Decision A fires only because AC1 cleared


def test_coinflip_does_not_pass_preference():
    s = _run(lambda f, c, r: f"## Plan for {c}\n\n" + VALID_BODY, judge_always_A)
    # always-A: strong wins only when randomized into slot A (~half) -> ~0.5
    assert s["preference_primary_judge"]["preference_passes"] is False


def test_internal_only_firewall_present():
    s = _run(gen_valid_with_one_refusal, judge_strong_wins)
    assert s["internal_only"] is True
    assert "superiority" in s["firewall"].lower()


def test_no_refusal_clean_run_has_empty_queue():
    s = _run(lambda f, c, r: f"## Plan for {c}\n\n" + VALID_BODY, judge_strong_wins)
    assert s["review_queue_count"] == 0
    assert s["dropped_pairs"] == []


def test_auth_failure_fails_fast():
    # simulate isolation breaking auth: every generation returns "Not logged in"
    def gen_auth_error(f, c, r):
        return "Not logged in · Please run /login"
    try:
        _run(gen_auth_error, judge_strong_wins)
        raise AssertionError("expected RuntimeError on systemic auth failure")
    except RuntimeError as e:
        assert "auth" in str(e).lower() or "logged in" in str(e).lower()


def test_all_quarantined_no_pairs_fails_fast():
    # non-auth but all short/structureless -> all review -> no pairs
    def gen_all_review(f, c, r):
        return "where is it?"
    try:
        _run(gen_all_review, judge_strong_wins)
        raise AssertionError("expected RuntimeError when no valid pairs survive")
    except RuntimeError:
        pass


def _main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
