# Pre-Registration — WordPress Critic Evaluation Corpus (recommendation 09)

Status: **design norm for the critic-corpus instrument.** Covers the four critic suites
(`wordpress-critic`, `wordpress-security-critic`, `wordpress-performance-critic`,
`wordpress-theme-critic`). A norm, not a tamper-proof control; git history makes edits visible.

Companion (do NOT edit): `../wordpress-skill-candidate-eval/answerkey-diagnostic-prereg.md`
is the frozen design of the answer-key instrument this corpus reuses. This document adds a
labeled *fixture corpus* for the critics; it does not change the scorer's judging math.

Governing boundary: `CLAUDE.md` "Evaluation Boundary" — internal diagnostic only, never a
superiority or equivalence claim.

---

## 1. The decision this serves

The four critic suites each shipped with one smoke fixture that restated the contract rather
than presenting a WordPress scenario (`eval.yaml: status: smoke_scaffold_only`). The
answer-key instrument (`evals/harness/answer_key_score.py`) already existed and is good; the
gap was labeled data. This corpus is that data: real WordPress review targets, each with a
`domain_signals` answer key, split into three provenance-labeled tranches so a score can say
*which* capability it measured.

Recommendation 09 measures the *current* critic to establish the baseline that recs 01/02/03
will later be measured against. It does **not** change any critic prompt.

## 2. The instrument (reused, suite-aware)

`answer_key_score.py --suite <critic-suite>` scores each output against the rubric's
`domain_signals`:

- `must_detect` → detection **recall** (blind, atomic one-item-per-call judge, span-verified).
- `expected_wordpress_apis` → **API coverage** (deterministic normalized substring).
- `must_not_penalize_or_do` → **specificity** = 1 − anti-pattern rate.

Conditions: `skill`, `baseline-zero-shot`, `baseline-few-shot`. Strong pole = `skill`, weak
pole = `baseline-zero-shot` (the discrimination self-check must clear ≥ 0.20 or the read is
saturated). The judge is blind to condition. None of this scoring math changed; only
suite-aware loaders, a `--suite` path, and additive per-tranche reports were added
(I/O layer, unit-tested).

**Judge family (amended 2026-08-13).** "Cross-family by default" held only for the `skill`
lane. Generation is split — the skill lane runs on a local Claude agent, both `baseline-*`
lanes on local Codex — so a single non-Claude judge scored the baselines *same-family* and
the skill *cross-family*, an asymmetry pointing at the one lane under test. The corpus now
defaults to `--judge-mode balanced`: one judge per family, scores averaged, so each condition
gets exactly one same-family and one cross-family judgment. `judge_self_preference` reports
the per-condition size of the effect, and the scorecard marks any single-family panel as
uncontrolled. A balanced run without an explicit `--judge-2` appends the counterpart judge
rather than silently degrading.

## 3. The three tranches

Each fixture is a review target (`fixtures/<id>.md`) + a `suite-risk`/`suite-smoke`
`metadata.yaml` + a `weighted-domain` `rubric.yaml` + a `fixtures/<id>.provenance.yaml`
sidecar. The sidecar carries `tranche`, `provenance`, `license`, `source`, `expected_verdict`,
`status`, and (for J) a `tool_invisibility` block and per-signal `grounding`
(cwe/sniff, file, line, severity).

- **T (tool-consumption, `provenance: tool`).** Canonical sniff-catchable defects
  (EscapeOutput, NonceVerification, ValidatedSanitizedInput, PreparedSQL, PostsPerPage). A
  linter scores ~100%; the critic's bar is faithful consumption. Grounded by `sniff` + line.
- **J (judgment, `provenance: researcher`|`authored`).** The discriminating set. Every J
  fixture passes WPCS **and** PHPStan clean **by construction** — a critic that only relays
  tool output scores zero here. Weighted to Broken Access Control (IDOR, wrong-object
  capability, nonce-result-discarded, decorative-capability-branch, wrong-sanitizer-for-sink).
  Tool-invisibility is an *entry criterion*, verified by
  `evals/harness/verify_critic_tool_invisibility.py` (WPCS **and**, since 2026-08-13,
  PHPStan) and recorded in the sidecar.
- **C (clean / false-positive trap, `expected_verdict: ACCEPT*`).** Code that looks
  suspicious but is correct. The mandatory one: `permission_callback => '__return_true'` on a
  genuinely public read-only endpoint — same token as the BAC defect, opposite verdict. A
  finding raised here is a false positive; the tranche-C false-positive rate is reported
  separately from recall.

## 4. Why a sidecar and not dict-items in `must_detect` (deviation from the source spec)

The source spec proposed making `domain_signals.must_detect` items either strings or dicts
carrying `cwe`/`file`/`line`, and a rich `metadata.yaml`. Both are **schema-illegal** under
`scripts/validate-eval-suite-integrity.py`, which freezes `domain_signals` values to nonempty
*string* lists and freezes metadata/rubric to a small set of exact-key profiles, with
whole-corpus tests asserting every file matches one. `llm_judge` likewise requires string
items. Adopting dict-items would have required editing those frozen, heavily-tested contracts.

