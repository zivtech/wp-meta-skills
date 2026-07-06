# Focused Fixture: Cutover, Rollback, And Reconciliation

Plan the launch runbook for a WordPress migration after an initial dry-run
import. Current facts:

- Dry-run import created 4,730 of 4,800 expected articles.
- 61 media files failed because source paths were missing.
- Staff profile counts match, but 37 profiles have empty office-location data.
- Editors need a one-week content freeze except for urgent announcements.
- The legacy site will remain read-only for 30 days after launch.
- Hosting backups exist, but no rollback trigger, delta migration process, or
  post-launch reconciliation owner has been named.

## Expected Planning Focus

- Define freeze window, delta migration, launch checklist, rollback checkpoint,
  rollback trigger, and ownership.
- Require reconciliation across source counts, WordPress counts, media counts,
  failed import queues, sample records, checksums or stable IDs, and editorial
  QA.
- Include dry-run reruns and launch rehearsal before production cutover.
- Name relevant WordPress/WP-CLI surfaces such as `wp post list`, `wp media
  import`, `wp search-replace`, `wp option get`, and import-log queries where
  applicable.
- Preserve the unresolved media failures and empty field data as release risks,
  not "cleanup later" unless accepted by owners.

## Required Boundaries

Do not claim launch readiness without rollback and reconciliation signoff. Do
not treat a one-time dry run as proof that the migration is rerunnable.
