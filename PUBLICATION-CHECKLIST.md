# Publication Checklist

Use this checklist before publishing or tagging `wp-meta-skills`.

Public-release evidence should be recorded in the public repository issue
tracker after the clean-root import.

## Review Packet

Public-release review should inspect the standalone repository copies of:

- `README.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `CUTOVER.md`
- `SECURITY.md`
- `EVIDENCE.md`
- `PROVENANCE.md`
- `PUBLICATION-CHECKLIST.md`

Approval must explicitly cover metadata accuracy, security reporting,
provenance/history strategy, evidence boundaries, selected public evidence
files, and whether remaining high-risk eval maturation gaps are accepted as
post-release work.

## Required Gates

- [ ] Maintainer review approves `README.md`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `CUTOVER.md`, `SECURITY.md`, `EVIDENCE.md`,
  `PROVENANCE.md`, and `PUBLICATION-CHECKLIST.md` for public release.
- [ ] Public reporting path in `SECURITY.md` is replaced with the real GitHub
  Security Advisory process or public contact.
- [ ] Package is rebuilt from the source repo with
  `scripts/build-wp-meta-skills-package.py`.
- [x] Standalone repository tree exists from a clean import of the generated
  package.
- [ ] `./install.sh --verify` passes inside the generated package.
- [ ] `scripts/validate-agent-frontmatter.py` passes inside the generated
  package, including agent and skill YAML frontmatter.
- [ ] `scripts/validate-wordpress-exact-api-contract.py` passes inside the
  generated package.
- [x] Root `skills.sh.json` is present and valid JSON for the future skills.sh
  repository page.
- [ ] `DISABLE_TELEMETRY=1 npx -y skills add ./ --list` reports all 14
  WordPress skills, including `wordpress-security-critic`, inside the generated
  package.
- [ ] Strict selected WordPress eval-suite validation passes inside the
  generated package.
- [ ] The WordPress harness pytest bundle passes inside the generated package.
- [ ] Scoped secret scan finds no committed secrets, credentials, private URLs,
  or real client data.
- [ ] Selected evidence files are present under
  `evidence/wordpress-skill-candidate-eval/`.
- [ ] Full result archives are either published as public artifacts or kept
  explicitly out of scope in `EVIDENCE.md`.
- [ ] Public GitHub visibility is approved for the standalone repository using
  the history strategy in `PROVENANCE.md`.
- [ ] Live GitHub Actions validation passes on the clean-root public
  repository.
- [ ] Live GitHub Actions validation passes after public-release review changes.
- [ ] Release tag is created only after the live CI run passes.

## Post-Public skills.sh Registration

Do not mark this complete while the repository is still private or before the
release gates above pass.

- [ ] After the visibility flip, run `npx skills add zivtech/wp-meta-skills`
  without `DISABLE_TELEMETRY=1` so skills.sh can see the repository through the
  CLI's anonymous aggregate install telemetry.
- [ ] Verify `https://skills.sh/zivtech/wp-meta-skills` resolves after the
  skills.sh cache refreshes and shows the 14-skill WordPress collection.
- [ ] Verify the page uses the root `skills.sh.json` grouping for Planning,
  Execution, and Review.
- [ ] Add the README badge only after the skills.sh page resolves:
  `[![skills.sh](https://skills.sh/b/zivtech/wp-meta-skills)](https://skills.sh/zivtech/wp-meta-skills)`.
- [ ] Comment on issue #1 with the verified skills.sh URL and final install
  command evidence.

## Non-Release Gates

These are important but should not block the first public draft unless the
release claims depend on them:

- Long-run variance reduction across repeated current-baseline generations.
- Credentialed OpenAI, Anthropic, Google, or other third-party AI-provider
  behavior.
- Production readiness of generated plugins, blocks, themes, or migrations.

If any release copy claims one of these, move it back into the required gates
and verify it before publication.
