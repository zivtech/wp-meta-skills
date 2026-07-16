Plan: 018
Plan base SHA: 848c1c7dd4f81bd500c4905461124fcb3ec2b04c
Reviewed code tip SHA: 1a602d8c04cdb5a14217b12bdadfb7f7d07ee63e
Implementation/fix commits: ca729e54889fee28fe486d29cba49a47143424ec 9a7f764967aaa52f38f26439f43252d0bc7a5808 b42f8a1a922340994f054fc4545c6057b57a048a 1a602d8c04cdb5a14217b12bdadfb7f7d07ee63e
Verdict: ACCEPT

# Plan 018 Implementation Review

## Locked validation and collection contract

The reviewed range makes `uv.lock` the canonical Python validation lock for
Python 3.13.9. The `test` extra names exact pytest 9.1.0 and PyYAML 6.0.3
requirements, `requirements-validation.txt` is a hash-pinned export and tested
pip escape hatch, and pytest configuration and marker registration now live in
`pyproject.toml`. Canonical commands select the test extra and execute pytest
through the selected interpreter rather than an ambient console script.

Directory-wide collection is partitioned into four disjoint sets: general,
package-sandbox Docker, generated-runtime Docker, and authorized live-provider.
The collection oracle proves that their union is the complete corpus and that
the two Docker shards exactly partition `docker_boundary`. Real PHP API and
security gates remain in the general set after the pinned PHP toolchain is
installed. The ordinary workflow never selects live-provider tests.

Actions bootstrap Python from `.python-version` and uv 0.9.27 from a full
commit pin, check the lock, and sync it before validation. All retained action
uses are full commit pins. The two no-secrets jobs retain credential-free
checkout, empty token inputs, disabled uv cache, separately budgeted Docker
shards, explicit disk admission, and terminal resource cleanup. Documentation
distinguishes the validation lock from the separately owned `anthropic` and
`gepa` operator lanes.

## Hosted Linux cleanup amendment

The first exact-SHA hosted run collected the newly directory-wide general
corpus and exposed a real cleanup ownership defect in the Plugin Check runtime:
path identity alone could accept a removed and externally replaced directory
when Linux immediately reused the device/inode tuple. The plan was amended
before implementation. Production now creates a mode-0600 ownership sentinel,
records exact directory and sentinel identity plus a 16-byte random nonce, and
keeps the original content directory open as parent-shell descriptor 9 across
Plugin Check and cleanup. Linux cleanup is rooted at `/proc/self/fd/9`, renames
the owned directory to a nonce-derived quarantine path, permits only the exact
`object-cache.php` and `.wp-plugin-check-owner` unlink basenames, and proves the
anchored directory link state after `rmdir()`.

Deterministic synchronization tests exercise pre/post-rename disposition,
file and directory substitution, symlink and hardlink rejection, final
absence, and original-unlinked-first races. Test hooks and the Darwin
direct-path structural branch do not appear in production payloads. A general
critic then reproduced a stable-FIFO liveness defect because source and target
paths were opened before their already-collected type was validated. Regular,
non-symlink and target-link-count checks now gate `fopen()`; retained post-open
`fstat()` and exact path/handle identity checks remain. Both stable FIFO cases
return cleanup exit 43 promptly.

The next hosted Linux run exposed an allocator-dependent test assumption:
unlinking the sentinel before copying it back allowed ext4 to reuse the freed
inode, making all recorded fields and the readable nonce match. The repaired
test allocates and proves a distinct copy while the original inode is still
live, then renames that copy over the pathname. This tests distinct-copy
rejection without claiming inode identity is a provenance capability.

General, security, and performance critics re-reviewed exact final tip
`1a602d8` and returned `ACCEPT` with no unresolved Critical, Major, or Minor
findings.

## Verification

- Clean locked local environment: Python 3.13.9, pytest 9.1.0, and PyYAML
  6.0.3; `uv lock --check`, locked sync, and dependency checks passed.
- Focused Plugin Check cleanup suite: `38 passed` on macOS and `38 passed` in a
  clean Python 3.13.14 Linux container with hash-installed validation
  requirements and PHP CLI.
- Local locked general partition: `2179 passed, 3 skipped, 41 deselected in
  67.72s`.
- Fresh hash-installed pip fallback general partition: `2179 passed, 3
  skipped, 41 deselected in 68.12s`.
- Exact-tip hosted run
  [29467671308](https://github.com/zivtech/wp-meta-skills/actions/runs/29467671308)
  succeeded in all three jobs. The general job passed `2182` tests with `41`
  deselections in 159.17 seconds, completed Plan 010 measurement, and uploaded
  artifact `8363610812` with SHA-256
  `5897bab07daab04b14a2ed12c4cfab4e9ea590ecfd087983913870caf99f91a8`.
- The hosted package-sandbox job passed its 286-test topology preflight, its
  `1161 passed, 1 skipped, 16 deselected` hermetic bundle, and all 35 Docker
  nodes. The admitted runner began with 92,848,054,272 free bytes; the canary
  took 189 seconds and post-cleanup disk delta was 4,893,503,488 bytes.
- The hosted generated-runtime job passed all 5 Docker nodes in 456.26 seconds;
  post-cleanup disk delta was 4,920,029,184 bytes.
- Lock/export parity, collection set equality and disjointness, workflow command
  policy, full action pins, Python compilation, file/function size, and
  `git diff --check` gates passed. Every staged implementation/fix diff had a
  redacted Gitleaks scan with no new leak.

## Failed-run evidence and disposition

Run `29465126438` was retained as the evidence that exposed external directory
replacement; its Docker jobs succeeded while general collection correctly
failed. Run `29467239602` retained two distinct findings: the generated-runtime
job succeeded, the sandbox's 35 Docker nodes passed before an undersized runner
with only 15,058,157,568 free bytes correctly failed the 20 GiB admission
floor, and the general job exposed the inode-reuse test assumption. The fresh
exact-tip run used a runner with adequate disk and passed without lowering any
admission or cleanup threshold.

## Negative space

The validation lock covers this repository's validation surface; it does not
install or make the `anthropic` or `gepa` operator lanes reproducible. The hash-
pinned pip file is a tested fallback, not a second source of dependency truth.
Local Darwin and local pip-fallback results do not prove Linux procfs descriptor
or directory-link semantics; the exact-tip hosted run is that proof.

The cleanup is not a general race-free pathname deletion primitive. A same-UID
process can still act between setup and descriptor acquisition or between a
regular-file `lstat()` and PHP's pathname `fopen()`, causing bounded denial
under the outer runtime deadline. A pre-cleanup unlink/recreation may receive
the same filesystem inode, and an original-unlinked-first replacement after a
verified handle is open may be the exact-name entry subsequently removed.
Successful cleanup therefore does not prove provenance of the removed
pathname. It proves only the bounded contract: the retained original directory
anchor, two exact basenames, no symlink-target traversal or broad delete, final
absence when successful, and terminal disposable-container teardown as the
authoritative boundary.
