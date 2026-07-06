#!/usr/bin/env python3
"""Compute human-vs-judge agreement from exported Phase 0c annotations.

Usage:
  python3 compute_kappa.py <human-annotations.json>

Reads LLM modal votes from scores_cache.json, compares against human ratings,
and reports Cohen's kappa as the Phase 0 gate. Gwet's AC1 and PABAK are
included as prevalence-robust diagnostics, not as replacement gates.
"""

import json
import random
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
SCORES_CACHE = ROOT / "evals" / "results" / "judge-reliability" / "scores_cache.json"
REPORT_PATH = ROOT / "evals" / "results" / "judge-reliability" / "report.json"
KAPPA_RESULT_PATH = ROOT / "evals" / "results" / "judge-reliability" / "kappa-result.json"
KAPPA_THRESHOLD = 0.7


def normalize_annotation_mode(raw):
    if raw in {"ai_assisted_human_review", "ai_assisted_human_reviewed"}:
        return "ai_assisted_human_reviewed"
    if raw in {"blind_human", "human"}:
        return "blind_human"
    if raw == "ai_assisted_draft":
        return "ai_assisted_draft"
    return "legacy_unknown"


def load_llm_modal_votes():
    with open(SCORES_CACHE) as f:
        data = json.load(f)
    by_criterion = defaultdict(list)
    for entry in data:
        for c in entry["criteria"]:
            key = (entry["fixture_id"], c["criterion_id"])
            by_criterion[key].append(c["met"])
    modal = {}
    for (fid, cid), votes in by_criterion.items():
        met_count = sum(1 for v in votes if v)
        modal[(fid, cid)] = met_count > len(votes) / 2
    return modal


def cohens_kappa(rater1, rater2):
    n = len(rater1)
    assert n == len(rater2), "Rater vectors must be same length"
    assert n > 0, "Need at least one observation"

    a = sum(1 for r1, r2 in zip(rater1, rater2) if r1 and r2)
    b = sum(1 for r1, r2 in zip(rater1, rater2) if r1 and not r2)
    c = sum(1 for r1, r2 in zip(rater1, rater2) if not r1 and r2)
    d = sum(1 for r1, r2 in zip(rater1, rater2) if not r1 and not r2)

    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)

    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def gwets_ac1(rater1, rater2):
    n = len(rater1)
    assert n == len(rater2)
    assert n > 0

    a = sum(1 for r1, r2 in zip(rater1, rater2) if r1 and r2)
    d = sum(1 for r1, r2 in zip(rater1, rater2) if not r1 and not r2)

    po = (a + d) / n

    pi_met = (sum(rater1) + sum(rater2)) / (2 * n)
    pi_not = 1 - pi_met
    pe = 2 * pi_met * pi_not

    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def pabak(rater1, rater2):
    n = len(rater1)
    po = sum(1 for r1, r2 in zip(rater1, rater2) if r1 == r2) / n
    return 2 * po - 1


# ---------------------------------------------------------------------------
# Multi-category (3-way A/B/tie) agreement — ADDITIVE.
# The binary path above (Phase 0c gate) is unchanged. These functions support the
# WordPress pairwise pilot's reliability gate. Each reduces to its binary
# counterpart at K=2 (enforced by tests/test_agreement_multi.py).
# K is the DECLARED category count, never inferred from observed data, so a
# degenerate column cannot cause a divide-by-(K-1) error.
# ---------------------------------------------------------------------------

def _declared_categories(rater1, rater2, categories=None):
    if categories is not None:
        return list(categories)
    return sorted(set(rater1) | set(rater2))


def _marginals(rater1, rater2, categories):
    """Mean marginal proportion of each category across the two raters."""
    n = len(rater1)
    return {c: (rater1.count(c) + rater2.count(c)) / (2 * n) for c in categories}


def _identity_weight(a, b):
    return 1.0 if a == b else 0.0


