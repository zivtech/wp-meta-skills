Plan: 008
Plan base SHA: f1e1fad98a6c0a51062f53780553f0116b284b5c
Reviewed code tip SHA: c4f561e2a8fe41670bfcc8f82cce0227f31588a7
Implementation/fix commits: 55b509a7156b673168ed9cdbeba9113ee559b51f 796f1e48fbb24b57f45902386f162ac744808d90 fe0a102225b8a0789d598f9ff09ca84ed7c4dc2d c4f561e2a8fe41670bfcc8f82cce0227f31588a7
Verdict: ACCEPT

# Plan 008 Implementation Review

## Scope and amendments

The reviewed range makes static and runtime repair certification consume fresh, exact, identity-bound evidence. It removes fuzzy global runtime-result lookup, refuses reused run/result directories through Plan 006 leases, binds evidence IDs and canonical execution-closure digests, captures subprocess return codes, requires explicit top-level/profile/check passes, and bounds repair diagnostics.

Cold planning amended the plan to preserve standalone CLI compatibility, define canonical digest bytes, bind runtime proof to staged bytes, fix the synthetic failure vocabulary, and reject symlinked output ancestors. A later STOP-condition amendment added `workspace_lease.py` and its direct tests so both CLIs could consume one public `validate_safe_name()` implementation. Both amendments were cold-reviewed before tracked edits continued.

## Review history and dispositions

The initial implementation was rejected because runtime hashed mutable source bytes rather than the staged execution tree, canonical digest and parent-symlink requirements were incomplete, and the runtime imported a private validator. Those defects were corrected before the first code tip.

General and security review of `55b509a7156b673168ed9cdbeba9113ee559b51f` then found inconsistent copy/digest ignores, unsafe default `copytree()` symlink following, an `lstat()`/read race, unbounded diagnostic identifiers/details, and incomplete artifact discovery. Commit `796f1e48fbb24b57f45902386f162ac744808d90` introduced bounded no-follow staging/digest reads, shared closure ignores, and structured diagnostic bounds.

Re-review found intermediate/root descriptor races, loss of subordinate machine-readable statuses, and contradictory blocked checks that could pass. Commit `fe0a102225b8a0789d598f9ff09ca84ed7c4dc2d` moved traversal to retained directory descriptors, bounded snapshots before copying, preserved nested fail/blocked status, and rejected contradictory evidence.

Final security review found one call-site still resolving the source before descriptor traversal. Commit `c4f561e2a8fe41670bfcc8f82cce0227f31588a7` preserved the absolute-but-unresolved path through the descriptor boundary and added a root-swap staging regression. Final WordPress general review: ACCEPT. Final WordPress security review: ACCEPT. No unresolved Critical, Major, or Minor findings.

## Verification

- Four focused modules at reviewed tip — 115 passed.
- `python3 -m pytest evals/harness/tests/ -q` — 264 passed, 10 skipped.
- Python compilation of changed harness modules — passed during executor gates.
- `git diff --check` — clean before commits.
- Scoped diff secret scans found only intentional identifier/redaction test strings, not credentials.
- No Docker, npm, network, model, or live wp-env call was used by the hermetic tests.

## Negative space

This packet does not claim live Docker/wp-env proof, hostile generated-package sandboxing, or block/Blueprint runtime adapter support. Plans 009 and 011 own those boundaries. Atomic JSON replacement prevents partial/stale consumption but does not claim power-loss durability.
