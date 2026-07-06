# GEPA Executor Persona-Optimization Spike (2026-06-22/23)

Follow-up that executes the #1 recommendation of `skill-improvement-research-2026-06-22.md`:
point a reflective prompt optimizer (GEPA) at the executor's deterministic gate and ask the
question four prior eval rounds left open — **does a machine-optimized persona beat the
hand-written one where the persona did not?**

## Bottom Line

**No held-out gain (Δ = 0.0).** GEPA, given only the gate's pass/fail and its machine-readable
failure text, **autonomously closed the training fixture's gate failure** (abilities `0.93 → 1.0`,
reproduced twice) — proving the loop works with no human reading the oracle. But on a **held-out
fixture the optimizer never saw, the best GEPA persona tied the seed** (`best_idx = 0`, smoke
`0.93 → 0.93`; one candidate even regressed to `0.86`).

The reason is the interesting part: GEPA did **not** overfit a narrow hack. Its reflection produced
a **genuinely general distribution-metadata + WPCS policy** — the same edits a careful human prompt
engineer would make (mandatory GPL `License`/`License URI`, no-placeholder rules, `Tested up to`,
ABSPATH guards, function prefixing, a dedicated metadata phase). **A good, general persona still did
not beat the seed on held-out gate-pass**, because the holdout's residual failures are *different*
concrete artifact defects that a prose policy can raise the base rate against but cannot
deterministically guarantee. The deterministic **repair loop remains the only lever** that closes a
novel artifact's specific defect. This is the **5th converging negative** that persona tuning is not
the lever — and the first on a *machine-optimized* persona, not a hand-written one. Internal-only; not
a superiority claim.

## Question

`skill-improvement-research-2026-06-22.md` ranked GEPA as the lowest-lift untried method and noted the
repo had already built the metric (the executor certifier) but never pointed an optimizer at it. The
spike tests the unasked follow-up: machine-optimize the persona against the gate and measure held-out
gate-pass vs the seed persona, holding the generation model fixed.

## Design

- **Optimizer:** `gepa==0.1.1` `optimize_anything`. Candidate = the `wordpress-plugin-executor`
  persona (system prompt, seed = `.claude/agents/wordpress-plugin-executor.md`, 8.5 KB).
- **Harness:** `evals/harness/run_gepa_executor_optimization.py`.
  - **Evaluator:** `persona + task-spec fixture` → packet, via isolated `codex exec --model gpt-5.5`
    (medium); certify through the proven `run_executor_repair_loop.make_certify` (static contract →
    materialize → runtime: wp-env + WPCS + Plugin Check + WP activation). Returns a graded score plus
    the gate's failure text as GEPA Actionable Side Information.
  - **Score** (graded, so reflection has a gradient): full pass `1.0`; runtime reached `0.30 + 0.70·(k/n)`
    (10/11 → ~0.93); static-only progress `0.30·(k/n)`.
  - **Reflection LM:** the same `codex exec --model gpt-5.5` lane wrapped as a callable (codex is not a
    litellm provider). Generation model is held **fixed** to the baseline lane's model, so
    "optimized vs seed" is a clean did-optimization-help comparison.
- **Reward-hacking guardrail (by construction):** codex runs `--sandbox read-only --ephemeral` in a
  fresh temp cwd and is told not to use tools, so the generator cannot touch the certifier or repo.
  ≥1 fixture is held out in split mode.
- **Fixtures:** only two task-spec fixtures exist (`abilities-ai-surface-v1` = hard,
  `smoke-wordpress-v1` = easy); the other "examples" are gold *packets* (outputs), not fixtures
  (inputs), so they cannot seed generation. Train on abilities, hold out smoke.

## Results

### Seed baseline (pre-flight, abilities, runtime profile, N=5)

| reps | pass | score | failing gate |
|---|---|---|---|
| 5 | **0/5** | 0.93 each | `plugin_check / plugin_header_no_license` (missing GPL `License:` header) |

Consistent, systematic zero-shot failure on one nameable gate — stable signal, single-eval scoring
sufficient. (One earlier ad-hoc generation passed 10/10; generation is stochastic but the License gap
dominates.)

### GEPA optimization

