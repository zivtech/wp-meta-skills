# Handoff — Resume the WordPress Pairwise Eval Pilot

**Date:** 2026-06-18
**Status of this doc:** untracked, alongside the (deliberately uncommitted) pilot. Not committed.
**OUTCOME (2026-06-19): CLOSED — directional-internal FINAL.** Reliability fails under an independent (non-Claude) judge (cross-family AC1 0.66 < 0.70) and the preference gate doesn't replicate at n=12; zivtech is directionally top-tier but ≈ few-shot. Full decision: `evals/results/wordpress-skill-candidate-eval/pairwise-cert-2-xfamily/INTERNAL-DECISION-FINAL.md`. 27-fixture run + any external claim remain BLOCKED.
**Companion files:** `pairwise-prereg.md` (FROZEN — do not edit), `pairwise-build-summary.md` (what was built).

## Where it stands (one screen)

**Question:** does the Zivtech V1 WordPress skills prototype (`zivtech_prototype`) produce measurably better candidate outputs than the two baselines and the raw upstream `WordPress/agent-skills` candidate? (v1 *absolute* scoring failed — ceiling saturation + a refusal-driven −0.113 inversion — so it was redesigned to **blind pairwise** + an escalate-first validity gate + dual gates.)

**Built & verified (DONE):**
- 5 harness files complete: `validity_gate.py`, `pairwise_judge.py`, `isolation.py`, `run_pairwise_pilot.py`, `compute_kappa.py` (multi-category AC1/κ/PABAK added). All untracked.
- Tests: **35 passed, 1 skipped** (`test_isolation_smoke`, dormant). GATE 1 (test-critic) = ACCEPT-WITH-RESERVATIONS. Live isolation smoke PASSED non-vacuously 2026-06-17.
- Prereg frozen; 27 fixtures + 27 pairwise rubrics (1:1, in the `criteria`+`domain_signals` schema, quality-weighted).

**Pilot run `pairwise-pilot-20260617-061925` (4 fixtures × 4 conditions × 3 runs = 48 gens, 69 pairings):**
- ✅ **Preference gate PASSED.** `zivtech` vs `baseline-zero-shot` win-rate **0.889** (CI [0.667, 1.0], p=0.039); both baselines and raw upstream lose to `zivtech` (BH-significant). Raw upstream is the weakest condition.
- ❌ **Reliability gate FAILED.** Gwet's AC1 = **0.644**, 95% CI **[0.495, 0.785]** — CI lower bound below the **0.70** floor. (κ=0.519, PABAK=0.609.)
- **Operator decision (2026-06-17, INTERNAL-DECISION.md):** accept as **directional internal-only**; keep Zivtech V1 as primary; no benchmark/external claim; 27-fixture run stays blocked.

**Root cause of the AC1 miss (identified, fix coded, NOT re-run):** the v1 judge prompt passed **no rubric** to the judges — both graded on gestalt. **Judging v2** (rubric-anchored: `build_judge_prompt` now passes the per-fixture criteria block) is implemented in `pairwise_judge.py` and wired in `run_pairwise_pilot.py`, but the **certification re-run has not been executed.**

## THE next step: the certification re-run (judging v2)

