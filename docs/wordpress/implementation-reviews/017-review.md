Plan: 017
Plan base SHA: afb3ad2d5837341b9814c93ae976f2118270e102
Reviewed code tip SHA: 414b986edba0ae7566f0ef681e6b390db0930fe5
Implementation/fix commits: 1c09b29b3c0ba393387bd9209b7e469d34f3b1c4 8947b5edd653de80729dd118b28f6705dc852e02 d3b10a554d149fad860fb693b24f2c7c46c45c7a 07975d401a3a486009fd2ed412cfc4a4d2015ed9 5736a2b31e65cbe1985e645405dc1c3c2b680864 414b986edba0ae7566f0ef681e6b390db0930fe5
Verdict: ACCEPT

# Plan 017 Implementation Review

## Scope and distribution contract

The reviewed range connects all five published representations through one
explicit 14-skill/14-agent policy mapping: Claude skills, Agents skills,
Claude Markdown agents, Codex TOML agents, and `skills.sh.json`. Paired skill
metadata and bodies are exact after only the reviewed model-provider prefix
normalization. Paired agent identity, description, and prompt bodies are bound
to the mapping and filename inventory. Protocol, hard-gate, exact-API, and
ordered output-heading projections connect each mapped skill to its agent
without fuzzy matching or lossy whitespace normalization.

The pre-implementation oracle found exactly three real output-contract drifts:
the security, performance, and theme critic skills exposed verdict syntax that
did not match their mapped agents. Commit `1c09b29` changes exactly one line in
each of the six paired skill-host files. Their post-frontmatter bodies remain
byte-equal within each skill pair, and no mapped agent file changed.

`MANIFEST.sha256` is now a deterministic, header-free, sorted control over all
57 distributed files. Generation uses a same-directory temporary regular file,
validates the candidate, fsyncs it, and atomically replaces the prior manifest.
Verification rejects missing, extra, duplicate, malformed, absolute, traversal,
symlinked, non-regular, changed, or unexpected distribution entries. Default
installation verifies first and creates no links after a verification failure;
`--no-verify` remains an explicit operator override.

## Review findings and dispositions

The first general/security/QA pass reproduced four central false negatives:
prompt-only pull requests did not trigger CI; paired agent names were not bound
to inventory; no-follow protection covered only the leaf rather than ancestor
directories; and shared-section parsing stripped prompt-owned whitespace.
Workflow path coverage, explicit name binding, root-anchored directory-FD
traversal, exact host-wrapper removal, and adversarial mutations closed them.

The next pass showed that `splitlines()` still normalized isolated carriage
returns and empty-record filtering discarded inner blank lines. LF-only parsing,
exact section-boundary removal, empty-record rejection, and strict manifest
record grammar closed those paths. Direct parity also gained secure checks for
every expected distribution entry.

The final attack replaced a distributed prompt with a FIFO. The secure preflight
detected it, but semantic parsing reopened it through `Path.read_bytes()` and
could block. All Markdown, JSON, and TOML semantic reads now use the same
root-anchored `O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK` traversal with a 1 MiB
limit. FIFO and corrupt outside-symlink probes fail immediately without reading
the target. General, security, and QA critics re-reviewed exact tip `414b986`
and returned `ACCEPT` with no Critical, Major, or Minor findings.

The full gate also exposed that Plan 016's deliberately minimal ownership-test
fixture could not satisfy the new 57-file manifest. The plan was amended to
bring `test_install_sh.py` into scope: those link-ownership cases explicitly use
`--no-verify`, while complete-distribution tests prove bare-install success and
missing, corrupt, or symlinked-manifest abort before any link is created.

## Verification

- Direct parity passed with 14 skill pairs, 14 agent pairs, and 14 index entries.
- Manifest verification passed with exactly 57 deterministic checksum records;
  two consecutive generations were byte-identical and stdlib-only verification
  passed under `python3 -S`.
- Focused installer/parity suite: `131 passed in 12.46s`.
- Exact workflow harness bundle: `1120 passed, 1 deselected in 59.38s`.
- Full harness gate: `2132 passed, 43 skipped, 1 deselected in 68.95s`.
- Frontmatter, Exact API, and strict eval-suite-integrity validators passed.
- Python compilation, Bash syntax, ShellCheck, `git diff --check`, deterministic
  manifest checks, and file/function size checks passed. The validator is 791
  lines; no new function exceeds 50 lines.
- Every implementation/fix staged diff received a redacted Gitleaks scan; all
  scans reported no leaks.

## Negative space

The manifest is an unkeyed drift control, not release authentication. This plan
does not prove the hosted skills.sh listing or GitHub branch-protection state,
does not create a transactional snapshot against a same-authority concurrent
writer, and does not freeze installed symlink targets after verification.
Manifest hashing and redundant preflight hashing are not size-capped for large
regular files, although semantic parsing is capped at 1 MiB. `--no-verify` is a
deliberate local override, not a verified installation path.
