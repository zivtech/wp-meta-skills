#!/usr/bin/env python3
"""WordPress candidate PAIRWISE pilot — single entrypoint.

Wires the whole redesigned pipeline:
  generate (ISOLATED) -> validity gate -> blind two-judge pairwise -> reliability
  (3-way AC1/kappa/PABAK) + preference signal (win-rate/CI/tie-rate) gates.

Replaces the saturated absolute-scoring pilot. Internal-only: a cleared result
licenses continued internal measurement, never a superiority claim
(wordpress-skills/CLAUDE.md:34).

The orchestration core `orchestrate(...)` takes injectable `generate_fn`/`judge_fn`
so it is fully unit-tested with stubs (tests/test_pairwise_pilot.py). `main()`
wires the real isolated generation (isolation.py) and two local `claude -p` judges;
it requires a logged-in CLI and is run by the operator after the smoke test passes.
Design frozen in evals/suites/wordpress-skill-candidate-eval/pairwise-prereg.md.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path

from validity_gate import classify_output
from pairwise_judge import (
    make_pairings, build_judge_prompt, parse_preference, to_preference,
    aggregate_preferences, reliability_between_judges, benjamini_hochberg,
    judge_pair_via_cli, judge_pair_via_codex,
)
from compute_kappa import agreement_report_multi  # noqa: F401  (used via reliability_between_judges)

ROOT = Path(__file__).resolve().parent.parent.parent
SUITE = "wordpress-skill-candidate-eval"
SUITE_DIR = ROOT / "evals" / "suites" / SUITE
RESULTS_DIR = ROOT / "evals" / "results" / SUITE

PILOT_FIXTURES = ("security-boundary-risk", "block-development-risk",
                  "content-model-ambiguous", "performance-ops-clean")
CONDITIONS = ("baseline-zero-shot", "baseline-few-shot",
              "raw_upstream_candidate", "zivtech_prototype")
KNOWN_STRONG = "zivtech_prototype"
KNOWN_WEAK = "baseline-zero-shot"
ALL_CONTRASTS = [(a, b) for i, a in enumerate(CONDITIONS) for b in CONDITIONS[i + 1:]]

ZIVTECH_AGENTS = {
    "security-boundary-risk": "wordpress-security-critic",
    "block-development-risk": "wordpress-block-planner",
    "content-model-ambiguous": "wordpress-content-model-planner",
    "performance-ops-clean": "wordpress-performance-critic",
}
UPSTREAM_SKILLS = {
    "security-boundary-risk": "wp-plugin-development",
    "block-development-risk": "wp-block-development",
    "content-model-ambiguous": "wp-rest-api",
    "performance-ops-clean": "wp-performance",
}
DEFAULT_UPSTREAM_PROJECT = Path("/tmp/wp-agent-skills-pilot-project")
AC1_FLOOR = 0.70


def wordpress_agent_dir():  # pragma: no cover
    monorepo_dir = ROOT / "wordpress-skills" / ".claude" / "agents"
    if monorepo_dir.exists():
        return monorepo_dir
    return ROOT / ".claude" / "agents"


# --------------------------------------------------------------------------- #
# PURE orchestration core (injectable; unit-tested)
# --------------------------------------------------------------------------- #

def _noop_progress(phase, i, n, label):  # pragma: no cover
    pass


def orchestrate(*, fixtures, conditions, contrasts, known_strong, known_weak, runs,
                judges, generate_fn, judge_fn, fixture_text_fn,
                criteria_fn=None, classify_fn=classify_output, seed="pilot",
                progress_fn=None):
    """Run the pipeline. `generate_fn(fixture, condition, run)->text`,
    `judge_fn(judge_model, prompt)->raw`. Optional `progress_fn(phase, i, n, label)`
    is called per generation and per judge call. Returns the internal-only summary."""
    progress = progress_fn or _noop_progress
    outputs, validity, review_queue = {}, {}, []
    empty_or_error = []
    total_gen = runs * len(fixtures) * len(conditions)
    gi = 0
    for run_index in range(1, runs + 1):
        for fixture in fixtures:
            for cond in conditions:
                gi += 1
                progress("generate", gi, total_gen, f"{fixture}/{cond} run{run_index}")
                text = generate_fn(fixture, cond, run_index)
                # An auth failure from `claude -p` is a SHORT stderr-like message
                # ("Not logged in" / "Please run /login"); a real candidate output is
                # long. Gate the phrase match on length so a legitimate long answer
                # that merely discusses being "not logged in" (e.g. a wp_ajax_nopriv_
                # security review) does not trip the fail-fast. Empty always trips.
                low = (text or "").lower()
                short = len((text or "").strip()) < 500
                if (not text or not text.strip()
                        or (short and ("not logged in" in low
                                       or "please run /login" in low))):
                    empty_or_error.append(f"run{run_index}/{fixture}/{cond}")
                v = classify_fn(text)
                outputs[(run_index, fixture, cond)] = text
                validity[(run_index, fixture, cond)] = v
                if v.label != "valid":
                    review_queue.append({"run": run_index, "fixture": fixture,
                                         "condition": cond, "class": v.cls, "reason": v.reason})

    # Fail fast on a systemic generation failure (e.g. CLI auth broken under
    # isolation) rather than crashing later in reliability with an opaque error.
    valid_total = sum(1 for v in validity.values() if v.label == "valid")
    if empty_or_error:
        raise RuntimeError(
            f"{len(empty_or_error)}/{total_gen} generations were empty or an auth error "
            f"(e.g. 'Not logged in') — generation likely failed under isolation. "
            f"Check CLI auth / credential seeding. First few: {empty_or_error[:5]}")
    if valid_total == 0:
        raise RuntimeError(
            f"0/{total_gen} generations passed the validity gate (all quarantined to "
            f"review). No pairwise comparison is possible. See review_queue.")

    # Build ALL pairings first so the judge total is known for progress reporting.
    plan = []  # (pairing, prompt)
    dropped = []
    for run_index in range(1, runs + 1):
        for fixture in fixtures:
            cond_outputs = {c: outputs[(run_index, fixture, c)] for c in conditions}
            labels = {c: validity[(run_index, fixture, c)].label for c in conditions}
            pairings, drop = make_pairings(f"{fixture}#r{run_index}", cond_outputs,
                                           labels, contrasts, seed)
            dropped.extend(drop)
            ftext = fixture_text_fn(fixture)
            crit = criteria_fn(fixture) if criteria_fn else ""
            for p in pairings:
                plan.append((p, build_judge_prompt(ftext, p.text_a, p.text_b, crit)))

    prefs = {j: [] for j in judges}
    total_judge = len(plan) * len(judges)
    ji = 0
    for p, prompt in plan:
        for j in judges:
            ji += 1
            progress("judge", ji, total_judge, f"{p.fixture_id} {p.cond_a}|{p.cond_b} [{j}]")
            winner, reasoning, ok = parse_preference(judge_fn(j, prompt))
            pref = to_preference(p, winner, reasoning, j)
            pref.parse_ok = ok  # attribute tag for parse-failure accounting
            prefs[j].append(pref)

    primary = judges[0]
    preference = aggregate_preferences(prefs[primary], known_strong, known_weak)
    have_pairs = len(prefs[primary]) > 0
    reliability = (reliability_between_judges(prefs[judges[0]], prefs[judges[1]])
                   if (len(judges) >= 2 and have_pairs) else None)
    if not have_pairs:
        raise RuntimeError(
            "0 pairwise comparisons survived the half-invalid drop rule — every "
            "condition pair had a quarantined side. Inspect review_queue / dropped_pairs.")

    # per-contrast descriptive preference (no single contrast is a GO; multiplicity)
    per_contrast, pvals = [], []
    for cx, cy in contrasts:
        agg = aggregate_preferences(prefs[primary], cx, cy)
        per_contrast.append(agg)
        pvals.append(agg["binomial_p"])
    bh = benjamini_hochberg(pvals) if pvals else []
    for agg, passed in zip(per_contrast, bh):
        agg["bh_significant"] = bool(passed)

    parse_failures = sum(1 for j in judges for p in prefs[j] if not getattr(p, "parse_ok", True))

    reliability_passes = bool(reliability and reliability["ci_lower_clears_floor"])
    summary = {
        "suite": SUITE,
        "internal_only": True,
        "firewall": "A cleared result licenses continued internal measurement only, "
                    "not a superiority claim (wordpress-skills/CLAUDE.md:34).",
        "runs": runs, "fixtures": list(fixtures), "conditions": list(conditions),
        "judges": list(judges),
        "review_queue": review_queue,
        "review_queue_count": len(review_queue),
        "dropped_pairs": [{"contrast": list(c), "reason": r} for c, r in dropped],
        "preference_primary_judge": preference,
        "per_contrast_preference": per_contrast,
        "reliability": reliability,
        "ac1_floor": AC1_FLOOR,
        "reliability_passes": reliability_passes,
        "judge_parse_failures": parse_failures,
        "both_gates_clear": bool(preference.get("preference_passes") and reliability_passes),
        "human_anchor_next": reliability_passes,  # Decision A: only if AC1 clears
        "twentyseven_fixture_unblock": bool(preference.get("preference_passes") and reliability_passes),
    }
    return summary


# --------------------------------------------------------------------------- #
# Real wiring (operator-run; needs logged-in `claude` CLI)
# --------------------------------------------------------------------------- #

def fixture_text(fixture_id):  # pragma: no cover
    return (SUITE_DIR / "fixtures" / f"{fixture_id}.md").read_text(encoding="utf-8")


def rubric_criteria_block(fixture_id):  # pragma: no cover
    """Format the fixture's rubric (weighted criteria + domain signals) into the
    shared block both judges grade against. Wiring this is the judging-v2 upgrade
    that lifts inter-judge agreement off vague 'which is better' calls."""
    import yaml
    r = yaml.safe_load((SUITE_DIR / "rubrics" / f"{fixture_id}.rubric.yaml").read_text(encoding="utf-8")) or {}
    lines = ["Weighted criteria (higher weight = more decisive):"]
    for c in r.get("criteria", []):
        lines.append(f"- [weight {c.get('weight', 1)}] {c['id']}: {c['description']}")
    ds = r.get("domain_signals", {}) or {}
    if ds.get("must_detect"):
        lines.append("\nRequired issues a strong response MUST catch (decisive):")
        lines += [f"- {x}" for x in ds["must_detect"]]
    if ds.get("expected_wordpress_apis"):
        lines.append("\nWordPress-native APIs a strong response tends to use:")
        lines += [f"- {x}" for x in ds["expected_wordpress_apis"]]
    if ds.get("must_not_penalize_or_do"):
        lines.append("\nPitfalls — a response doing these is weaker; penalizing these is itself wrong:")
        lines += [f"- {x}" for x in ds["must_not_penalize_or_do"]]
    return "\n".join(lines)


def build_condition_prompt(condition, fixture_id, ftext, upstream_project):  # pragma: no cover
    """Returns (prompt, agent_prompt_text). agent_prompt_text is injected as content
    (never via --agent), so no repo .claude discovery — the confirmed v1 vector."""
    if condition.startswith("baseline-"):
        base = (SUITE_DIR / "baselines" / f"{condition}.md").read_text(encoding="utf-8")
        return f"{base.strip()}\n\n---\n\nUse this fixture:\n\n{ftext.strip()}", None
    if condition == "raw_upstream_candidate":
        skill = UPSTREAM_SKILLS[fixture_id]
        skill_md = (upstream_project / ".claude" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        return f"## Fixture\n\n{ftext.strip()}", skill_md
    if condition == "zivtech_prototype":
        agent = ZIVTECH_AGENTS[fixture_id]
        agent_md = (wordpress_agent_dir() / f"{agent}.md").read_text(encoding="utf-8")
        return ftext, agent_md
    raise ValueError(condition)


def _hash(*parts):  # pragma: no cover
    import hashlib
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()[:24]


def load_source_generation_models(run_id):  # pragma: no cover
    """Return recorded generation model provenance from a source run if present."""
    for name in ("pairwise-summary.json", "summary.json", "pilot-summary.json"):
        path = RESULTS_DIR / run_id / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        models = payload.get("generation_models")
        if models:
            return models
    return None


def build_generation_models_summary(args, provenance_counts):
    """Describe generation provenance without relabeling reused generations."""
    generated = {
        "baseline_provider": "codex",
        "baseline_model_policy": "newest-chatgpt-level-at-run-time",
        "baseline_model": args.baseline_model,
        "baseline_effort": args.baseline_effort,
        "candidate_provider": "claude",
        "candidate_model": args.generation_model,
    }
    if not args.gen_from:
        return {
            "generation_source": "generated-or-current-run-cache",
            "generated_or_cached_in_run_models": generated,
            "provenance_counts": provenance_counts,
        }
    return {
        "generation_source": "reused-checkpoint-with-current-run-fill",
        "reused_from": args.gen_from,
        "source_generation_models": load_source_generation_models(args.gen_from),
        "missing_generation_fill_models": generated,
        "provenance_counts": provenance_counts,
        "warning": (
            "Do not infer Codex/ChatGPT baseline provenance for reused generations "
            "unless source_generation_models records it."
        ),
    }


def run_codex_baseline_generation(prompt, *, model, effort, timeout_sec):  # pragma: no cover
    """Run a prompt-only ChatGPT-level baseline through the shared Codex lane."""
    import invoke
    out, err, rc, _dt = invoke._run_codex(
        prompt,
        timeout_sec=timeout_sec,
        max_retries=2,
        model=model,
        effort=effort,
    )
    if rc != 0 and not out.strip():
        return err
    return out


def main():  # pragma: no cover
    import sys
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--generation-model", default="claude-sonnet-4-6",
                   help="Claude model for skill/upstream candidate lanes. Baseline lanes use --baseline-model.")
    p.add_argument("--baseline-model", default="gpt-5.5",
                   help="Codex/ChatGPT-level model for baseline-zero-shot and baseline-few-shot lanes.")
    p.add_argument("--baseline-effort", default="medium",
                   help="Codex reasoning effort for baseline lanes.")
    p.add_argument("--judge-1", default="claude-opus-4-6")
    p.add_argument("--judge-2", default="claude-opus-4-6",
                   help="Second judge model. If equal to judge-1 this is repeated "
                        "blinded passes (single-judge self-agreement) per pre-reg §2.")
    p.add_argument("--upstream-project", type=Path, default=DEFAULT_UPSTREAM_PROJECT)
    p.add_argument("--run-id", default=f"pairwise-pilot-{datetime.now():%Y%m%d-%H%M%S}")
    p.add_argument("--timeout-sec", type=int, default=900)
    p.add_argument("--resume", action="store_true",
                   help="Reuse the --run-id checkpoint dir; skip already-completed "
                        "generations and judge calls.")
    p.add_argument("--fast", action="store_true",
                   help="Quick directional read: runs=1 and only the known-strong vs "
                        "known-weak contrast (~24 calls instead of ~190).")
    p.add_argument("--gen-from",
                   help="Reuse generations from another run-id's checkpoint (read-only) "
                        "while writing a fresh run. Use for a judging-only re-run (e.g. "
                        "the sharpened-rubric certification attempt) without regenerating.")
    args = p.parse_args()

    from isolation import run_isolated_generation

    runs = 1 if args.fast else args.runs
    contrasts = [(KNOWN_WEAK, KNOWN_STRONG)] if args.fast else ALL_CONTRASTS

    out_dir = RESULTS_DIR / args.run_id
    ckpt = out_dir / "checkpoint"
    (ckpt / "gen").mkdir(parents=True, exist_ok=True)
    (ckpt / "judge").mkdir(parents=True, exist_ok=True)
    gen_from = (RESULTS_DIR / args.gen_from / "checkpoint" / "gen") if args.gen_from else None

    def progress(phase, i, n, label):
        print(f"[{phase} {i}/{n}] {label}", flush=True)

    provenance_counts = {
        "current_run_cache": 0,
        "reused_from_source": 0,
        "generated_codex_baseline": 0,
        "generated_claude_candidate": 0,
    }

    def generate_fn(fixture_id, condition, run_index):
        key = f"r{run_index}__{fixture_id}__{condition}.txt"
        cache = ckpt / "gen" / key
        if cache.exists():
            provenance_counts["current_run_cache"] += 1
            print(f"    (cached) {key}", flush=True)
            return cache.read_text(encoding="utf-8")
        if gen_from is not None and (gen_from / key).exists():
            text = (gen_from / key).read_text(encoding="utf-8")
            cache.write_text(text, encoding="utf-8")  # copy into this run for provenance
            provenance_counts["reused_from_source"] += 1
            print(f"    (reused from {args.gen_from}) {key}", flush=True)
            return text
        ftext = fixture_text(fixture_id)
        prompt, agent = build_condition_prompt(condition, fixture_id, ftext, args.upstream_project)
        if condition.startswith("baseline-"):
            out = run_codex_baseline_generation(
                prompt,
                model=args.baseline_model,
                effort=args.baseline_effort,
                timeout_sec=args.timeout_sec,
            )
            provenance_counts["generated_codex_baseline"] += 1
            cache.write_text(out, encoding="utf-8")
            return out
        with tempfile.TemporaryDirectory(prefix="wp-iso-") as base:
            out, _err, _rc, _posture = run_isolated_generation(
                prompt, model=args.generation_model, base=Path(base),
                agent_prompt_text=agent, timeout_sec=args.timeout_sec)
        provenance_counts["generated_claude_candidate"] += 1
        cache.write_text(out, encoding="utf-8")  # checkpoint
        return out

    judges = [args.judge_1] if args.judge_1 == args.judge_2 else [args.judge_1, args.judge_2]
    repeated_pass = len(judges) == 1
    if repeated_pass:  # repeated-pass mode: same model twice, labelled distinctly
        judges = [f"{args.judge_1}#pass1", f"{args.judge_1}#pass2"]

    def judge_fn(judge_model, prompt):
        real_model = args.judge_1 if repeated_pass else judge_model
        cache = ckpt / "judge" / f"{_hash(judge_model, prompt)}.txt"
        if cache.exists():
            return cache.read_text(encoding="utf-8")
        # Claude judges go through `claude -p`; any non-claude model id (e.g. a
        # gpt-* codex judge) routes to the codex CLI — the pre-reg branch-(b)
        # cross-family judge for breaking the both-Claude correlation limitation.
        judge_call = judge_pair_via_cli if real_model.startswith("claude") else judge_pair_via_codex
        raw = judge_call(real_model, prompt, timeout_sec=args.timeout_sec)
        cache.write_text(raw, encoding="utf-8")  # checkpoint
        return raw

    if not args.resume:
        # fresh run-id dirs are already empty; nothing to clear
        pass

    summary = orchestrate(
        fixtures=PILOT_FIXTURES, conditions=CONDITIONS, contrasts=contrasts,
        known_strong=KNOWN_STRONG, known_weak=KNOWN_WEAK, runs=runs,
        judges=judges, generate_fn=generate_fn, judge_fn=judge_fn,
        fixture_text_fn=fixture_text, criteria_fn=rubric_criteria_block,
        seed=args.run_id, progress_fn=progress)
    summary["mode"] = "fast" if args.fast else "full"
    summary["judging"] = "v2-rubric-anchored"
    summary["run_id"] = args.run_id
    summary["generation_models"] = build_generation_models_summary(args, provenance_counts)
    if args.gen_from:
        summary["generations_reused_from"] = args.gen_from

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pairwise-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("both_gates_clear", "reliability_passes", "review_queue_count",
                       "twentyseven_fixture_unblock")}, indent=2))
    print(f"\nWrote {out_dir/'pairwise-summary.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