> **UPDATE 2026-06-18 — Option 1 ruled out; proceeding with Option 2.** The original 48 gens exist nowhere (see Open verifications) and the v1-absolute `…-live/raw/` outputs are refusal-contaminated, so the cheap pure `--gen-from` re-judge is impossible. Proceeding with the full regen as run-id **`pairwise-cert-1`** (generation `claude-sonnet-4-6`; judges `claude-opus-4-6` + `claude-sonnet-4-6` — held identical to the pilot so the only intended change is the rubric-anchored judge v2). Caveat stands: fresh sample ⇒ confounds judge-improvement with sampling noise; valid as a *new* cert run, not a pure re-judge. Pre-launch checks (2026-06-18): all 5 path deps present (fixtures/rubrics/baselines, in-repo zivtech agents, `/tmp/wp-agent-skills-pilot-project` upstream skills), PyYAML 6.0.3, both model strings resolve (and a garbage model ID errors, confirming the CLI pins versions rather than coercing). **First launch failed (exit 1) on a fail-fast FALSE POSITIVE, not a real failure:** all 48 gens ran and cached fine, but the `r1/security-boundary-risk/baseline-zero-shot` output (a valid 6,278 B `wp_ajax_nopriv_` review) contains the literal phrase "not logged in", which the bare-substring auth-error check in `orchestrate()` mismatched. Fixed by length-gating that check (`run_pairwise_pilot.py` ~L88–99: empty always trips; the "not logged in"/"please run /login" phrases trip only on a <500 B stderr-sized output). Harness tests: 41 passed / 1 skipped. Relaunched with `--resume` (reuses the 48 cached gens, proceeds straight to judging) → log `pairwise-cert-1.resume.run.log`.
>
> **CERT-1 RESULT (2026-06-18, judging v2):** the fix is VALIDATED — inter-judge AC1 **0.644 → 0.804** (κ 0.519→0.655, PABAK 0.609→0.771); preference still PASSES (zivtech vs zero-shot **0.818**, 9–2–1). But the reliability gate FAILS on CI width: AC1 95% CI **[0.689, 0.912]** — lower bound 0.689 misses the 0.70 floor by ~0.011 (n=72; `prevalence_extreme`, ties ~2%). It's a width near-miss, not stuck agreement. Caveat: under rubric-anchored judging zivtech beats **baseline-few-shot only 7–5 (NS, p=0.77)** — its measurable edge is over zero-shot (9–2) and raw-upstream (10–2), not a strong few-shot prompt. 27-fixture stays blocked; internal-only.
>
> **DECISION (operator, 2026-06-19): branch (b) — non-Claude judge.** Both cert-1 judges were Claude-family, so AC1 0.80 could be shared-family correlation. Extended the harness: `judge_pair_via_codex` (pairwise_judge.py) + a dispatch in `run_pairwise_pilot.py` `judge_fn` routing any non-`claude*` model id to the local **`codex` CLI** (OpenAI, ChatGPT-auth, NO API key) run non-agentically (`--sandbox read-only --output-schema {winner,reasoning} --output-last-message --ephemeral --ignore-rules`). Smoke on 1 real pairing → clean schema JSON; model **gpt-5.5** (xhigh). Harness tests 41 passed / 1 skipped. Launched **`pairwise-cert-2-xfamily`** = `--gen-from pairwise-cert-1` (reuse the 48 gens), judges `claude-opus-4-6` vs `gpt-5.5` → measures **cross-family AC1**. If it holds high, the 0.80 is real reliability; if it drops, the both-Claude correlation is confirmed. → log `pairwise-cert-2-xfamily.run.log`.

Goal: does the rubric-anchored judge lift the AC1 **CI lower bound above 0.70**? The point estimate must actually move from 0.644 — a sharper rubric has to raise inter-judge agreement, not just tighten the interval.

⚠️ **The cheap `--gen-from` shortcut in `pairwise-build-summary.md` will NOT work as written.** It reads cached generations from `RESULTS_DIR/pairwise-pilot-20260617-061925/checkpoint/gen/` (`run_pairwise_pilot.py:274`), but that run dir now contains **only 3 files** (`pairwise-summary.json`, `RESULT-INTERPRETATION.md`, `INTERNAL-DECISION.md`) — **no `checkpoint/gen/`.** The original 48 generations are not where `--gen-from` expects them.

