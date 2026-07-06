# Pre-Registration — WordPress Candidate Pairwise Pilot

Status: **frozen design, committed before any scored pairwise run.** This file is
a *norm*, not a tamper-proof control (an admin can edit it; `git` history makes
edits visible). It exists so post-hoc rationalization is auditable.

Source plan: `plans/2026-06-16-wordpress-pairwise-eval-redesign-plan-v4.md`.
Governing boundary: `wordpress-skills/CLAUDE.md:34-38`.

---

## 1. Purpose & internal-only firewall

Decide, for internal adopt/adapt routing only, whether the Zivtech V1 prototype
produces better WordPress candidate outputs than fair baselines / upstream — under
a discrimination instrument that the v1 absolute-scoring pilot failed (ceiling
saturation + refusal contamination → −0.113 inversion).

**Firewall:** no result here — pilot or 27-fixture — is evidence that "V1
outperforms upstream or baseline" in the sense `CLAUDE.md:34` forbids. A cleared
reliability gate licenses *continued internal measurement*, not a comparative
public claim. AC1 measures judge agreement, not correctness.

---

## 2. Conditions & raters

Conditions (4): `baseline-zero-shot`, `baseline-few-shot`, `raw_upstream_candidate`,
`zivtech_prototype`. Known-weak = `baseline-zero-shot`; known-strong (hypothesized)
= `zivtech_prototype`.

Pilot fixtures (4): `security-boundary-risk`, `block-development-risk`,
`content-model-ambiguous`, `performance-ops-clean`. Runs per condition: 3.

**Raters (two judges — the AC1 second-rater decision, M-B).** Judge-1 =
`claude-opus-4-6`. Judge-2 = a *second independent judge model* run as a separate
blinded pass (NOT the generator — the generator rates nothing). Both are
Claude-family; their correlation is a known limitation (A7) that AC1 cannot
detect and that the deferred human anchor (§7) exists to address. If a distinct
second model is unavailable, fall back to **repeated blinded passes** of Judge-1
(temperature 0 still has run-to-run variance) to estimate self-agreement, and
label the reliability figure "single-judge self-agreement" rather than
"inter-judge."

---

## 3. Validity gate (frozen) — escalate-first

Gate is a pure function `classify_output(text) -> {label, class, reason,
scorable_chars}` (`evals/harness/validity_gate.py`). No LLM call.

- **Refusal-intent** is matched over the **whole text** (not a leading window)
  against the frozen pattern set in `validity_gate.REFUSAL_PATTERNS`.
- **Scorable body** requires *structure*: a fenced code block, a table, or a
  level-2/3 heading. **Length alone is never a body.**
- **Length floor (frozen): 1000 characters.** Used only inside the "substantive"
  test, never as a standalone discard signal.
- **Decision:** `valid` (auto) iff *no refusal-intent* AND (length ≥ floor OR has
  structural body). **Everything else → `review`** (human queue; excluded from
  auto-pairing until adjudicated). The gate never auto-`invalid` at pilot scale —
  it never silently discards a possibly-valid output.

**Frozen expected labels — 12 archived `zivtech_prototype` outputs**
(`evals/results/wordpress-skill-candidate-eval/wordpress-candidate-pilot-20260616-live/`):

| run / fixture | label |
|---|---|
| run-1 block-development-risk | valid |
| run-1 content-model-ambiguous | review |
| run-1 performance-ops-clean | review (true refusal) |
| run-1 security-boundary-risk | valid |
| run-2 block-development-risk | valid |
| run-2 content-model-ambiguous | review (true refusal) |
| run-2 performance-ops-clean | valid |
| run-2 security-boundary-risk | review |
| run-3 block-development-risk | valid |
| run-3 content-model-ambiguous | valid |
| run-3 performance-ops-clean | valid |
| run-3 security-boundary-risk | valid |

Auto-valid = 8; review = 4 (2 true refusals + 2 refusal-flavored 100-scorers).
No true refusal is ever auto-valid; no valid output is ever auto-discarded.

