# Pre-Registration — WordPress Answer-Key Diagnostic

Status: **design norm for a NEW instrument.** Not a certifier. This file is a
*norm*, not a tamper-proof control (an admin can edit it; `git` history makes
edits visible). It exists so the diagnostic's design is fixed before it is read.

**Companion (do NOT edit):** `pairwise-prereg.md` is the FROZEN pairwise-preference
design; its run history (`pairwise-pilot…`, `pairwise-cert-1`, `pairwise-cert-2-xfamily`)
stands as recorded. This diagnostic is **additive** — a different instrument that
reuses the same fixtures, rubrics, and committed generations. It neither replaces
the pairwise eval nor reopens it.

Governing boundary: `wordpress-skills/CLAUDE.md:34-38`.

Post-run amendment, 2026-06-20: the archived `answerkey-diag-fast` and
`answerkey-diag-adversarial` runs remain pre-amendment diagnostics. Future reruns
use stricter exact-surface `expected_wordpress_apis` rubric entries and API
normalization that collapses code/path/package punctuation while preserving
WordPress function underscores. The deterministic gate is
`scripts/validate-wordpress-exact-api-contract.py`.

---

## 1. Purpose & the decision it serves

The pairwise eval reached a defensible *null-ish* verdict: zivtech is directionally
top-tier but ties a strong few-shot baseline, and the judge-reliability gate did not
certify. That instrument grades a **race** (which output is better, one bit per
pairing). The decision now in front of us is different: **improve the skill** — find
*where* V1 should add value and harden it there. A race result cannot localize a gap;
a **diagnostic** can.

This instrument scores each output against the **objective answer key already present
in every rubric** (`domain_signals.must_detect`, `expected_wordpress_apis`,
`must_not_penalize_or_do`) and reports, per condition and per fixture, three axes:

- **Detection recall** — did the output identify the issues a strong response must catch?
- **API coverage** — did it name the expected WordPress-native APIs (literal mention)?
- **Specificity** — did it AVOID the listed anti-patterns / false moves (e.g. inventing
  bottlenecks on a clean control)? Reported as `1 − anti_pattern_rate`.

The diagnostic value is the **per-axis, per-fixture, per-condition breakdown** and the
**zivtech-vs-baseline deltas** on each axis — i.e. the exact signal needed to decide
whether and where to change the skill.

### Internal-only firewall (unchanged)

No result here is evidence that "V1 outperforms upstream or baseline" in the sense
`wordpress-skills/CLAUDE.md:34` forbids. A detection-recall or specificity delta is an
**engineering diagnostic**, not a superiority claim, and not an equivalence claim.
Answer-key recall measures coverage of a *predefined* list; it does not measure
consulting quality, and the answer key is a **floor, not a ceiling** (see §7).

---

## 2. Inputs (frozen for the first run)

- **Generations: reused, never regenerated.** Read committed outputs from a prior run's
  `checkpoint/gen/` via `--gen-from` (default `pairwise-cert-1`). Filenames:
  `r{run}__{fixture}__{condition}.txt`. The first diagnostic re-scores the **same 48
  outputs** the pairwise cert judged, so the two instruments are compared on identical
  artifacts (this is the cheapest possible read — zero generation cost).
- **Conditions (4):** `baseline-zero-shot`, `baseline-few-shot`, `raw_upstream_candidate`,
  `zivtech_prototype`. Known-weak = `baseline-zero-shot`; known-strong (hypothesized) =
  `zivtech_prototype`.
- **Pilot fixtures (4):** `security-boundary-risk`, `block-development-risk`,
  `content-model-ambiguous`, `performance-ops-clean` (tiers: HAS_RISK, HAS_RISK,
  AMBIGUOUS_TRADEOFF, CLEAN_CONTROL). Scales to the full 27 later without a gate change —
  there is no reliability/power gate to clear, because this is a diagnostic, not a
  certifier.
- **Answer key per fixture:** `rubrics/{fixture}.rubric.yaml → domain_signals`.

---

## 3. Metrics (frozen definitions)

For one output `o` scored against its fixture's answer key:

- `recall(o)  = confirmed_must_detect / total_must_detect`
- `api_coverage(o) = matched_expected_apis / total_expected_apis`  (deterministic match, §5)
- `specificity(o) = 1 − (committed_anti_patterns / total_anti_patterns)`
- `composite(o) = mean(recall, api_coverage, specificity)`  — a transparent equal-weight
  summary used ONLY for the discrimination self-check (§6). The three axes are the
  product; the composite is a convenience scalar, not the finding.