So, in order of preference:
1. **Recover the original generations, then re-judge only (cleanest science, ~20–40 min).** If you have the 48 generations backed up anywhere, restore them to `pairwise-pilot-20260617-061925/checkpoint/gen/` and run the documented command — it isolates the judge change (same outputs, new judge), which is exactly what a certification re-run should do:
   ```bash
   python3 evals/harness/run_pairwise_pilot.py \
     --run-id pairwise-cert-1 --gen-from pairwise-pilot-20260617-061925 \
     --judge-1 claude-opus-4-6 --judge-2 claude-sonnet-4-6
   ```
   (Possible source to inspect: the older `wordpress-candidate-pilot-20260616-live/run-*/raw/<condition>/` outputs exist — but they're from the v1 *absolute* pilot, likely not isolation-clean or key-compatible; verify provenance before trusting them.)
2. **Full re-run (regenerate + judge v2, ~1.5–3 h).** Drop `--gen-from`:
   ```bash
   python3 evals/harness/run_pairwise_pilot.py \
     --run-id pairwise-cert-1 \
     --judge-1 claude-opus-4-6 --judge-2 claude-sonnet-4-6
   ```
   Caveat: regeneration is non-deterministic, so this is a **fresh sample**, not a pure re-judge — it confounds "did the judge improve?" with sampling noise. Acceptable as a new cert run; just don't report it as isolating the judge change.

Either way: **local `claude -p` only** — the harness's `run_isolated_generation` preserves OAuth and introduces no `ANTHROPIC_API_KEY`. Keep it that way.

## Decision tree after the cert re-run
- **AC1 CI-lower ≥ 0.70 AND preference still passes** → both gates clear → **Decision A**: add the human validity anchor (lightweight spot-check via the annotation tool + `compute_kappa.py`) → then the **27-fixture full paired run** unblocks.
- **AC1 still fails** (point estimate stuck near 0.64) → either (a) accept the directional internal-only decision as **final** and close the pilot, or (b) break the judge-correlation limitation with a **non-correlated judge** (a human pass, or a non-Claude-family model). Both judges today are Claude-family — the known limitation the prereg routes to the human anchor.

## Guardrails (read before running anything)
- **Local `claude -p` only**; no API key.
- **`pairwise-prereg.md` is frozen** — do not edit the locked design (conditions, gates, thresholds). Record new results as new run dirs/docs, not by rewriting prior run history.
- The harness/results/prereg/plan files are **untracked in-flight work** — commit only when you decide to; don't `git add -A` (it would also sweep unrelated untracked files).
- **27-fixture run + any external/superiority claim stay BLOCKED** until preference + reliability + human anchor all clear (prereg).

## Open verifications (couldn't fully confirm from files)
- **Do the original 48 generations exist anywhere? — RESOLVED 2026-06-18: NO.** Searched repo (no `r{run}__{fixture}__{condition}.txt`, no `gen/`/`checkpoint/` dirs), `$HOME` incl. `~/Library`/CloudStorage/iCloud (only the repo run-dir — and it holds just its 3 summary docs), `~/.Trash`, `$TMPDIR`/`/tmp`/`/var/folders` (no `wp-iso-*`), and git (`log --all` on the gen path + `stash`) — never committed, nothing stashed. **Option 1 (pure `--gen-from` re-judge) is dead.** The one structural look-alike, `wordpress-candidate-pilot-20260616-live/run-*/raw/`, is the v1 *absolute* pilot and is **contaminated**: ≥2 `zivtech_prototype` outputs (673 B, 783 B vs a ~6 KB norm) are not candidate answers — the generator mistook the fixture for a *scoring* task ("paste the candidate and I'll score it"). That is the −0.113 refusal inversion; reusing it would re-poison the cert sample. ⇒ Option 2 (full regen + judge v2) is the only clean path.
- `test_isolation.py` pass status (presumably part of the 35 passing).
- Judge independence: `pairwise-summary.json` lists judges `[claude-opus-4-6, claude-sonnet-4-6]`; whether truly independent or correlated is the documented limitation.

## Where to start
1. Look for a backup of the `pairwise-pilot-20260617-061925` generations (determines re-run cost).
2. Run the cert re-run (option 1 if recoverable, else option 2).
3. `compute_kappa.py` the new judgments; check AC1 CI-lower vs 0.70 and that preference still passes.
4. Branch per the decision tree. Stop and report before unblocking the 27-fixture run.
