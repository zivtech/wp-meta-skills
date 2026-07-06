# Standalone Extraction Readiness - 2026-06-21

## Decision

The working standalone release name is `wp-meta-skills`.

The first public package should contain the WordPress skill suite and the
WordPress-specific validation harness needed to prove it still works outside
`zivtech-meta-skills`. It should not carry unrelated Zivtech skill families.

## Extraction Scope

Include:

- `.claude/agents/` from `wordpress-skills/.claude/agents/`.
- `.claude/skills/` from `wordpress-skills/.claude/skills/`.
- `README.md`, `AGENTS.md`, and `CLAUDE.md` from `wordpress-skills/`.
- WordPress docs under `docs/wordpress/`.
- A pruned `evals/harness/` subset because WordPress validations depend on
  local harness helpers.
- `evals/suites/wordpress-*`.
- `evals/suites/QUALITY_GAPS.md` if present.
- `scripts/validate-agent-frontmatter.py`.
- `scripts/validate-wordpress-exact-api-contract.py`.
- `scripts/validate-eval-suite-integrity.py`.
- `install.sh` plus generated `MANIFEST.sha256`.
- Standalone root metadata from `wordpress-skills/standalone/`:
  `.gitignore`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CUTOVER.md`,
  `SECURITY.md`, `EVIDENCE.md`, `PROVENANCE.md`, and
  `PUBLICATION-CHECKLIST.md`.
- Curated lightweight evidence bundle under
  `evidence/wordpress-skill-candidate-eval/`.

Exclude:

- Non-WordPress skill packages.
- Non-WordPress eval suites.
- Historical result archives unless a release needs a curated evidence bundle.
- Local tool state, caches, and unpublished secrets or credentials.

## Dry-Run Package

Dry-run package path:

```bash
/tmp/wp-meta-skills-extraction-20260621-233205
```

The package was built as a clean filesystem extraction, with the WordPress
skills moved to root `.claude/agents` and `.claude/skills` so Claude and Codex
skill discovery do not depend on the old monorepo path.

The first validation attempt exposed a real extraction bug: the exact API
contract validator and candidate/pairwise pilot harness still assumed
`wordpress-skills/.claude`. Those paths were changed to prefer the monorepo
layout when present and fall back to root `.claude` in an extracted package.

## Reproducible Pruned Package

The current release-prep path is:

```bash
python3 scripts/build-wp-meta-skills-package.py \
  --output /tmp/wp-meta-skills-pruned-20260621 \
  --force \
  --generate-manifest
```

Result:

```text
Generating MANIFEST.sha256...
  Generated checksums for 28 files.
Built wp-meta-skills package at <local scratch path omitted>
```

The pruned package contains 346 files, is 2.3M on disk, and includes 18 harness
files plus 12 harness test files. This removes unrelated math/design harness
utilities from the standalone package while keeping the WordPress validation
bundle runnable.

The package root includes:

- `LICENSE` with Apache-2.0 text, matching the root README's declared license;
- `CHANGELOG.md` with an unreleased V1 summary and publication boundary;
- `CUTOVER.md` with the source-of-truth transition plan after public release
  approval;
- `SECURITY.md` with current private-reporting guidance and post-publication
  update notes;
- `CONTRIBUTING.md` with validation, exact-API, and provenance expectations.
- `EVIDENCE.md` with the selected proof surfaces, source result paths, and
  non-claims.
- `PROVENANCE.md` with the source mapping and first-public-draft history
  strategy.
- `PUBLICATION-CHECKLIST.md` with the required gates before public tag or
  release.
- `.gitignore` to keep local Python, pytest, editor, package-install, and
  scratch-state files out of clean-import commits.
- `.github/workflows/validate.yml` with the standalone validation bundle.
- `evidence/wordpress-skill-candidate-eval/` with six selected runtime proof
  scorecards and six matching runtime JSON files.

## Validation Evidence

After generating the pruned package, these commands passed inside the extracted
package:

```bash
./install.sh --generate-manifest
./install.sh --verify
```

Result:

```text
Verifying file integrity against MANIFEST.sha256...
  All files match manifest checksums.