def linear_ordinal_weight(ordered_categories):
    """Return w(a,b) = 1 - |rank(a)-rank(b)| / (K-1) for an ordered scale
    (e.g. A < tie < B). A polar flip (A vs B) scores a larger disagreement than
    an adjacent near-miss (A vs tie)."""
    rank = {c: i for i, c in enumerate(ordered_categories)}
    k = len(ordered_categories)
    dmax = (k - 1) or 1

    def w(a, b):
        return 1.0 - abs(rank[a] - rank[b]) / dmax

    return w


def _weight_matrix_total(categories, weight):
    return sum(weight(a, b) for a in categories for b in categories)


def gwets_ac1_multi(rater1, rater2, categories=None, weight=None):
    """Gwet's AC1, multi-category, optionally weighted.

    Chance agreement: pe = (Tw / (K(K-1))) * Σ_k πk(1-πk),
    where Tw = Σ_{a,b} w(a,b) and πk are mean marginals. With identity weights
    Tw = K, so pe = (1/(K-1)) Σ_k πk(1-πk) — the canonical Gwet form, which at
    K=2 equals the binary tool's 2·π·(1-π).
    """
    n = len(rater1)
    assert n == len(rater2) and n > 0
    cats = _declared_categories(rater1, rater2, categories)
    k = len(cats)
    if k < 2:
        return 1.0  # single declared category: perfect agreement, no chance correction
    w = weight or _identity_weight
    pa = sum(w(a, b) for a, b in zip(rater1, rater2)) / n
    pi = _marginals(rater1, rater2, cats)
    sum_pi = sum(pi[c] * (1 - pi[c]) for c in cats)
    tw = _weight_matrix_total(cats, w)
    pe = (tw / (k * (k - 1))) * sum_pi
    if pe == 1.0:
        return 1.0 if pa == 1.0 else 0.0
    return (pa - pe) / (1 - pe)


def cohens_kappa_multi(rater1, rater2, categories=None):
    """Nominal multi-category Cohen's kappa. Reduces to binary cohens_kappa."""
    n = len(rater1)
    assert n == len(rater2) and n > 0
    cats = _declared_categories(rater1, rater2, categories)
    po = sum(1 for a, b in zip(rater1, rater2) if a == b) / n
    p1 = {c: rater1.count(c) / n for c in cats}
    p2 = {c: rater2.count(c) / n for c in cats}
    pe = sum(p1[c] * p2[c] for c in cats)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def pabak_multi(rater1, rater2, categories=None):
    """Prevalence-and-bias-adjusted kappa, multi-category:
    PABAK = (K*po - 1)/(K-1). At K=2 this is 2*po - 1 (the binary pabak)."""
    n = len(rater1)
    cats = _declared_categories(rater1, rater2, categories)
    k = len(cats)
    po = sum(1 for a, b in zip(rater1, rater2) if a == b) / n
    if k < 2:
        return 1.0 if po == 1.0 else 0.0
    return (k * po - 1) / (k - 1)


