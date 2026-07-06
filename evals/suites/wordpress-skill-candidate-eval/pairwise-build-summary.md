# Pairwise Redesign — Build Summary & GATE 1 Record

Implements `plans/2026-06-16-wordpress-pairwise-eval-redesign-plan-v4.md`
(Steps 1–5). Pre-run; no generation or scored run executed.

## Artifacts built

| Artifact | Purpose |
|---|---|
| `evals/suites/wordpress-skill-candidate-eval/pairwise-prereg.md` | Frozen pre-registration (conditions, validity labels, AC1/preference gates, isolation, second rater) |
| `evals/harness/validity_gate.py` | Pure escalate-first validity gate (CR-2 fix) |
| `evals/harness/compute_kappa.py` | **Additive** multi-category AC1/κ/PABAK + ordinal weighting + bootstrap CI (CR-1 fix). Binary Phase-0c gate untouched |
| `evals/harness/pairwise_judge.py` | Blind A/B pairing, anonymization, parsing, win-rate/CI/tie-rate aggregation, BH multiplicity, judge-vs-judge reliability; thin CLI I/O wrapper |
| `evals/harness/isolation.py` | Scratch cwd + scratch HOME/XDG + `--strict-mcp-config` empty + env scrub + agent-as-content (M4); posture recorder |
| `evals/harness/run_pairwise_pilot.py` | Single entrypoint: injectable `orchestrate()` (generate→gate→two-judge pairwise→reliability+preference) + `main()` wiring real isolated generation + two CLI judges |
| `evals/harness/tests/` | E4 corpus + agreement + pairwise + isolation + orchestration tests; two-arm live smoke test; fixtures |

## Test results

`python3 -m pytest evals/harness/tests/ -q` → **35 passed, 1 skipped** (the
operator-only isolation smoke test, correctly skipped without `RUN_ISOLATION_SMOKE=1`).

## Isolation proof — first run was VACUOUS; re-run required (2026-06-17)

The two-arm smoke test first ran on the logged-in CLI and *appeared* to pass (Arm A
leaked, Arm B clean). But the live **pairwise pilot then crashed with zero valid
pairs**, which exposed the real cause: the isolation was scrubbing every
`CLAUDE_*`/`ANTHROPIC_*` env var **including the auth token**, so every isolated
generation returned "Not logged in." Arm B was therefore clean *vacuously* — nothing
generated — not because isolation worked.

**Fixes applied:** isolation now preserves auth credentials and seeds only
`~/.claude/.credentials.json` into the scratch HOME (no config files); the smoke
test now asserts the isolated run is **non-empty and authenticated** before the
sentinel check (so the vacuous pass is impossible); and the pilot fails fast with a
clear message on systemic auth failure instead of crashing in reliability.

**Action: re-run the smoke test** — with the auth-preserving isolation it should now
pass *non-vacuously* (Arm A leaks, Arm B authenticates AND is clean):
`RUN_ISOLATION_SMOKE=1 python3 -m pytest evals/harness/tests/test_isolation_smoke.py -s`

Coverage highlights:
- Validity gate: all 12 archived outputs match the frozen pre-reg labels (8 valid,
  4 review incl. both true refusals); 9 held-out adversarial fixtures (FN1–FN4, FP3,
  a–e) satisfy the invariant — no refusal auto-valid, no valid auto-discarded.
- Agreement: 3-way AC1 reduces to the binary tool at K=2 over 25 random vectors;
  hand-checked K=3 matrix reproduced; the wrong v3 `K/(K−1)` coefficient explicitly
  guarded against; estimators stay in [−1,1]; declared-K avoids divide-by-zero.
- Pairwise: half-invalid drop, deterministic+balanced A/B randomization, blind
  prompt leaks no condition names, clear-win passes, coin-flip and all-ties do not.

## GATE 1 (M5 — test-critic on the built design)

**Verdict: ACCEPT-WITH-RESERVATIONS** → satisfies `wordpress-skills/CLAUDE.md:38`
condition 3; the run is authorized. The critic ran the suite independently,
re-verified the K=2 reduction to ~1e-15, confirmed the gate invariant is enforced
by code structure (not fixtures), and confirmed the compute_kappa.py changes are
provably additive. Reservations (all disclosed, none run-blocking): live isolation
proof is necessary-not-sufficient; lexical detector ceiling; correlated Claude-family
judges (routed to the deferred human anchor). Two minor fixes from the review were
applied: the dormant smoke test now reports SKIPPED (not PASSED), and
`parse_preference` flags parse failures separately from substantive ties.

## Isolation vector — DIAGNOSED (pre-reg §6 now filled)