```

```bash
python3 scripts/validate-agent-frontmatter.py
python3 scripts/validate-wordpress-exact-api-contract.py
```

Result:

```text
Agent frontmatter validation passed (14 agents).
WordPress Exact API contract validation passed.
```

```bash
python3 scripts/validate-eval-suite-integrity.py \
  --strict-suites wordpress-plugin-executor \
  --strict-suites wordpress-block-executor \
  --strict-suites wordpress-skill-candidate-eval \
  --allow-known-gaps
```

Result:

```text
Eval suite integrity validation passed.
```

```bash
python3 -m pytest \
  evals/harness/tests/test_invoke_claude_command.py \
  evals/harness/tests/test_wordpress_runtime_smoke.py \
  evals/harness/tests/test_wordpress_artifact_oracle.py \
  evals/harness/tests/test_wordpress_executor_packet_oracle.py \
  evals/harness/tests/test_wordpress_exact_api_contract.py \
  evals/harness/tests/test_wordpress_executor_artifact_certifier.py \
  evals/harness/tests/test_wordpress_packet_materializer.py \
  evals/harness/tests/test_wordpress_skill_output_contract.py \
  evals/harness/tests/test_answer_key_score.py \
  evals/harness/tests/test_pairwise_pilot.py \
  evals/harness/tests/test_wordpress_candidate_pilot_generation.py \
  -q
```

Result:

```text
125 passed
```

Scoped secret scans found no real credentials. The only literal-assignment
matches were copies of the documented placeholder:

```text
evals/harness/README.md:701:export ANTHROPIC_API_KEY="<anthropic-api-key>"
```

Broader keyword scanning also returned expected references to local test
password plumbing, API-key environment variable names, validator code that
detects hardcoded secrets, and prompt text instructing agents not to include
secrets.

## Publication Boundary

This proves the current WordPress package shape can be extracted and validated
outside the monorepo.

## Standalone Staging

The first standalone clean import was validated in a staging archive repository
before the public clean-root import. The public release should not expose the
staging archive repository history.

- Branch: `main`
- Initial clean-import commit:
  `8798b2e11ba5335ca5452be8bb01ddd9b09a0d03`
- Import package: local scratch path omitted from public docs.

The live `Validate wp-meta-skills` workflow passed in staging. The job verified
the manifest, validated agent frontmatter and WordPress API contracts, validated
selected WordPress eval suites, and ran the WordPress harness tests.

The public release should use a fresh clean-root import of the validated tree,
then rerun public Actions before any release tag or announcement.

## History Extraction Probe

Committed `wordpress-skills` history is mechanically splittable with:

```bash
git subtree split --prefix=wordpress-skills HEAD
```

Result:

```text
ef7e00b2f848ee57f2f008714855fe440b78d892
```

Boundary: this split was run against committed `HEAD`. It does not include the
current uncommitted WordPress release-prep, harness, runtime proof, package
builder, metadata, or result-archive changes. It is also not sufficient as the
final package history strategy by itself, because the generated standalone
package pulls root-level `evals/harness`, `scripts`, `install.sh`, and selected
evidence files in addition to `wordpress-skills`.

Current recommended history strategy for the first public draft is a clean
import of the generated package with `PROVENANCE.md` preserved. A local
clean-import rehearsal is documented at
`wordpress-skills/docs/public-repo-rehearsal-2026-06-21.md`. If maintainers
require history preservation, use a post-commit path-aware filtering strategy
over every source area named in `PROVENANCE.md`, then validate the resulting
repository with the same package gates.

It does not prove:

- public GitHub visibility or release publication;
- public owner review of the standalone metadata;
- maintainer approval of the documented clean-import history strategy, or a
  verified path-aware history-preserving alternative;
- published full result archives or public URLs for the curated evidence
  manifest;
- credentialed third-party AI provider behavior.
- pushed source commits for the local recovery work.

## Next Publication Steps

1. Review the standalone metadata files for public owner approval.
2. Ask maintainers to approve the documented clean-import history strategy for
   the first public draft, or replace it with a verified path-aware
   history-preserving import.
3. Publish the clean-root public repository and record validation evidence in
   the public issue tracker.
4. Publish selected result directories or convert evidence paths to public URLs
   only if a later release expands evidence scope.
5. Re-run or confirm standalone CI after any post-review changes.
6. Tag or announce the public release only after the secret/provenance scan
   passes and owner approval is explicit.
