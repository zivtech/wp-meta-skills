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
saturated). The judge is blind to condition and cross-family by default (generations Claude;
judge non-Claude codex). None of this scoring math changed; only suite-aware loaders, a
`--suite` path, and additive per-tranche reports were added (I/O layer, unit-tested).

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
  `evals/harness/verify_critic_tool_invisibility.py` (WPCS) and recorded in the sidecar.
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

## 6. Honest limitations (also written into `pilot-results.md`)

- **This corpus measures the critic; it does not improve it.** The first honest run may well
  confirm the skill trails a strong few-shot baseline — that localization *is* the deliverable.
- **The few-shot baseline must be strong or the eval lies.** The `baseline-few-shot/` prompts
  name the dimensions and carry worked findings *and a calibration non-finding*; they still owe
  an independent reviewer's sanity check (a human who is not the fixture author) before any
  comparative reading is trusted.
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
