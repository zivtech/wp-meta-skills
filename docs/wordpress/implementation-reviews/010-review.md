Plan: 010
Plan base SHA: e1630a7a1736728b7903f491e69ecbf37ff429b3
Reviewed code tip SHA: 4666158dc359b47a0f393a9b09e543d48bebba65
Implementation/fix commits: d86c354068dee25aced308bb10bfba6c80a7345a 19ecf7a35312b28f1652c8f45f7ff27b537e1d08 5a7aa559121329c382646451fcf6c00cbe3c3f0a 8479beeca0a4a8d09ee9095457ca439b6423ce89 7231ea739205049ec9a9781f54571643bef2191c 088e9e0478af787490f8e0fea4b2bf7128bc69d2 ffa0a94a7e2c4ef267f652ed2bf9d88b8cb58134 2e3b5978533c5a969fa3acf1f2dde107e9b0416a 1807cb7d9a2afa8eb75602613538b6c63d3b6dec 5d49e9897b4da666396ecc989fbc9c575ea94eab a5e9ed5a52c566b7c7cf5d1ee24e60ac707104bd a6aae06e791b1ee73ce6f1be73b34cb96e8f6a9b 935bebbc460dc5f6b33be72072c00412aff4e3fb 4666158dc359b47a0f393a9b09e543d48bebba65
Verdict: ACCEPT

# Plan 010 Implementation Review

## Scope and architecture

The reviewed range makes block certification operate on the selected `block.json` graph and the generated PHP closure rather than an incomplete filename subset. It validates strict WordPress block metadata, closes declared metadata assets under bounded file, byte, edge, depth, PHP-count, and PHP-byte ceilings, distinguishes source and built authority, and binds the selected graph, synthesized wrapper, scanner input, proof, and artifact digest together.

PHP discovery is deliberately conservative. Authenticated deterministic `.php` aliases bring unusual executable suffixes such as `.phtml`, `.txt`, and extensionless PHP into PHPStan and PHPCS without losing the original finding path. Alias path, size, and hash mappings participate in the artifact digest. Blocks with no selected PHP explicitly skip PHP scanners and still pass the artifact gate; selected-root excluded namespaces remain excluded.

Synthesis and validation share `evals/harness/block_runtime_wrapper.py`, which emits the only accepted wrapper bytes. The validator rejects case changes, comment-separated tags, commented or string-literal tags, and any leading, trailing, or extra bytes. Parser and subprocess boundaries enforce deadlines, output limits, process-group cleanup, and bounded evidence. Runtime security evidence prioritizes enforced findings, security-relevant findings, and reviewed suppressions while retaining aggregate counts.

## Review history and dispositions

The first critic passes rejected zero-PHP handling, permissive wrapper whitespace, excluded-namespace leakage, extension-filtered PHP scanning, security evidence truncation, unbounded source/parser reads, and measurement semantics that did not prove the full certification path. Each defect received a focused regression and was re-reviewed.

The alias implementation then closed the unusual-suffix bypass while preserving ordinary plugin and theme scans. A final general review found that mixed-case and comment-separated PHP open tags could still diverge between synthesis and validation. Moving canonical generation into one shared helper removed the duplicate interpretation and made exact bytes the contract. Final general, security, and performance reviews accepted the exact reviewed tip with no unresolved Critical, Major, or Minor findings.

The first hosted exact-SHA attempt stopped before runtime because the reviewed mutable-tag index for WordPress had drifted. Live inspection showed that the Node, Python, and WordPress multi-platform indexes had changed while the reviewed AMD64 and ARM64 child digests remained unchanged. The plan was amended, only the three index identities and verification timestamp were refreshed, and the replacement exact-SHA run passed. This failure is part of the acceptance history; the later green run does not retroactively make the stale provenance acceptable.

## Verification

- Exact reviewed-tip local hermetic gate: `1633 passed, 3 skipped, 38 deselected in 57.79s`.
- Installer manifest verification, agent/skill frontmatter validation, WordPress Exact API validation, eval-suite integrity validation, Python compilation, workflow YAML parsing, and `git diff --check`: passed.
- All new files remain below 800 lines and all new functions remain below 50 lines.
- Real unusual-suffix baits proved that PHPStan and PHPCS scan `.phtml`, `.txt`, and extensionless PHP aliases and report the original paths.
- Every staged implementation/fix diff was scanned with Gitleaks; no credential leak was found.
- Exact hosted run: https://github.com/zivtech/wp-meta-skills/actions/runs/29433634156 at `4666158dc359b47a0f393a9b09e543d48bebba65`.
- Hosted `validate` job `87414638783`: success; 636 tests passed in 96.93 seconds, exact-commit verification passed, Plan 010 measurement passed, and artifact `8350515509` was uploaded.
- Hosted generated-runtime job `87414638819`: success; three Docker tests passed in 175.59 seconds, recorded runtime was 176 seconds, and post-cleanup disk delta was 4,910,014,464 bytes.
- Hosted feasibility job `87414639217`: success; 130 topology tests, 1,157 hermetic package tests with one skip and 16 deselections, and 35 live cases passed in 203.03 seconds. The legacy runtime and sandbox canary passed; post-cleanup disk delta was 4,893,519,872 bytes.
- Hosted aggregate measurement: pass with zero violations; 82.293689 seconds certification time, 82.92644 seconds wall time, 120,483,840-byte maximum observed RSS, 68 bounded invocations, 128 aliases totaling 16 MiB, and complete cleanup.
- Hosted max-member measurement: pass with zero violations; 3.14006 seconds certification time, 3.223268 seconds wall time, 120,569,856-byte maximum observed RSS, five bounded invocations, two aliases totaling 128 bytes, and complete cleanup.

## Negative space

This packet does not prove JavaScript import reachability, dynamically generated or evaluated PHP, short-tag execution, authenticated provider behavior, or browser/runtime behavior beyond the inherited Plan 009 adversarial gates. Conservative PHP classification is a certification boundary, not a claim that every selected file is executable in WordPress.

The measurements count top-level bounded invocations and report the maximum observed parent-or-child RSS, not a process-tree memory sum. They prove the committed fixtures remain inside reviewed ceilings on the exact hosted lane; they do not establish production throughput, concurrent workload capacity, or release readiness. Plan 011 still owns executor-specific repair certification.
