**Scope**

Plan is not launch-ready yet. The dry run exposed unresolved migration gaps and missing operational controls:

- 4,730 / 4,800 articles imported, leaving 70 missing articles.
- 61 media failures remain unresolved due to missing source paths.
- 37 staff profiles have empty office-location data despite matching profile counts.
- No rollback trigger, delta migration process, or reconciliation owner has been named.
- A one-week editorial freeze is required, with a defined exception path for urgent announcements.
- Legacy site remains read-only for 30 days after launch, which helps validation but does not replace rollback planning.

The runbook should cover freeze, rerunnable imports, delta capture, launch rehearsal, cutover, rollback, and post-launch reconciliation.

**WordPress-Specific Decisions**

- Define a one-week content freeze start/end time, including who can approve urgent announcements.
- Establish a delta migration process for content changed after the dry run and during the freeze exception window.
- Require at least one dry-run rerun after fixes to prove the migration is repeatable.
- Run a launch rehearsal using the same steps, ordering, credentials, and validation checks intended for production.
- Use WordPress/WP-CLI surfaces for validation, not manual spot checks alone:
  - `wp post list` for article and staff profile counts.
  - `wp media import` or equivalent media importer logging for failed media retries.
  - `wp search-replace` only with a reviewed dry-run plan before production URL changes.
  - `wp option get` for site URL, home URL, active theme/plugin settings, and migration-relevant options.
  - Import-log queries for failed queues, skipped records, duplicate stable IDs, and retry status.
- Preserve stable IDs or source IDs in WordPress metadata so imported records can be reconciled against the legacy source.
- Treat the 61 media failures and 37 empty office-location fields as release risks unless explicitly accepted by named owners.

**Risks**

- Missing rollback trigger means the team may discover launch failure without a shared decision point.
- Hosting backups exist, but backups alone are not a rollback plan unless restore scope, timing, validation, and authority are defined.
- The 70 missing articles may indicate source filtering, importer failure, duplicate handling, or unstable rerun behavior.
- The failed media paths may create broken article bodies, missing featured images, or inaccessible files.
- Empty office-location data may be a data mapping issue, not just incomplete content.
- A one-time dry run does not prove the migration is rerunnable.
- Urgent announcements during the freeze can create content drift unless captured in a delta queue.
- Legacy read-only access for 30 days supports reconciliation, but does not guarantee recovery if WordPress production data diverges.

**Verification**

Before cutover, require signoff on:

- Source article count vs WordPress article count.
- Staff profile source count vs WordPress profile count.
- Media source count vs WordPress media library count.
- Failed import queue count equals zero, or every remaining failure has owner-approved disposition.
- Sample record QA across articles, media, staff profiles, taxonomy, redirects, authorship, dates, and office-location fields.
- Stable ID or checksum comparison for representative records.
- URL/domain checks after reviewed `wp search-replace` procedure.
- Import logs reviewed for skipped, duplicated, failed, and retried records.
- Editorial QA completed by named owners.
- Rollback checkpoint completed immediately before cutover.
- Rollback trigger and decision owner documented.
- Post-launch reconciliation owner assigned for the 30-day read-only legacy window.

**Open Questions**

- Who owns migration reconciliation after launch?
- What exact conditions trigger rollback?
- What is the maximum acceptable article/media/profile data loss at launch?
- Are the 61 missing media files recoverable from another source?
- Are the 37 empty office-location fields source-data gaps or mapping failures?
- Who approves urgent announcements during the freeze?
- How will urgent announcement deltas be captured and migrated?
- What is the target launch date and freeze window?
- What backup restore time has hosting committed to?
- Who signs off that reconciliation is complete?

Conclusion: this task should be planned as a controlled cutover with rollback and reconciliation gates. It should not be treated as ready for launch until rerun evidence, data-risk disposition, rollback criteria, and named ownership are in place.