**Frozen expected labels — 9 held-out adversarial fixtures** (authored to defeat
the detector; `evals/harness/tests/fixtures/`): a_short_valid_heading=valid,
b_anchorless_prose=valid, c_padded_refusal_heading=review, d_refusal_quotes_fence=
review, e_fake_recovery=review, FN1_post_window_refusal=review,
FN2_out_of_set_bodyless=review, FN4_out_of_set_padded=review,
FP3_valid_quotes_phrase=review.

**Defense-in-depth.** The gate is the first filter; the blind pairwise judge (a
non-answer loses every comparison) and the human-review queue are backstops.
Residual ceiling (a long, *structured* refusal using no recognized refusal
vocabulary) is accepted as judge-backstopped.

**Auto-invalidate option (deferred).** If review load (~33% at pilot) is too high
at 27-fixture scale, a narrow auto-`invalid` rule (refusal-intent + no structure +
short) may be added, accepting the contrived FP3 residual. The pilot uses
escalate-first.

---

## 4. Reliability gate (frozen)

- **Primary metric: Gwet's AC1**, justified on prevalence-robustness (pairwise
  labels are expected skew-prevalent; Cohen's κ collapses under extreme prevalence
  — the kappa paradox). Multi-category form: `pe = (1/(K−1))·Σ πk(1−πk)`,
  K = declared category count = 3 (A/B/tie). Implementation:
  `compute_kappa.gwets_ac1_multi`; verified to reduce to the binary tool at K=2.
- **Reported alongside (never hidden): Cohen's κ and PABAK.**
- **Floor: AC1 ≥ 0.70**, and the gate requires the **bootstrap 95% CI lower
  bound** to clear 0.70 — not the point estimate — because pilot n (≈12–72
  judge-pair items) yields a wide CI. If the CI lower bound cannot clear, the run
  is marked **directional-only** with the full CI reported.
- **Prevalence fallback:** if the observed label distribution is *not* extreme
  (min-category share > 0.20), report κ as **co-primary** — the AC1-preference
  justification no longer holds.
- **Weighting:** ordinal-weighted 3-way agreement (A < tie < B; a polar A/B flip
  is a larger disagreement than an A/tie near-miss). Nominal reported as a
  secondary cross-check.

---

## 5. Preference signal (frozen) — the headline decision variable

Separate from reliability. The preference side "passes" only if **all** hold:

- **Statistic:** paired win-rate of known-strong over known-weak across
  fixtures×runs, with a **bootstrap 95% CI**; plus a sign/binomial test on
  A-wins vs B-wins.
- **Directionality + margin:** known-strong wins at win-rate ≥ **0.60** AND the
  95% CI excludes 0.50.
- **Tie-rate cap (anti-saturation):** if tie rate > **0.40**, declare pairwise
  **saturated** (the all-ties degenerate) and revise the instrument — pairwise
  must not silently inherit the absolute-scoring ceiling.
- **Half-invalid pairs:** if the gate flags one side as `review`/invalid, the
  pair is **dropped** (not forfeited) and recorded; denominator is the count of
  fully-valid pairs.
- **Multiplicity:** up to 6 condition-pair contrasts → report all descriptively;
  **no single contrast is a GO on its own.** If any contrast is elevated to a
  decision, apply Benjamini-Hochberg across the 6 (matches `eval.yaml` FDR).

**27-fixture unblock requires BOTH** the preference side (this section) **and**
the reliability side (§4) to clear.

---

## 6. Generation isolation (frozen) — vector CONFIRMED

**Confirmed primary vector (diagnosed from the v1 run, 2026-06-16): config/context
discovery from `cwd`.** The v1 harness (`run_wordpress_candidate_pilot.py:run_claude`)
applied no isolation beyond setting `cwd`, and ran the `zivtech_prototype` condition
with **`cwd = the repo root`** (`/path/to/zivtech-meta-skills`) plus
`--agent <name>`. Launching `claude -p` from inside the repo makes it discover the
repo's root `CLAUDE.md` (which documents the eval/harness infrastructure) and the
repo's `.claude/` tree.