The v1 contamination vector is confirmed from the run metadata, not deferred. The
`zivtech_prototype` condition ran with **`cwd = the repo root`** plus `--agent`, so
`claude -p` discovered the repo's root `CLAUDE.md` + `.claude/` tree. Smoking gun: a
`zivtech_prototype` output names `run_wordpress_candidate_pilot.py` and
`score_with_claude_cli.py` — strings absent from the fixture and from every agent
prompt, while baselines/upstream (run in `/tmp`) leak nothing. `isolation.py` was
hardened to close it: generation now runs from a **scratch cwd** (never the repo)
and **injects the agent prompt as message content instead of `--agent`** (which
itself triggers `.claude/agents` discovery), on top of the scratch HOME/XDG +
`--strict-mcp-config` + env scrub. The smoke test plants both confirmed-vector
sentinels (`./CLAUDE.md` and `~/.claude/CLAUDE.md`) and asserts neither leaks.

## Pilot executed — directional internal result (2026-06-17)

Run `pairwise-pilot-20260617-061925` completed (3 runs × 4 fixtures × 4 conditions,
judges opus-4-6 + sonnet-4-6). **Preference gate PASSED** — the Zivtech prototype is
preferred over zero-shot (0.89, p=0.039), few-shot (~0.91, BH-sig), and raw upstream
(~0.91, BH-sig), reversing the v1 inversion. **Reliability gate NOT certified** —
inter-judge AC1 = 0.64, CI [0.50, 0.79] < 0.70 floor. Operator accepted the result as
**directional internal-only**; 27-fixture run + superiority claims stay blocked. Full
analysis: `pairwise-pilot-20260617-061925/RESULT-INTERPRETATION.md`; decision:
`.../INTERNAL-DECISION.md`.

## Judging v2 — rubric-anchored (judge improvement, 2026-06-17)

Root cause of the low agreement (AC1 0.64): the v1 judge prompt asked "pick the
better one" and — the real miss — the orchestrator **never passed the fixture's
domain signals to the judge**, so the two judges graded on gestalt. Judging v2
fixes both: `build_judge_prompt` now grades A and B against the **same explicit
rubric** (weighted criteria + `must_detect` items + expected APIs + pitfalls,
formatted by `rubric_criteria_block`), with a narrow tie definition and
criterion-by-criterion instructions. Shared concrete anchors are what lift
inter-judge agreement off vibe-judging. Because the AC1 point estimate (0.64) is
itself below the floor, this — not more sampling — is the lever that can clear 0.70.

This was a **new measurement**: the directional decision already recorded stands
on v1 judging; the v2 run was the certification attempt. The original
`pairwise-pilot-20260617-061925` run no longer has `checkpoint/gen/`, so do not
reuse the old documented `--gen-from pairwise-pilot-20260617-061925` command.
That shortcut was ruled out in `pairwise-resume-handoff.md`.

For judging-only follow-up runs, use a source run that actually contains
`checkpoint/gen/`, such as `pairwise-cert-1`, and rely on
`pairwise-summary.json` `generation_models.provenance_counts` to distinguish
reused generations from newly generated Codex/Claude fills:

```bash
python3 evals/harness/run_pairwise_pilot.py \
  --run-id pairwise-followup-YYYYMMDD-HHMMSS \
  --gen-from pairwise-cert-1 \
  --judge-1 claude-opus-4-6 \
  --judge-2 gpt-5.5
```

If AC1's CI lower bound now clears 0.70 → the result is certified; then Decision A
(human anchor) fires and the 27-fixture run unblocks. If it still misses, the honest
read is that the two Claude-family judges genuinely diverge on these calls and a
non-correlated (e.g. human or non-Claude) judge is needed — the directional
internal decision stands either way.

## How to run / re-run

1. ~~Fill the pre-reg §6 confirmed isolation vector~~ — **done**.
2. ~~Run the live isolation smoke test~~ — **done; PASSED 2026-06-17** (above).
3. Execute the pilot. The runner now prints **per-call progress**, **checkpoints
   every generation and judge call to disk**, and **resumes** — so a long run is
   observable and never lost. The full pass is ~190 sequential `claude -p` calls
   (~1.5–3 h); start with `--fast` for a ~24-call directional read (~10–15 min).

   ```bash
   # quick directional read first (runs=1, strong-vs-weak only)
   python3 evals/harness/run_pairwise_pilot.py --fast \
     --judge-1 claude-opus-4-6 --judge-2 claude-sonnet-4-6

   # full pilot (resumable: re-run with --resume + the same --run-id if interrupted)
   python3 evals/harness/run_pairwise_pilot.py \
     --judge-1 claude-opus-4-6 --judge-2 claude-sonnet-4-6 --run-id wp-pairwise-1
   #   ... if it dies at call 150, just re-run with --resume --run-id wp-pairwise-1
   ```

   Omit `--judge-2` (or set it equal to `--judge-1`) for repeated blinded passes =
   "single-judge self-agreement" per pre-reg §2. Writes
   `evals/results/wordpress-skill-candidate-eval/<run-id>/pairwise-summary.json`
   plus a `checkpoint/` dir. The run applies the validity gate (escalate-first),
   blind two-judge pairwise, and the reliability (AC1 CI-lower-bound ≥ 0.70) +
   preference (win-rate ≥ 0.60, CI excludes 0.5, tie-rate ≤ 0.40) gates. It **fails
   fast** with a clear message if generation systemically fails (e.g. auth broke).
   Result is internal-only; the human anchor (Decision A) fires only if AC1 clears.
