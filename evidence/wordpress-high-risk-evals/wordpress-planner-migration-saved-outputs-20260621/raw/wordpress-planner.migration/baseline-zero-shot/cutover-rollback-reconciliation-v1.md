This migration is **not launch-ready** yet. The dry run exposed unresolved content, media, and ownership gaps, and the current plan lacks rollback triggers, delta migration, and reconciliation signoff. A launch runbook should treat those as gating risks, not post-launch cleanup.

**Launch Runbook Scope**

Freeze window:
- Set a one-week editorial freeze before production cutover.
- Allow only urgent announcements through a named exception process.
- Track every approved freeze-period change in a delta log with content ID, URL, editor, timestamp, and change type.
- Legacy site remains read-only for 30 days after launch.

Delta migration:
- Define a repeatable delta import for all approved changes made after the dry run.
- Include articles, media, staff profiles, redirects, taxonomy changes, menus, and urgent announcements.
- Validate delta selection by stable IDs, modified timestamps, or import mapping tables.
- Do not rely on manual editor memory.

Dry-run reruns and rehearsal:
- Rerun the migration after fixing known importer issues.
- Confirm the import is rerunnable from a clean target environment.
- Run a full launch rehearsal using the same commands, timing, credentials, logs, and rollback checkpoint expected for production.
- Rehearsal must include `wp search-replace`, media handling, cache/index rebuilds, redirect validation, and editorial QA.

**Known Release Risks**

Article gap:
- Dry run created 4,730 of 4,800 expected articles.
- The missing 70 articles need classification: skipped intentionally, failed import, duplicate suppression, unpublished legacy content, or mapping error.
- Launch cannot be signed off until this gap is reconciled or explicitly accepted by the migration owner and editorial owner.

Media failures:
- 61 media files failed because source paths were missing.
- These remain launch risks unless owners accept broken/missing media.
- Use import-log queries plus source-file audits to identify affected posts and whether replacement assets exist.
- Use `wp media import` only after missing source paths are corrected or replacements are approved.

Staff profile data:
- Staff profile counts match, but 37 profiles have empty office-location data.
- This is not resolved by count parity.
- Reconcile against stable staff IDs and source field values.
- Editorial or HR/content owner must decide whether empty office-location values are acceptable at launch.

**Required Reconciliation**

Reconciliation should compare:

- Source article count vs WordPress article count.
- Source media count vs WordPress attachment count.
- Failed import queues and importer logs.
- Staff profile counts and field-level completeness.
- Sample records across content types.
- Stable IDs or source IDs stored in post meta.
- URL mappings and redirects.
- Checksums where practical for body fields or serialized source payloads.
- Editorial QA findings.

Useful WordPress/WP-CLI surfaces:
- `wp post list --post_type=post --format=count`
- `wp post list --post_type=attachment --format=count`
- `wp post meta get <id> <source_id_meta_key>`
- `wp media import <path>`
- `wp search-replace <old-domain> <new-domain> --dry-run`
- `wp option get home`
- `wp option get siteurl`
- Import-log database queries for failed rows, skipped rows, source IDs, and error messages.

**Launch Checklist**

Before cutover:
- Freeze window approved and communicated.
- Exception process active for urgent announcements.
- Delta migration script/process documented and rehearsed.
- Missing 70 articles reconciled.
- 61 media failures resolved or formally accepted.
- 37 empty office-location profiles resolved or formally accepted.
- Full dry-run rerun completed successfully.
- Launch rehearsal completed.
- Backup restore tested, not merely confirmed to exist.
- Rollback owner, migration owner, editorial QA owner, infrastructure owner, and reconciliation owner named.
- Go/no-go meeting held with documented signoff.

During cutover:
- Put legacy site into read-only mode.
- Take final backup/snapshot of WordPress target.
- Run final delta migration.
- Run `wp search-replace` for production URLs after a dry run.
- Confirm `home` and `siteurl` via `wp option get`.
- Clear caches and rebuild indexes/search if applicable.
- Validate redirects, canonical URLs, media rendering, forms, logins, and priority templates.
- Run reconciliation checks before DNS or traffic switch.

After cutover:
- Monitor errors, redirects, search, media, and editorial reports.
- Keep legacy read-only for 30 days.
- Assign daily reconciliation review until all known queues are closed or accepted.
- Document any post-launch fixes against source IDs, not just URLs.

**Rollback Checkpoint And Trigger**

Rollback checkpoint:
- Final pre-cutover database backup.
- Final uploaded files backup.
- Confirmed restore procedure.
- DNS/CDN rollback steps.
- Legacy read-only site confirmed available.
- Named person authorized to trigger rollback.

Rollback triggers should be explicit, for example:
- Article reconciliation gap exceeds accepted threshold.
- Critical templates fail for major content types.
- Production URLs or redirects break at scale.
- Media failures affect high-priority pages.
- Search, login, forms, or editorial access fail.
- Delta migration produces unexplained skips or duplicate content.
- Reconciliation owner cannot sign off.

Do not proceed to launch unless rollback and reconciliation owners have signed off. A one-time dry run proves only that one import attempt partially worked; it does not prove the migration is repeatable, complete, or safe to cut over.