Resolution: keep the rubric and metadata schema-legal; carry the structured grounding
(cwe/sniff, file, line, severity — keyed by the exact `must_detect` description string) plus
tranche/provenance/license/tool-invisibility in the un-policed `.provenance.yaml` sidecar. The
scorer reads the sidecar additively and carries the fields into the scorecard; the
description remains the judged, span-verified recall unit, computed exactly as before. The new
`evals/harness/tests/test_critic_corpus_integrity.py` is what polices the sidecar and enforces
anti-leakage.

## 5. Anti-leakage & tool-invisibility gates (CI)

- `test_critic_corpus_integrity.py`: the quad is complete; the sidecar schema is valid;
  license is allowed and no source is a non-commercial feed (WPScan/CC BY-NC forbidden); a J
  fixture proves tool-invisibility; a C fixture is ACCEPT* with no `must_detect`; the review
  target `.md` leaks no `must_detect` substring, `CWE-`/sniff token, `// BUG|VULN|FIXME` hint,
  or "this code has…" preamble; grounding maps to real `must_detect` items; draft stubs stay
  out of the scored root.
- `verify_critic_tool_invisibility.py`: every tranche-J fixture is run through WPCS and must
  show zero security/perf sniffs firing, or it is mislabeled and belongs in T.
  **PHPStan half added 2026-08-13.** The "and PHPStan" in §3 was asserted from the corpus's
  first day but never executed, though the PHPStan stack was pinned in `php-tools` the whole
  time. It now runs at `level: max` and classifies findings **default-deny**: only
  identifiers on a justified benign allowlist pass, so a PHPStan upgrade that starts seeing
  a J defect trips the gate instead of passing quietly the way the WPCS deny-list would.
  The gate also now runs in CI; it was manual, so a mislabeled fixture could have landed
  unnoticed. Result on the current corpus: all nine PHP-bearing J fixtures are invisible to
  both tools. The claim was true; it simply had never been checked.

  **The excerpt limitation, measured and narrowed 2026-08-13.** It was first recorded as
  "the gate analyses excerpts, not plugins". Quantifying it moved the problem:

  - **Scope is one fixture, not the corpus.** Only `sec-like-wildcard-no-esc-like-v1`
    declares a global at all; the other nine J fixtures have none, so the untyped-`$wpdb`
    masking route cannot apply to them.
  - **The real hole was the allowlist, not the excerpt format.** All 15 `argument.type`
    findings in the corpus are the `mixed`-propagation shape untyped `$_POST`/`$_GET` input
    produces, so allowlisting the identifier was accurate *for today's corpus*. But the same
    identifier carries `wpdb::prepare() expects literal-string, non-falsy-string given` —
    PHPStan's SQL-injection heuristic. Measured on a typed variant of that fixture, the
    literal-string finding was classified **benign** by the identifier-only allowlist. The
    gate would have suppressed a genuine SQL-safety signal.
  - **Fixed.** `argument.type` is now benign only when the message carries `mixed given`;
    anything else disqualifies. `class.notFound`/`function.notFound` were dropped from the
    allowlist entirely — they never fire here, and "this WordPress function does not exist"
    is a real defect class. The corpus still passes 0-disqualifying as analysed, and the
    typed variant now correctly reports 2 disqualifying findings.

  What remains open is narrower than first stated: PHPStan sees more in typed code than in
  these excerpts, so "PHPStan clean" is still established **for these fixtures as analysed**.
  The gate no longer mistakes a real signal for noise when it does appear, which was the
  part that could have produced a false clean before recommendation 01 runs tools in situ.

## 6. Honest limitations (also written into `pilot-results.md`)

- **This corpus measures the critic; it does not improve it.** The first honest run may well
  confirm the skill trails a strong few-shot baseline — that localization *is* the deliverable.
- **The few-shot baseline must be strong or the eval lies.** The `baseline-few-shot/` prompts
  name the dimensions and carry worked findings *and a calibration non-finding*; they still owe
  an independent reviewer's sanity check (a human who is not the fixture author) before any
  comparative reading is trusted.
  **Review package prepared 2026-08-13:** [`baseline-strength-review.md`](baseline-strength-review.md),
  open and awaiting a reviewer. It also records a finding that reframes the check: the
  few-shot prompts already contain a mean **0.79** of the corpus's own
  `expected_wordpress_apis` answer key before reading any fixture (zero-shot: 0.00), measured
  by `evals/harness/measure_baseline_api_leakage.py`. The risk is therefore not only a weak
  baseline inflating the skill, but a prompt-supplied API vocabulary deflating it on the one
  axis the pilot called its clearest signal. Both directions are open until that review lands.
- **Tranche T can't fully exercise the critic until rec 01 lands** (the critic still can't run
  tools). T establishes the target and baseline now; consumption is measured after 01.
- **CVE-diff labels are noisier than WPCS's** — the `researcher` tranche is staged as drafts
  under `fixtures/_drafts/` and requires the human verification gate before scoring.
- **This is an instrument, not a benchmark.** The corpus measures direction and localizes
  weakness; it does not certify quality. Scale via the CVE pipeline before any superiority
  claim, and keep the "not a benchmark" caveat.

## 7. What this licenses

- ✅ Localizing, by tranche, where the skill helps / doesn't vs strong baselines (internal).
- ✅ A tranche-C false-positive rate and a tranche-J recall as separate, honest numbers.
- ❌ Any "skill beats / equals baseline" claim — same firewall as the candidate eval.
- ❌ Editing the frozen answer-key design or the eval-suite validator's contracts.
