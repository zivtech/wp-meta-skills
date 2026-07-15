Plan: 013
Plan base SHA: d82190bdcea6fddb3c6c17d978d4e269da77684a
Reviewed code tip SHA: 63af08169c6d9b830d144254a2fc5626ce74d373
Implementation/fix commits: 63af08169c6d9b830d144254a2fc5626ce74d373
Verdict: ACCEPT

# Plan 013 Implementation Review

## Scope and architecture

The reviewed range makes the PHPCS suppression differential occurrence-based
rather than set-based. Normal findings are counted by immutable normalized
file, line, column, sniff source, message type, and whitespace-normalized
message identity. Each ignored-run finding consumes at most one normal
occurrence. Unmatched occurrences remain suppression-hidden evidence, including
duplicates on the same line, and are sorted deterministically only after
matching.

The deterministic gate no longer grants any reviewed-safe suppression by
helper name, PHPCS message, or source excerpt. Every newly emitted
`reviewed_safe_api` is `null`; every unmatched suppressed
`OutputNotEscaped` occurrence remains security-relevant unless the existing
operator-supplied `--allow-suppression-prefix` policy applies. The nullable
field and schema version remain unchanged. Historical v1 nullable-string values
remain readable but are not current deterministic proof and are not rewritten.

## Review history and dispositions

Tests were added first. Ten adversarial cases reproduced the planned set
collision and source/message substring downgrade failures, while the real
pinned-tool genuine-helper case passed. Counter-based one-to-one consumption
then closed duplicate, same-line column, message, normalized identity, and
ordering collisions.

The initial message parser was narrowed to the complete pinned
`OutputNotEscaped` template after review showed free-text `found '…'` could
match negated prose. That still did not establish callable identity. Security
review ran the pinned WPCS toolchain against a defined constant, a
namespaced/local function, and an imported alias sharing the
`get_block_wrapper_attributes` basename. WPCS emitted the same reported name as
for the genuine global WordPress helper. A reflected-request value behind the
suppression could therefore be downgraded to advisory evidence and pass the
hard gate.

That empirical result triggered the plan's unreliable-expression STOP
condition. The original exact-message architecture was rejected rather than
polished further. Before implementation resumed, the ignored plan was amended
and cold-reviewed to remove all automatic reviewed-safe downgrades, keep token
and PHP name-resolution work out of scope, preserve the existing allow-prefix
boundary, require real positive and basename-collision cases to fail closed,
and add the canonical runtime-oracle runbook to scope. The amendment also
separates current always-null producer policy from historical v1 reader
compatibility. General and security critics accepted the amendment.

Final review required the canonical runbook to name the retained explicit
allow-prefix exception. With that correction, both critics accepted the exact
reviewed tip with no unresolved Critical, Major, or Minor findings. The genuine
helper is now a conservative false positive when suppressed; that is an
intentional disposition because basename-only evidence cannot exclude the
demonstrated false-negative/XSS path.

## Verification

- Pinned Composer install: lock verified, nothing to install/update/remove,
  autoload files generated successfully.
- Focused security-gate suite: `54 passed in 2.01s`.
- Mandatory pinned real-tool selection: `15 passed, 39 deselected in 1.92s`;
  zero required environment skips. The four helper-name cases were the genuine
  global call, same-named constant, namespaced/local function, and imported
  alias, and all produced security-relevant hard failures.
- WordPress skill output-contract regression: `14 passed`.
- Cumulative ordinary harness gate: `1812 passed, 3 skipped, 41 deselected in
  52.52s`.
- Changed Python compilation and `git diff --check`: passed.
- The changed source and test modules are 730 and 719 lines; no function in
  either exceeds 50 lines.
- Changed-to-declared scope parity is exact across the gate, tests, schema, and
  canonical runtime-oracle runbook.
- Gitleaks scanned the complete staged implementation/fix diff immediately
  before commit and found no leaks.

## Negative space

This gate does not prove callable identity, PHP name resolution, taint flow,
authorization, capability correctness, exploitability, or contextual safety of
a genuine helper. It deliberately does not parse source excerpts or infer
safety from PHPCS message basenames. The security critic owns manual contextual
adjudication.

The existing operator-supplied `--allow-suppression-prefix` policy is unchanged
and remains the sole deterministic relevance-downgrade boundary. This packet
does not claim that an allow-prefix decision is safe; it records that such a
decision requires explicit operator authority rather than generated-code text.
No new sniff, safe API, allow mechanism, or serialized field was added.

Historical v1 reports containing a non-null `reviewed_safe_api` remain valid
reader inputs, but their non-null value is not evidence under the current
producer policy. Reintroducing any automatic downgrade requires a separately
reviewed callable-identity design plus real constant, namespace, alias, and bait
collision evidence.