Aggregation: report each axis as the mean over fixtures×runs **per condition**, and a
**per-tier** breakdown (RISK / AMBIGUOUS / CLEAN), because the hypothesized skill edge
is tier-specific — recall on RISK/AMBIGUOUS, specificity on CLEAN. Pooling tiers hides
the signal (the pairwise eval's core mistake).

**Clustering (anti-pseudoreplication).** The 3 runs within a fixture are correlated; they
are NOT 3 independent samples. CIs on deltas use a **cluster bootstrap resampling
fixtures**, not individual outputs. With only 4 pilot fixtures these CIs are honestly
very wide — the per-axis point breakdown is the deliverable at pilot scale, not a tight
interval.

---

## 4. Judge protocol & reliability mitigations (frozen)

Each `must_detect` and `must_not_penalize_or_do` item is graded by an **atomic, blind,
single-item** check. The judge sees the fixture, ONE answer-key item, and the response —
**never the condition name**, never the other conditions, never the full rubric. Direction
of bias therefore cancels in condition deltas (the judge cannot favor "zivtech" because
it cannot see which output is zivtech).

Mitigations are deliberate, each grounded in the LLM-judge reliability literature:

- **Atomic one-item-per-call**, not a bundled rubric pass. Bundling prevents partial
  credit and lowers reliability (RIFT "Non-Atomic" failure mode, arXiv:2604.01375; TICK
  shows per-item checklist grading beats holistic, arXiv:2410.03608).
- **Required verbatim span.** A `present: true` verdict MUST quote an exact span from the
  response, and the harness **verifies the span actually occurs in the response**
  (whitespace-normalized substring); an unsupported or fabricated span is **downgraded to
  `false`**. This is the single most important guard: it directly counters the documented
  agreeableness bias where judges confirm satisfied criteria reliably (TPR > 96%) but fail
  to catch unmet ones (TNR < 25%) (Jain et al., arXiv:2510.11822). Evidence-anchoring
  raises rubric reliability (RULERS, arXiv:2601.08654).
- **Reference in prompt.** The answer-key item description is given to the judge as the
  reference for what "correct" looks like (No Free Labels: judges are reliable mainly on
  questions they can themselves answer / are given the answer to, arXiv:2503.05061).
- **Negative-framed instruction.** The prompt states that absence (for `must_detect`) or
  non-commission (for anti-patterns) is a valid and common answer, to blunt
  confirmation/agreeableness drift.
- **Cross-family judge by default.** Generations were produced by `claude-sonnet-4-6`; the
  default judge is a **non-Claude** model via local `codex` (e.g. `gpt-5.5`), so the
  re-score is not self-graded (self-preference bias persists even on objectively
  verifiable criteria — Pombal et al., arXiv:2604.06996). A Claude judge is allowed for an
  agreement cross-check, not as the primary.
- **API coverage is deterministic, not judged.** Expected APIs are matched by normalized
  substring (lowercased, code/path/package punctuation collapsed, WordPress function
  underscores preserved) — no LLM call, perfectly reliable, and it measures exactly the
  rubric's "WordPress-native API specificity" criterion. Limitation: it credits literal
  mention, not paraphrase (§7).

**Optional second judge.** `--judge-2` runs a second blind pass; the harness then reports
**per-item agreement** (raw % + which items the judges split on) as a *secondary
diagnostic* — NOT as a gate. Low agreement on an item flags that item as ambiguous for
re-authoring, which is itself useful skill-improvement signal.

---

## 5. Span & API matching rules (frozen)

- **Span support:** normalize whitespace; the quoted span (or its first 40 non-space chars,
  to tolerate the judge truncating a long quote) must be a case-insensitive substring of the
  response. Fail → verdict downgraded to `false` and logged as `unsupported_span`.
- **API match:** for each `expected_wordpress_apis` entry, normalize both the entry and the
  response (lowercase; collapse code/path/package punctuation such as `$`, `->`, `()`,
  `/`, `.`, `*`, `@`, and `-` into spaces while preserving WordPress function underscores)
  and test substring containment. Multi-token entries (e.g.
  `register_rest_route permission_callback`) match if **all** tokens appear. Records
  matched/total and the matched list.

---

## 6. Discrimination self-check (frozen — run FIRST, before interpreting anything)

Before any condition is interpreted, validate that the instrument can SEE a gap where one
must exist: compute mean `composite(zivtech) − composite(zero-shot)` across fixtures.

- **≥ 0.20** → the instrument discriminates (the threshold the suite already uses for
  rubric discrimination). Proceed to interpret the zivtech-vs-few-shot deltas and the
  per-axis/per-tier breakdown.
- **< 0.20** → the answer-key instrument ALSO saturates (a competent base model satisfies
  the key from a 3-line prompt). Do NOT interpret the few-shot comparison as meaningful;
  report the saturation honestly. The likely fix is harder fixtures whose `must_detect`
  items defeat a zero-shot prompt (and, for code-producing fixtures, defeat a linter — see
  §7), not a different metric.

This mirrors the pre-execution discrimination validation already standard in this suite:
score known-weak vs known-strong first; if the delta is absent, the instrument cannot
support the comparison.

---

## 7. Honest limitations — negative space (frozen)

What this instrument does NOT measure, stated as plainly as what it does:

- **Answer key is a floor, not a ceiling.** A response that catches a real issue NOT on
  the `must_detect` list gets no credit; a response that names every required item can
  still be incoherent, mis-prioritized, or wrong on severity. Recall ≠ quality. Keep a
  **separate holistic track** (the pairwise instrument, or a calibrated absolute-quality
  pass) for the gestalt — do not let answer-key recall stand in for "good consulting."
- **Goodhart.** Once a `must_detect` list is known, outputs can be tuned to name the items
  without substantive reasoning (specification gaming is documented and non-trivial). Treat
  the diagnostic as a development aid, not a target to optimize blindly; rotate/expand
  fixtures when they inform skill changes.
- **Relocated, not removed, judge unreliability.** Decomposition moves the hard judgment
  from "which is better" to per-item "did it catch X" and to answer-key authoring. The span
  guard mitigates the per-item direction but does not eliminate it; ambiguous items will
  still split judges (which §4's optional second judge surfaces).
- **Omission-type anti-patterns are lower-reliability.** Some `must_not_penalize_or_do`
  items are commissions (spanable, e.g. "invent bottlenecks") and some are omissions (e.g.
  "skip capability mapping") with no span. Omission items are flagged in output and should
  be read as weaker signal pending review.
- **API coverage credits literal mention,** not paraphrased intent; a response describing
  "a capability check" without writing `current_user_can` scores 0 on that API. This is
  intentional (it measures specificity) but must not be read as "missed the concept."
- **Does NOT establish superiority or equivalence.** n is tiny; this is localization, not
  inference. Any comparative/benchmark claim remains BLOCKED per `wordpress-skills/CLAUDE.md`.

### Optional anchor-set validation (recommended before trusting absolute levels)

To distinguish "judge is reliable, items are genuinely close" from "judge is noisy," add a
handful of **anchor checks of known answer** — an item the response unmistakably catches
and one it unmistakably ignores — and confirm the judge scores them correctly. Without
anchors, low per-item agreement is ambiguous between a good instrument on hard items and a
bad instrument. Anchors are optional for the delta read (bias cancels in the blind delta)
but required before quoting absolute recall numbers as instrument-validated.

---

## 8. Analysis order (frozen)

1. Load committed generations (`--gen-from`); load per-fixture answer keys.
2. Deterministic API coverage (no judge).
3. Atomic blind per-item checks (`must_detect`, then anti-patterns), span-verified.
4. **Discrimination self-check (§6) — gate interpretation on it.**
5. Per-condition × per-axis × per-tier aggregation; zivtech-vs-baseline deltas with
   cluster-bootstrap CIs.
6. (Optional) second-judge per-item agreement; flag split items for re-authoring.
7. Write `answerkey-summary.json` to a NEW run dir. Interpret into a result doc; do not
   edit this prereg or any pairwise run history.

---

## 9. What this licenses

- ✅ Localizing where V1 helps / doesn't vs baselines, to drive skill changes (internal).
- ✅ Flagging ambiguous answer-key items and weak fixtures for revision.
- ❌ Any "V1 beats / equals baselines" claim — same firewall as the pairwise eval.
- ❌ Editing the frozen pairwise design or rewriting prior run history.
