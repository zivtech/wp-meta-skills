Plan: 016
Plan base SHA: 3bdfe5a16ce3dfc7a9483eecdacfde94967d5cf3
Reviewed code tip SHA: 246498ec1bb845b4b3faead02574192c2c5fc754
Implementation/fix commits: 41220b88cb643f771d3f09f106d5d2d269aba749 7af030ab821bba2de59e6a2271dd02ff418fd768 e18bad1ca5d571192a2ce5268004ba660a89031e 246498ec1bb845b4b3faead02574192c2c5fc754
Verdict: ACCEPT

# Plan 016 Implementation Review

## Scope and ownership boundary

The reviewed range turns `install.sh` into a standalone `wp-meta-skills`
installer. It no longer discovers, verifies, installs, or removes entries from
named sibling repositories. The three existing skill destinations and Claude
agent destination remain unchanged, but installation and removal now share a
single canonical ownership rule: an existing link is managed only when its raw
target exists and resolves on a component boundary inside the physical checkout
that owns the installer.

Discovery is exact-depth and NUL-delimited. Every source is independently
canonicalized immediately before linking, public names are restricted to the
current safe filename vocabulary, and symlinked installer entrypoints resolve
back to the physical checkout through a bounded hop walk. Ambiguous
control-bearing entrypoint, HOME, source, and raw-link paths fail closed. Path
capture preserves terminal bytes long enough to reject them instead of letting
shell command substitution silently change identity.

Normal installation refreshes only current-checkout links and preserves
unrelated or dangling symlinks plus every regular file and directory.
`--force` is install-only and may replace an unrelated safe symlink after
printing its destination and shell-escaped prior raw target; it cannot replace
a regular file or directory. Removal has no force mode and deletes only links
that pass the ownership oracle.

## Test-first and review dispositions

The RED commit established 22 hermetic cases; 17 failed against the prior
installer, reproducing sibling discovery/removal, prefix containment, relative
target resolution, unrelated-link overwrite, regular-file replacement, and
missing recovery evidence. The final suite contains 31 tests and uses only
synthetic source trees and HOME values. Git fixtures disable system/global
configuration and use an empty template. The recovery case sends SIGTERM after
the first forced link, round-trips a target containing spaces and `$`, restores
it, and proves an unrelated destination remains untouched.

QA review found that post-increment arithmetic under `set -e` passed on macOS
Bash 3.2 but exited after the first link on Linux Bash 5.2. Every affected
counter was changed to assignment arithmetic and a static regression plus an
independent Debian Bash 5.2 install/remove replay were added.

Security review then demonstrated a newline-delimited discovery escape that
could register an external skill despite a passing manifest. Exact-depth
NUL-delimited discovery, source containment, and skill/agent control-path tests
closed it. Further review found that a symlink launcher could redefine the
checkout and that unescaped paths could corrupt operational evidence; physical
entrypoint resolution and one-line `%q` output/log fields closed those paths.

The final security pass identified command-substitution loss of terminal
newlines. That loss could select a stripped sibling checkout or misclassify an
unrelated raw link as owned. Central byte-preserving `readlink -n`, `pwd`, and
`realpath` capture plus fail-closed control handling now preserve such links
through normal install, removal, and force. General, security, and QA critics
re-reviewed the exact final tip and returned `ACCEPT` with no remaining
Critical, Major, or Minor findings.

## Verification

- `bash -n install.sh`, ShellCheck, the stale companion-name scan, manifest
  verification, `git diff --check`, and Python compilation passed.
- Focused installer suite: `31 passed in 2.84s`.
- Exact workflow harness bundle: `1020 passed, 1 deselected in 48.85s`.
- Full harness gate: `2032 passed, 43 skipped, 1 deselected in 55.92s`.
- Debian Bash 5.2 installed 56 links through a symlink launcher, removed all 56,
  and left zero link destinations behind.
- `install.sh` is 525 lines and the installer test module is 470 lines. No new
  function exceeds 50 lines.
- Every implementation/fix staged diff received a redacted Gitleaks scan; all
  four scans reported no leaks.

## Negative space

This plan proves current-checkout discovery, source provenance, destination
ownership, and recovery behavior at invocation time. It does not expand or
validate manifest inventory coverage; Plan 017 owns that distribution surface.
It does not install companion repositories or provide a multi-repo
orchestrator. It does not replace regular files/directories under any option.

The shell sequence does not claim atomic protection against a concurrent
same-user process that can already mutate the destination directory between
inspection and unlink. Forced recovery output is shell-escaped evidence of the
raw target, not an automated rollback database. A control-bearing source or
target is preserved or rejected rather than normalized into a different path.