**Smoking-gun evidence:** the `zivtech_prototype` output
`run-1/raw/zivtech_prototype/performance-ops-clean.md` names
`run_wordpress_candidate_pilot.py` and `score_with_claude_cli.py`. Those strings
appear in **neither the fixture (0 matches) nor any agent prompt (0 matches)** — the
agent could only have learned them from discovered repo context. Baselines and
upstream, which ran in `/tmp` dirs, show **0** such leakage. The contamination is
therefore `zivtech`-condition-specific and `cwd`-driven, asymmetric vs. the
baselines — and it plausibly drove the refusals (the repo `CLAUDE.md` framed the
task as "score a candidate," so the agent noticed no candidate was attached and
refused).

**Secondary vectors (mechanism-certain; the harness applied zero isolation):**
(a) user-level `~/.claude/` discovery loads into *every* condition regardless of
`cwd` (this is the one that survives a `/tmp` cwd); (b) `bypassPermissions` with no
`--strict-mcp-config` loads any user/project-scoped MCP servers; (c) `run_claude`
calls `subprocess.run` with **no `env=`**, so `CLAUDE_*`/`ANTHROPIC_*` and the full
environment pass through.

**Enforcement (closes all of the above):** run each generation (1) from a **scratch
`cwd`** (empty temp dir, never the repo) so no repo `CLAUDE.md`/`.claude` is
discovered; (2) **inject the agent prompt as message content, NOT via `--agent`** —
`--agent` itself triggers repo `.claude/agents` discovery; (3) scratch `HOME` and
`XDG_CONFIG_HOME` (empty temp) to block user-level `~/.claude/`; (4)
`--strict-mcp-config` with an empty MCP config; (5) drop **config-redirect** env
vars (`CLAUDE_CONFIG_DIR`) only; (6) non-interactive `-p`. The posture is recorded
in each output's generation metadata.

**Authentication MUST survive isolation (live-run correction, 2026-06-17).** The
first enforcement draft scrubbed *every* `CLAUDE_*`/`ANTHROPIC_*` env var, which
removed the CLI's auth token: every isolated generation failed "Not logged in,"
read as a vacuous "clean" run, and the pilot crashed with zero valid pairs. Fix:
preserve auth credentials (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`CLAUDE_CODE_OAUTH_TOKEN`) and **seed only `~/.claude/.credentials.json`** into the
scratch `HOME` (never `CLAUDE.md`/settings/agents/MCP). The smoke test now asserts
the isolated run is **non-empty and authenticated** before checking the sentinel,
so a broken-auth run can never read as a false pass.

**Proof:** `evals/harness/tests/test_isolation_smoke.py` plants the confirmed-vector
sentinels — a `./CLAUDE.md` in a repo-shaped cwd AND a `~/.claude/CLAUDE.md` — and
asserts the isolated run (scratch cwd + scratch HOME + strict MCP + scrubbed env)
emits neither. Necessary-not-sufficient: it shows the confirmed vectors are closed,
not that every conceivable vector is.

---

## 7. Human validity anchor (Decision A — deferred)

Reliability ≠ validity. Run the two-judge pairwise design first; compute AC1
(+ κ, PABAK). **Only if the AC1 CI lower bound clears 0.70**, add a lightweight
non-Claude human spot-check (existing annotation tool + `compute_kappa.py`) over a
handful of pairs as the validity anchor before the 27-fixture decision. If AC1
fails, **stop and fix judging** — validity is *unestablished*, not "moot." No
claim that AC1-passing alone validates.

---

## 8. Analysis order (frozen)

1. Generate (isolated) → classify (validity gate) → quarantine `review` to queue.
2. Blind pairwise judging, two raters, randomized A/B order recorded.
3. Reliability: AC1 (+ κ, PABAK) with bootstrap CI; check CI-lower-bound vs floor;
   apply prevalence fallback if needed.
4. Preference: win-rate + CI + tie-rate; check §5 thresholds.
5. Decision A branch (§7). 27-fixture run stays blocked; any result internal-only.
