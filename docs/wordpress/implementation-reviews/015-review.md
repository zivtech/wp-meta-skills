Plan: 015
Plan base SHA: 36b15c8b8c220a7468a3ab4fc45596d9dabe2317
Reviewed code tip SHA: a928606bbfefcb187e7b5f27974bfbd6e943c0eb
Implementation/fix commits: a928606bbfefcb187e7b5f27974bfbd6e943c0eb
Verdict: ACCEPT

# Plan 015 Implementation Review

## Scope and schema inventory

The reviewed range replaces permissive YAML loading with a bounded, typed
integrity boundary for the live evaluation corpus: 15 eval configurations, 61
fixture metadata documents, and 61 rubrics. Every live document maps to one of
four named eval profiles, four metadata profiles, or three rubric profiles.
Duplicate keys retain source location, while anchors, aliases, explicit tags,
oversized input, invalid UTF-8, non-mapping roots, unsafe paths and patterns,
and malformed profile fields fail closed with stable structured issues.

Eval configuration is validated before any mapping access, path join, or glob.
Metadata validation covers filename identity, suite identity, substantive
expectations, and the existing runtime-assertion contract. Rubric validation
covers identity, maximum score, criterion identifiers and categories, numeric
weights with a documented tolerance, domain signals, and discrimination gates.
Structural issue families cannot be suppressed through the known-gap ledger,
and requesting a missing strict suite fails.

The bounded amendment also connects accepted domain signals to the real LLM
rubric scorer. `expected_surfaces` produces one aggregate quality criterion;
each `must_not_claim` entry produces a separately identified inverted
false-positive trap. Existing weights and arithmetic are unchanged, so the
affected rubric denominator intentionally grows by the added unit weights.

## STOP condition and review dispositions

Implementation exposed a pre-existing contract gap: the validator accepted
`expected_surfaces` and `must_not_claim`, but the LLM scorer did not consume
them. Work stopped, Plan 015 was marked blocked, and a bounded amendment adding
`evals/harness/llm_judge.py` was cold-reviewed before implementation resumed.
The amendment fixed exact IDs, categories, weights, inversion semantics,
combined-signal expectations, and collision handling; cold review accepted it.

General and security review found real false-green and resource-boundary
classes. The implementation was revised to reject mapping values in scalar
fields, recursive `**` patterns, missing strict suites, non-finite accumulated
weights, suite-root symlinks, control characters in diagnostics, and unbounded
or symlink-following `QUALITY_GAPS.md` reads. Surrogate-bearing input now
produces a safe structured diagnostic instead of crashing. The quality-gap
ledger uses the same bounded, nonblocking, no-follow regular-file boundary as
YAML documents, and its structural failure is unsuppressible during strict
validation.

Both critics re-reviewed the exact committed tip and returned `ACCEPT` with no
remaining Critical, Major, or Minor findings.

## Verification

- Manifest verification, agent/skill frontmatter validation, exact WordPress
  API contract validation, and the exact seven-suite strict validation passed.
- CI-equivalent ordinary harness bundle: `989 passed, 1 deselected in 45.72s`.
- Cumulative ordinary repository gate: `2001 passed, 3 skipped, 41 deselected
  in 53.97s`.
- Focused integrity suite: `98 passed`; the final general review also ran 119
  focused and adjacent scorer tests.
- All 61 live rubrics extracted through the scorer with unique criterion IDs.
- YAML workflow parsing, Python compilation, `git diff --check`, and scoped
  changed-file checks passed.
- The validator is 799 lines and the scorer is 712 lines. No newly introduced
  function exceeds 50 lines.
- The staged implementation secret scan examined approximately 66.17 KB and
  reported no leaks.

## Negative space

This plan proves structural/schema integrity for the named current profiles; it
does not prove that fixture prose, answer keys, rubrics, or model judgments are
correct or high quality. It does not establish benchmark superiority or
provider/runtime behavior. Rejecting all explicit YAML tags, anchors, and
aliases is an intentional repository contract, not a claim that safe YAML
implementations can never support those features.

The domain-signal scorer change is limited to LLM rubric extraction.
`must_not_claim` remains inverted: meeting the trap means the prohibited claim
appeared. The separate high-risk lexical scorer still consumes only its
reviewed archived security, performance, and migration evidence; Blueprint is
not silently added. Lexical or model scoring remains evidence about an output,
not proof that WordPress code is safe, callable, installed, or operational.