def bootstrap_ci(rater1, rater2, stat, n_boot=2000, alpha=0.05, seed="pairwise"):
    """Percentile bootstrap CI for a paired agreement statistic.

    Resamples the paired items with replacement. Returns (lo, hi). Note: for very
    small n (~12) these CIs are themselves unstable — the pre-reg pins percentile
    method and treats a wide CI as a directional-only signal, not a hard gate."""
    rng = random.Random(seed)
    n = len(rater1)
    pairs = list(zip(rater1, rater2))
    vals = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        s1 = [a for a, _ in sample]
        s2 = [b for _, b in sample]
        try:
            vals.append(stat(s1, s2))
        except (ZeroDivisionError, AssertionError):
            continue
    vals.sort()
    if not vals:
        return (float("nan"), float("nan"))
    lo = vals[int((alpha / 2) * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return (lo, hi)


def agreement_report_multi(rater1, rater2, categories, ordered=None,
                           ac1_floor=0.70, n_boot=2000):
    """Full reliability report for the pairwise gate: nominal AC1/kappa/PABAK
    (primary AC1 + reported kappa/PABAK), ordinal-weighted AC1 cross-check, and a
    bootstrap CI on AC1 whose LOWER BOUND is compared to the floor."""
    cats = list(categories)
    nominal_ac1 = gwets_ac1_multi(rater1, rater2, cats)
    weighted_ac1 = None
    if ordered is not None:
        weighted_ac1 = gwets_ac1_multi(rater1, rater2, cats,
                                       weight=linear_ordinal_weight(ordered))
    lo, hi = bootstrap_ci(rater1, rater2,
                          lambda a, b: gwets_ac1_multi(a, b, cats),
                          n_boot=n_boot)
    marg = _marginals(rater1, rater2, cats)
    min_share = min(marg.values()) if marg else 0.0
    return {
        "n": len(rater1),
        "categories": cats,
        "ac1_nominal": round(nominal_ac1, 4),
        "ac1_weighted_ordinal": None if weighted_ac1 is None else round(weighted_ac1, 4),
        "cohens_kappa": round(cohens_kappa_multi(rater1, rater2, cats), 4),
        "pabak": round(pabak_multi(rater1, rater2, cats), 4),
        "ac1_ci95": [round(lo, 4), round(hi, 4)],
        "ac1_floor": ac1_floor,
        "ci_lower_clears_floor": lo >= ac1_floor,
        "min_category_share": round(min_share, 4),
        # prevalence fallback: if labels are NOT extreme, kappa is co-primary
        "prevalence_extreme": min_share <= 0.20,
        "kappa_co_primary": min_share > 0.20,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 compute_kappa.py <human-annotations.json>")
        sys.exit(1)

    annotations_path = Path(sys.argv[1])
    with open(annotations_path) as f:
        human = json.load(f)

    meta = human.get("_meta", {})
    annotation_mode = normalize_annotation_mode(meta.get("annotation_mode"))
    human_review_complete = meta.get("human_review_complete")
    if annotation_mode == "ai_assisted_draft":
        print(
            "Refusing to compute Phase 0c on ai_assisted_draft. "
            "Review assisted-review-queue.csv and run finalize_assisted_annotations.py first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if annotation_mode == "ai_assisted_human_reviewed" and human_review_complete is not True:
        print(
            "Refusing to compute Phase 0c on AI-assisted annotations without completed human review.",
            file=sys.stderr,
        )
        sys.exit(1)

    llm_modal = load_llm_modal_votes()

    human_ratings = []
    llm_ratings = []
    unsure_count = 0
    disagreements = []

    for fid, criteria in human["fixtures"].items():
        for cid, rating in criteria.items():
            if rating["unsure"]:
                unsure_count += 1
                continue

            human_met = rating["met"]
            if human_met is None:
                unsure_count += 1
                continue
            llm_met = llm_modal.get((fid, cid))

            if llm_met is None:
                print(f"WARNING: No LLM rating for {fid}/{cid}, skipping")
                continue

            human_ratings.append(human_met)
            llm_ratings.append(llm_met)

            if human_met != llm_met:
                disagreements.append({
                    "fixture": fid,
                    "criterion": cid,
                    "category": rating["category"],
                    "human": human_met,
                    "llm": llm_met,
                    "notes": rating.get("notes"),
                })

    n = len(human_ratings)
    if n < 10:
        print(f"Only {n} rated criteria. Need >= 10.", file=sys.stderr)
        sys.exit(1)

    human_met_rate = sum(human_ratings) / n if n else 0
    llm_met_rate = sum(llm_ratings) / n if n else 0
    raw_agreement = sum(1 for h, l in zip(human_ratings, llm_ratings) if h == l) / n if n else 0

    kappa = cohens_kappa(human_ratings, llm_ratings)
    ac1 = gwets_ac1(human_ratings, llm_ratings)
    pabak_val = pabak(human_ratings, llm_ratings)

    print("=" * 60)
    print("Phase 0c: Human-LLM Agreement Results")
    print("=" * 60)
    print(f"Paired criteria:    {n}")
    print(f"Unsure (excluded):  {unsure_count}")
    print(f"Human met rate:     {human_met_rate:.1%}")
    print(f"LLM met rate:       {llm_met_rate:.1%}")
    print(f"Raw agreement:      {raw_agreement:.1%}")
    print(f"Disagreements:      {len(disagreements)}")
    print()
    print(f"Cohen's kappa:      {kappa:.3f}   <-- primary GO metric")
    print(f"Gwet's AC1:         {ac1:.3f}   (prevalence-robust diagnostic)")
    print(f"PABAK:              {pabak_val:.3f}")
    print()

    kappa_go = kappa >= KAPPA_THRESHOLD
    print(f"GO threshold:       >= {KAPPA_THRESHOLD}")
    print(f"Kappa verdict:      {'GO' if kappa_go else 'NO-GO'}")
    print()

    if human_met_rate > 0.8 or human_met_rate < 0.2:
        print(f"WARNING: Extreme human met prevalence ({human_met_rate:.1%}). "
              f"Kappa may underestimate agreement; compare AC1={ac1:.3f} and PABAK={pabak_val:.3f}.")
        print()

    if disagreements:
        print(f"Disagreement details ({len(disagreements)} items):")
        print("-" * 60)
        for d in sorted(disagreements, key=lambda x: (x["fixture"], x["criterion"])):
            human_str = "MET" if d["human"] else "NOT MET"
            llm_str = "MET" if d["llm"] else "NOT MET"
            notes_str = f" -- {d['notes']}" if d.get("notes") else ""
            print(f"  {d['fixture']}/{d['criterion']} ({d['category']}): human={human_str}, llm={llm_str}{notes_str}")

    phase0c_result = {
        "schema_version": "phase0c.v1",
        "annotation_mode": annotation_mode,
        "human_review_complete": human_review_complete,
        "review_queue_count": meta.get("human_reviewed_queue_count", meta.get("review_queue_count")),
        "source_annotations": str(annotations_path),
        "generated_by": "compute_kappa.py",
        "generated_at": datetime.now().isoformat(),
        "primary_metric": "cohens_kappa",
        "threshold": KAPPA_THRESHOLD,
        "threshold_label": f">= {KAPPA_THRESHOLD}",
        "verdict": "GO" if kappa_go else "NO-GO",
        "n_rated": n,
        "kappa": round(kappa, 4),
        "agreement_rate": round(raw_agreement, 4),
        "prevalence": round(human_met_rate, 4),
        "n_paired": n,
        "n_unsure": unsure_count,
        "human_met_rate": round(human_met_rate, 4),
        "llm_met_rate": round(llm_met_rate, 4),
        "raw_agreement": round(raw_agreement, 4),
        "cohens_kappa": round(kappa, 4),
        "gwets_ac1": round(ac1, 4),
        "pabak": round(pabak_val, 4),
        "n_disagreements": len(disagreements),
        "disagreements": disagreements,
        "go": kappa_go,
    }

    KAPPA_RESULT_PATH.write_text(json.dumps(phase0c_result, indent=2), encoding="utf-8")

    with open(REPORT_PATH) as f:
        report = json.load(f)

    report["phase_0c_human_kappa"] = phase0c_result
    report["go_no_go"]["checks"]["criterion_kappa"] = {
        "cohens_kappa": round(kappa, 4),
        "gwets_ac1": round(ac1, 4),
        "pabak": round(pabak_val, 4),
        "primary_metric": "cohens_kappa",
        "annotation_mode": annotation_mode,
        "human_review_complete": human_review_complete,
        "review_queue_count": phase0c_result["review_queue_count"],
        "source_annotations": str(annotations_path),
        "value": round(kappa, 4),
        "threshold": f">= {KAPPA_THRESHOLD}",
        "go": kappa_go,
    }

    all_go = all(
        c.get("go") is True
        for c in report["go_no_go"]["checks"].values()
    )
    report["go_no_go"]["full_go"] = all_go
    if all_go:
        report["go_no_go"]["note"] = "All gates passed — judge is reliable for SkillOpt experiments"
    else:
        failed = [k for k, c in report["go_no_go"]["checks"].items() if c.get("go") is not True]
        report["go_no_go"]["note"] = f"Failed gates: {', '.join(failed)}"

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nUpdated: {REPORT_PATH}")


if __name__ == "__main__":
    main()
