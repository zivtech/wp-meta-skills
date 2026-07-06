#!/usr/bin/env python3
"""Blind pairwise preference judging for the WordPress candidate pilot.

Replaces saturated absolute scoring. For each fixture and each condition pair, the
judge sees two anonymized outputs (A/B, order randomized) and returns a preference
(A / B / tie) with reasoning. Two judges run independent blinded passes; their
preference labels feed the 3-way reliability gate (compute_kappa.agreement_report_multi).

This module separates PURE logic (pairing, anonymization, parsing, aggregation —
all unit-tested) from the LLM I/O (`judge_pair_via_cli`, which shells out to
`claude -p` and is exercised only during an actual run, after the GATE 1
test-critic ACCEPT). Nothing here is executed during the build/verify phase.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

# Frozen preference-signal thresholds (pre-reg §5).
WIN_RATE_FLOOR = 0.60
TIE_RATE_CAP = 0.40
PREF_CATEGORIES = ["A", "B", "tie"]
ORDERED_FOR_RELIABILITY = ["A", "tie", "B"]  # ordinal scale for weighted AC1


@dataclass
class Pairing:
    fixture_id: str
    cond_a: str            # condition shown in slot A (after randomization)
    cond_b: str            # condition shown in slot B
    text_a: str
    text_b: str
    # de-anonymization: which real condition each slot holds
    slot_map: dict[str, str] = field(default_factory=dict)


@dataclass
class Preference:
    fixture_id: str
    cond_a: str
    cond_b: str
    winner_slot: str       # "A" | "B" | "tie"
    winner_condition: str  # de-anonymized real condition, or "tie"
    reasoning: str
    judge: str


# --------------------------------------------------------------------------- #
# PURE: pairing + anonymization
# --------------------------------------------------------------------------- #

def make_pairings(fixture_id, condition_outputs, validity_labels, contrasts, seed):
    """Build blind A/B pairings for one fixture.

    condition_outputs: {condition: output_text}
    validity_labels:   {condition: "valid"|"review"|"invalid"} from the gate.
    contrasts:         iterable of (cond_x, cond_y) condition pairs to compare.
    Half-invalid rule (pre-reg §5): if either side is not `valid`, DROP the pair.
    A/B slot order is randomized per pairing from `seed`.

    Returns (pairings, dropped) where dropped lists (contrast, reason).
    """
    rng = random.Random(f"{seed}:{fixture_id}")
    pairings, dropped = [], []
    for cx, cy in contrasts:
        lx = validity_labels.get(cx)
        ly = validity_labels.get(cy)
        if lx != "valid" or ly != "valid":
            dropped.append(((cx, cy), f"{cx}={lx}, {cy}={ly}"))
            continue
        # randomize which real condition occupies slot A
        if rng.random() < 0.5:
            sa, sb = cx, cy
        else:
            sa, sb = cy, cx
        pairings.append(Pairing(
            fixture_id=fixture_id, cond_a=sa, cond_b=sb,
            text_a=condition_outputs[sa], text_b=condition_outputs[sb],
            slot_map={"A": sa, "B": sb},
        ))
    return pairings, dropped


def build_judge_prompt(fixture_text, text_a, text_b, criteria_block=""):
    """Pure: assemble the blind A/B judging prompt (judging v2 — rubric-anchored).

    Both responses are graded against the SAME explicit per-fixture rubric
    (criteria_block: weighted criteria + must-detect items + expected APIs +
    pitfalls), not on overall impression. Shared, concrete criteria are what raise
    inter-judge agreement above gestalt 'which is better?' judging. No condition
    names leak."""
    return (
        "You are a blind pairwise judge for WordPress consulting outputs. Two "
        "responses (A and B) answer the SAME fixture. Decide which is better using "
        "ONLY the rubric below — grade BOTH against the same criteria item by item; "
        "do not rely on overall vibe, length, or formatting.\n\n"
        f"## Fixture\n{fixture_text.strip()}\n\n"
        + (f"## Rubric — grade A and B against exactly these\n{criteria_block.strip()}\n\n"
           if criteria_block else "")
        + f"## Response A\n{text_a.strip()}\n\n## Response B\n{text_b.strip()}\n\n"
        "## How to decide (apply in order)\n"
        "1. For each weighted criterion, judge which response is stronger; higher "
        "weight matters more.\n"
        "2. A must-detect item is decisive: a response that catches a required issue "
        "the other misses wins on that axis.\n"
        "3. Penalize a response that commits a listed pitfall, invents issues on a "
        "clean scenario, or makes unsupported claims.\n"
        "4. Choose 'tie' ONLY if, after weighing every criterion, neither is clearly "
        "stronger AND neither caught a required item the other missed. Ties are rare.\n\n"
        "## Output\nReturn ONLY a strict JSON object, nothing before or after it:\n"
        '{"winner": "A"|"B"|"tie", "reasoning": "name the deciding criteria and the '
        'specific must-detect items each response caught or missed"}'
    )


def parse_preference(raw):
    """Pure: extract (winner, reasoning, parse_ok) from a judge response. Tolerant
    of fences/prose around the JSON. On failure returns ("tie", ..., False) so the
    run can log parse failures SEPARATELY rather than silently counting them as
    substantive ties (which would bias the tie-rate / saturation guard)."""
    s = (raw or "").strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start:end + 1])
            w = str(obj.get("winner", "")).strip().lower()
            if w in {"a", "b", "tie"}:
                return {"a": "A", "b": "B", "tie": "tie"}[w], str(obj.get("reasoning", "")).strip(), True
        except json.JSONDecodeError:
            pass
    return "tie", "unparseable judge response", False


def to_preference(pairing, winner_slot, reasoning, judge):
    cond = "tie" if winner_slot == "tie" else pairing.slot_map[winner_slot]
    return Preference(pairing.fixture_id, pairing.cond_a, pairing.cond_b,
                      winner_slot, cond, reasoning, judge)


# --------------------------------------------------------------------------- #
# PURE: aggregation + preference-signal gate
# --------------------------------------------------------------------------- #

def _binom_two_sided_p(k, n, p=0.5):
    """Exact two-sided binomial test p-value (no scipy)."""
    if n == 0:
        return 1.0
    def pmf(i):
        return math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    obs = pmf(k)
    return min(1.0, sum(pmf(i) for i in range(n + 1) if pmf(i) <= obs + 1e-12))


def aggregate_preferences(preferences, known_strong, known_weak, seed="agg", n_boot=2000):
    """Win-rate of known_strong over known_weak across the strong-vs-weak contrast,
    with bootstrap CI, tie-rate, and a sign/binomial test. Decisive = non-tie."""
    relevant = [p for p in preferences
                if {p.cond_a, p.cond_b} == {known_strong, known_weak}]
    n = len(relevant)
    ties = sum(1 for p in relevant if p.winner_slot == "tie")
    strong_wins = sum(1 for p in relevant if p.winner_condition == known_strong)
    weak_wins = sum(1 for p in relevant if p.winner_condition == known_weak)
    decisive = strong_wins + weak_wins
    win_rate = (strong_wins / decisive) if decisive else float("nan")
    tie_rate = (ties / n) if n else float("nan")

    # bootstrap CI on win-rate over decisive pairs
    outcomes = [1] * strong_wins + [0] * weak_wins
    lo = hi = float("nan")
    if outcomes:
        rng = random.Random(seed)
        boots = []
        for _ in range(n_boot):
            samp = [outcomes[rng.randrange(len(outcomes))] for _ in outcomes]
            boots.append(sum(samp) / len(samp))
        boots.sort()
        lo = boots[int(0.025 * len(boots))]
        hi = boots[min(len(boots) - 1, int(0.975 * len(boots)))]

    p_value = _binom_two_sided_p(strong_wins, decisive) if decisive else 1.0
    ci_excludes_half = (not math.isnan(lo)) and (lo > 0.5 or hi < 0.5)

    passes = (
        decisive > 0
        and not math.isnan(win_rate) and win_rate >= WIN_RATE_FLOOR
        and ci_excludes_half
        and not math.isnan(tie_rate) and tie_rate <= TIE_RATE_CAP
    )
    saturated = (not math.isnan(tie_rate)) and tie_rate > TIE_RATE_CAP
    return {
        "contrast": f"{known_strong} vs {known_weak}",
        "n_pairs": n, "ties": ties, "strong_wins": strong_wins, "weak_wins": weak_wins,
        "win_rate": None if math.isnan(win_rate) else round(win_rate, 4),
        "win_rate_ci95": [None if math.isnan(lo) else round(lo, 4),
                          None if math.isnan(hi) else round(hi, 4)],
        "ci_excludes_half": ci_excludes_half,
        "tie_rate": None if math.isnan(tie_rate) else round(tie_rate, 4),
        "tie_rate_cap": TIE_RATE_CAP,
        "binomial_p": round(p_value, 4),
        "win_rate_floor": WIN_RATE_FLOOR,
        "preference_passes": passes,
        "pairwise_saturated": saturated,  # all-ties degenerate guard
    }


def benjamini_hochberg(pvalues, alpha=0.05):
    """BH-FDR across the (up to 6) condition-pair contrasts (pre-reg §5)."""
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    m = len(pvalues)
    passed = [False] * m
    for rank, (idx, p) in enumerate(indexed, start=1):
        if p <= (rank / m) * alpha:
            for r2 in range(rank):
                passed[indexed[r2][0]] = True
    return passed


def reliability_between_judges(prefs_judge1, prefs_judge2):
    """3-way A/B/tie reliability between two judges' winner_slot labels over the
    same pairings. Returns the agreement_report_multi dict."""
    from compute_kappa import agreement_report_multi
    key = lambda p: (p.fixture_id, frozenset((p.cond_a, p.cond_b)))
    m1 = {key(p): p.winner_slot for p in prefs_judge1}
    m2 = {key(p): p.winner_slot for p in prefs_judge2}
    shared = sorted(set(m1) & set(m2), key=lambda k: str(k))
    r1 = [m1[k] for k in shared]
    r2 = [m2[k] for k in shared]
    return agreement_report_multi(r1, r2, PREF_CATEGORIES, ordered=ORDERED_FOR_RELIABILITY)


# --------------------------------------------------------------------------- #
# I/O (NOT exercised during build/verify; runs only after GATE 1 ACCEPT)
# --------------------------------------------------------------------------- #

def judge_pair_via_cli(model, prompt, *, env=None, timeout_sec=600):  # pragma: no cover
    """Shell out to a local Claude judge. Kept thin and side-effect-isolated."""
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--tools", "",
         "--permission-mode", "bypassPermissions"],
        input=prompt, text=True, capture_output=True, timeout=timeout_sec,
        check=False, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"judge CLI failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def judge_pair_via_codex(model, prompt, *, timeout_sec=600):  # pragma: no cover
    """Shell out to a non-Claude (OpenAI) judge via the local `codex` CLI, run
    NON-agentically so it behaves as a pure pairwise judge: read-only sandbox (no
    file writes), ephemeral session, project/user rules ignored, and the final
    message constrained to the {winner, reasoning} schema and captured via
    --output-last-message. This is the pre-reg branch-(b) cross-family judge that
    tests whether the Claude-vs-Claude reliability is real agreement or shared
    family correlation. Auth is codex's own (ChatGPT) — no ANTHROPIC_API_KEY."""
    import os
    import tempfile
    schema = {
        "type": "object",
        "properties": {
            "winner": {"type": "string", "enum": ["A", "B", "tie"]},
            "reasoning": {"type": "string"},
        },
        "required": ["winner", "reasoning"],
        "additionalProperties": False,
    }
    with tempfile.TemporaryDirectory(prefix="wp-codex-judge-") as d:
        schema_path = os.path.join(d, "schema.json")
        out_path = os.path.join(d, "last.txt")
        with open(schema_path, "w", encoding="utf-8") as fh:
            json.dump(schema, fh)
        # MEDIUM reasoning effort: xhigh is pathologically slow on long A/B rubric
        # prompts and blew past the 900s per-call timeout, crashing the batch. medium
        # reaches the same verdicts far faster (verified on a real pairing).
        argv = [
            "codex", "exec", "--model", model,
            "-c", "model_reasoning_effort=medium",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "--ignore-rules", "--color", "never",
            "--output-schema", schema_path, "--output-last-message", out_path, "-",
        ]
        proc = None
        for _attempt in range(2):
            try:
                proc = subprocess.run(
                    argv, input=prompt, text=True, capture_output=True,
                    timeout=timeout_sec, check=False,
                )
                break
            except subprocess.TimeoutExpired:
                if _attempt == 0:
                    continue
                return ""  # degrade to a parse failure rather than crash the batch
        if proc.returncode != 0:
            raise RuntimeError(f"codex judge failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
        try:
            with open(out_path, encoding="utf-8") as fh:
                text = fh.read().strip()
        except FileNotFoundError:
            text = ""
    return text or proc.stdout.strip()
