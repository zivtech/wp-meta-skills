Plan: 014
Plan base SHA: b8beb684d3818818435dc34b839fa0cc8ae5daa6
Reviewed code tip SHA: dabc4912585e618a26a27f524bb6e0136924fc91
Implementation/fix commits: 39ace831af6e9f10246756075eddd5f8f0905025 dabc4912585e618a26a27f524bb6e0136924fc91
Verdict: ACCEPT

# Plan 014 Implementation Review

## Scope and architecture

The reviewed range replaces shape-only exact-surface guesses with a typed,
WordPress-7.0-aligned contract. Core functions and classes resolve through the
committed symbol snapshot. Hooks, argument keys, capabilities, WP-CLI commands,
packages, named oracles, file/glob surfaces, and reviewed composed surfaces are
explicit registry categories. Both the rubric validator and saved-output oracle
fail closed on missing, malformed, version-incompatible, duplicate, unsafe, or
category-invalid registry data.

The symbol generator now fetches two immutable raw GitHub inputs through the
bounded `safe_curl` transport, verifies their embedded SHA-256 values and
Composer-lock identities, and introspects the stubs in the locally provisioned
Composer platform-child image with no network, a read-only root filesystem,
dropped capabilities, non-root execution, and bounded resources. The committed
snapshot records source, generator, command, container, and normalized-symbol
provenance without changing the native lint's schema-version compatibility.

Output occurrence matching is contiguous and boundary-aware. It accepts the
reviewed dynamic `wp_ajax_*` family and safe project paths/basenames, but rejects
partial identifiers, traversal/absolute/path-segment forms, PHP variables,
object/nullsafe/static methods, error-suppressed forms, and their adjacent or
whitespace-separated variants. Scoped non-applicability requires a named
subproblem, substantive no-control boundary, and concrete owner/oracle, and it
never changes the minimum exact-surface count.

## Review history and dispositions

Tests landed first and reproduced the invented-identifier, generic-phrase,
partial/scattered, blanket-waiver, registry, and provenance failures. The first
implementation preserved symbol snapshot schema `2`, which the cumulative gate
proved incompatible with `wp_api_lint.py`; the implementation was fixed back to
schema `1` while retaining separate generator schema/version metadata.

General and security review then found several real false-green classes. The
implementation was revised to align classifier and output grammars for dynamic
hooks, paths, basenames, and WP-CLI entries; require contextual generic argument
keys; preserve Abilities API `permission_callback`; validate registry boundary
and provenance metadata; reject vacuous non-applicability; support optional
function parentheses inside composed surfaces; and restore the committed
scattered-token RED expectation.

Further adversarial probes found basename matches inside traversal contexts,
the short core `wp` symbol inside `.wp-env.json`, and global API names inside PHP
variables and adjacent/spaced method, nullsafe, static, and `@` contexts. A
bounded operand-independent pre-context guard now covers core, composed,
registered identifier, and dynamic-hook categories. Final general and security
re-reviews accepted the exact code tip with no unresolved Critical, Major, or
Minor findings.

## Verification

- Direct exact-API validator: passed.
- Focused provenance/exact-surface/output suite: `107 passed`.
- Focused suite plus API-lint regression: `140 passed in 35.44s`.
- Cumulative ordinary harness gate: `1903 passed, 3 skipped, 41 deselected in
  52.66s`.
- Two immutable-source maintainer rebuilds and the final reviewed rebuild were
  byte-identical to `evals/harness/data/wp-symbols.json`; snapshot SHA-256 was
  `1b2d6a5a292b61fbf3498246b622f237291a9693a473829e526d16ea896b8b69`.
- Python compilation, direct registry inventory, `git diff --check`, and
  changed-file scope checks passed.
- The saved-output validator is 799 lines; the builder and exact-contract
  validator are 329 and 359 lines. No newly introduced function exceeds 50
  lines.
- Gitleaks found no leak in the 47.37 KB staged implementation after excluding
  the regenerated snapshot. Its four redacted snapshot findings were public
  `sodium_crypto_*` PHP function names; the excluded file separately passed the
  immutable-source byte comparison and ten hermetic provenance checks.

## Negative space

Registry membership proves reviewed contract vocabulary, not installation,
callability, compatibility, correct usage, or runtime execution. Text occurrence
proves only a bounded lexical match. The oracle is not a PHP AST, name resolver,
taint analyzer, authorization review, or runtime-existence check. Third-party
packages and hooks still require their own target-runtime evidence.

The reproducibility result is proved on the reviewed arm64 maintainer platform;
the snapshot records both reviewed platform-child digests, but this packet does
not claim a separately observed amd64 rebuild. The Docker CLI and daemon remain
trusted maintainer-host components. Ordinary CI validates committed metadata and
internal digests without fetching sources or pulling images.

Scoped non-applicability can document a boundary, but cannot excuse missing
concrete surfaces elsewhere in the deliverable. Safe-path acceptance does not
open or execute a path. Quoted callable names remain lexical evidence and do
not prove whether a callable is global, static, or object-bound at runtime.
