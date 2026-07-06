# Cutover Plan

This plan defines how `wp-meta-skills` becomes the source of truth after
release approval. It is intentionally separate from validation evidence:
validation proves the package works, while cutover controls ownership and
future change flow.

## Preconditions

Do not cut over until all of these are true:

- Monorepo recovery PR #11 is approved and merged into `main` with
  `validate-package` passing on the merge candidate.
- Standalone approval issue #1 approves public visibility, metadata,
  security reporting, evidence boundaries, and history/provenance strategy.
- `SECURITY.md` contains the real public reporting process or contact.
- The standalone repository has a live passing Actions run after any
  release-review edits.
- No release copy claims credentialed third-party AI-provider proof,
  production readiness of generated artifacts, long-run variance reduction, or
  completed high-risk eval maturation unless those claims have current
  evidence.

## Cutover Sequence

1. Freeze WordPress skill changes in `zivtech-meta-skills` except for the final
   package-generation and pointer-update commits.
2. Rebuild the standalone package from the approved monorepo merge commit:

   ```bash
   python3 scripts/build-wp-meta-skills-package.py \
     --output /tmp/wp-meta-skills-release-candidate \
     --force \
     --generate-manifest
   ```

3. Sync the generated package into `zivtech/wp-meta-skills` and run the
   standalone validation bundle locally.
4. Push the standalone release-candidate commit and wait for live standalone
   Actions to pass.
5. Apply only approved metadata, evidence, security, or provenance edits needed
   for public release; after each edit, rerun local validation and live Actions.
6. Change repository visibility only after issue #1 records owner approval.
7. Create a release tag only after the post-review live CI run passes.
8. Update `zivtech-meta-skills` documentation so future WordPress skill work
   points to `zivtech/wp-meta-skills` as the source of truth.

## Post-Cutover Rule

After cutover, new WordPress skill work should start in `zivtech/wp-meta-skills`.
The monorepo may keep historical handoff notes or a pointer, but it should not
accept new WordPress feature work unless the change is explicitly a
back-reference, archive update, or migration cleanup.

## Rollback

If public release is blocked after the standalone repository is made public,
do not delete history to hide the attempt. Open a follow-up issue, keep the
latest passing private/public validation link attached to the approval issue,
and either narrow release claims or revert the specific release-facing edit that
introduced the blocker.

## Non-Claims

This cutover plan does not itself approve public release, repo visibility,
release tagging, or evidence sufficiency. Those approvals remain in the
standalone approval issue until maintainers explicitly close them.
