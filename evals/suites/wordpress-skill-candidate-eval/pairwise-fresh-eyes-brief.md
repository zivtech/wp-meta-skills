# WordPress Pairwise Eval — Fresh-Eyes Improvement Brief

**Date:** 2026-06-19 · **Eval status:** CLOSED, directional-internal FINAL (`evals/results/wordpress-skill-candidate-eval/pairwise-cert-2-xfamily/INTERNAL-DECISION-FINAL.md`).
**Purpose:** hand the problem to a fresh context. The eval reached a defensible *null-ish* verdict; the open question is whether a better instrument — **or a better skill** — could reach a stronger one, or whether the verdict is simply correct. **Challenge the framing; don't just optimize the existing design.**

## What was being measured
Does the Zivtech WordPress V1 skills prototype produce measurably better candidate outputs than (a) zero-shot, (b) few-shot, (c) raw upstream `WordPress/agent-skills`? Method: blind pairwise preference, LLM judges, 4 fixtures × 4 conditions × 3 runs (**n=12 pairs/contrast**), dual gates — preference (win-rate ≥ 0.60 AND CI excludes ½) **and** reliability (inter-judge Gwet's AC1 CI-lower ≥ 0.70).

## Where it actually landed (the honest verdict)
- **Direction is robust:** zivtech ranks top-tier under every judge and run (ahead of zero-shot & raw-upstream).
- **But nothing certifies:**
  - **Reliability is the binding constraint.** Same-family AC1 0.80 → cross-family (opus vs gpt-5.5) **0.66**. ~0.14 was Claude-family correlation. The 0.70 floor is not met by an independent judge.
  - **Preference is underpowered at n=12.** It passed in two runs and *failed in a third on the same generations* — it flips on judge sampling noise.
  - **zivtech ≈ strong few-shot** — a near-tie replicated across both runs and both judge families.

## Three problems a fresh look should attack
1. **Judge reliability (instrument).** A/B/tie agreement between LLM judges is only moderate once you leave one model family, and the near-empty "tie" cell (`prevalence_extreme`, ~2%) destabilizes AC1's CI. Is AC1-on-3-categories the right reliability target at all? Would a **human anchor**, a **diverse 3–5-judge panel with consensus**, a **sharper rubric**, or a **continuous quality margin** (instead of discrete A/B/tie) get reliable separation?
2. **Statistical power (design).** n=12/contrast can't support a stable gate. The 27-fixture run (~27/contrast) would help but is gated on reliability — a chicken-and-egg. Should reliability be established on a subset first, then power scaled? Is the dual-gate dependency (reliability AND preference) the right structure?
3. **Construct + the skill itself (the uncomfortable one).** The replicated zivtech ≈ few-shot result may simply be **true**: V1 may not add measurable value over a good few-shot prompt. Two divergent reads — (a) the eval is too blunt to see a real delta, or (b) the delta isn't there and the **skill** should be improved (what does V1 encode that a few-shot prompt doesn't, and is it showing up in outputs?). Weigh both; don't assume (a).

## Bigger questions (challenge the approach)
- Is blind LLM-judged pairwise on **synthetic fixtures** the right instrument for "does this skill help"? Alternatives: **outcome-based** eval (execute the produced WordPress code — does it run, pass security/lint/unit tests?), **expert-human** eval, or task-completion metrics. An objective oracle would sidestep the judge-reliability problem entirely.
- **What decision does this eval serve?** If "ship V1 internally," that's already supported directionally. If "claim V1 beats baselines," the current evidence won't carry it. Match rigor to stakes.

## What NOT to do
- Don't re-run the same n=12 design hoping for a pass — that's Goodharting the gate, not evidence.
- Don't treat same-family judge AC1 as reliability — it's inflated (~0.14 here).
- Don't edit the frozen `pairwise-prereg.md` or rewrite prior run history. New designs = new prereg + new run dirs.

## Pointers
- Verdict + full arc: `evals/results/wordpress-skill-candidate-eval/pairwise-cert-2-xfamily/INTERNAL-DECISION-FINAL.md`
- Cross-family numbers: `…/pairwise-cert-2-xfamily/RESULT-INTERPRETATION.md`
- Frozen design: `pairwise-prereg.md`; build notes: `pairwise-build-summary.md`; run-resume context: `pairwise-resume-handoff.md`
- Harness: `evals/harness/{run_pairwise_pilot,pairwise_judge,validity_gate,isolation,compute_kappa}.py` (+ `tests/`)
- **Reusable:** `judge_pair_via_codex` runs a non-Claude judge via local `codex exec` (non-agentic, read-only sandbox, schema-locked output) — generalizes to any reliability study needing a non-correlated judge.
- All generations for cert-1/cert-2 are committed under each run's `checkpoint/gen/` — re-judging is cheap via `--gen-from`; do not repeat the cert-1 "generations were deleted" loss.