| Run | profile | budget | train (abilities) | held-out (smoke) | best |
|---|---|---|---|---|---|
| plumbing (single-task) | runtime | 4 | seed 0.93 → **1.0** @ iter 2 | — (no holdout) | candidate 1 |
| **split** | runtime | 16 (22 metric calls, 4 candidates) | mutated personas reached **1.0** | seed 0.93, candidates `[0.93, 0.93, 0.86]` | **candidate 0 (seed), 0.93** |

- **Train:** GEPA reliably finds a persona that passes the abilities gate `1.0` (reproduced in both runs).
- **Held-out:** **no candidate beat the seed** (`best_idx = 0`); the third candidate regressed to `0.86`.
  **Δ_holdout = 0.0.**

### Why — the held-out fixture fails differently

| fixture | seed failing gate(s) |
|---|---|
| **abilities** (train) | `plugin_check / plugin_header_no_license` — missing GPL License header |
| **smoke** (holdout) | `phpcs_wpcs` (a WPCS error) **+** `plugin_check / plugin_header_nonexistent_domain_path` (Domain Path → non-existent `languages/` folder) |

The training and held-out fixtures fail on **different concrete defects**. GEPA's persona fixes the
abilities defect cleanly; smoke's defects are untouched by it.

### What GEPA actually learned (candidate diff vs seed)

Not a narrow hack — a **general policy**. Reflection added, among other edits:
- a `<Distribution_Metadata_Requirements>` block: concrete `License: GPL-2.0-or-later`,
  `License URI`, `Tested up to`, `Requires PHP`, text domain, and *"omit Plugin URI rather than
  invent a placeholder"* (directly targeting the `example.com` nit);
- a dedicated **Phase 5 — distribution metadata pass**;
- hard gates: *"Missing license metadata is a blocking failure"*, *"must not contain `example.com`,
  `TODO`, `TBD`, `x.x`, or blank compatibility fields"*;
- WPCS hardening: `defined( 'ABSPATH' ) || exit;`, function/hook prefixing;
- a failure-mode watchlist naming missing `License`/`License URI`, placeholder metadata, missing
  `Tested up to`, mismatched text domains.

This is exactly what a human prompt engineer would write — and it still moved the held-out gate by
**zero**. A prose policy raises the chance of conformant output; it does not *guarantee* a gate-clean
artifact on a novel input. (The policy's `Domain Path: /languages` instruction may even perpetuate
smoke's Domain-Path nit when no `languages/` folder is emitted.)

## Conclusion

- **Machine-optimization did not beat the hand-written persona on held-out gate-pass.** It matched it.
- **The method works mechanically** (auto-discovers and bakes in the training-fixture fix from gate
  feedback alone) but does **not** yield a persona that generalizes gate-pass to an unseen fixture.
- **The lever is the deterministic repair loop**, which reads each artifact's actual failure and fixes
  *that* defect — something no static persona edit, hand- or machine-authored, can anticipate across
  fixtures. This sharpens the prior thesis: it is not that the optimizer failed to find a good prompt;
  it found a good prompt, and **a good prompt still isn't enough**.
- 5th converging result (after pairwise, fast + adversarial answer-key, gate-pass) that persona tuning
  is not the lever — now extended to machine-optimized personas.

## Negative Space / Caveats

- **N = 1 training fixture.** GEPA saw one failure mode. It nonetheless produced a *general* policy, so
  this is weaker than a naive overfit — but a richer, diverse-failure trainset (the deferred
  fixture-authoring path) might let GEPA target Domain-Path/WPCS specifically. The deeper ceiling
  (prose ≠ deterministic guarantee) would likely persist; that is a hypothesis, not established here.
- **Held-out scores are single generations per candidate** (abilities seed was N=5 and stable; smoke
  per-candidate was N=1). The `0.93` ties are suggestive, not variance-controlled.
- **Gate = shippability, not deep behavior.** WPCS/Plugin Check/activation, not ability-execution.
- **Does not claim the persona is worse** — only no measurable held-out edge from optimization.

## Reproduce

```
python3 evals/harness/run_gepa_executor_optimization.py --mode split --profile runtime \
  --budget 16 --train-fixture abilities-ai-surface-v1 --holdout-fixture smoke-wordpress-v1 \
  --run-dir <out>
# pre-flight seed pass-rate, plumbing, and dry-run modes also supported (see module docstring).
```

Requires `pip install gepa`, Docker (wp-env), and the runtime toolchain the gate-pass experiment used.
GEPA generation/reflection both run through the local `codex` CLI (gpt-5.5); no API key required.
