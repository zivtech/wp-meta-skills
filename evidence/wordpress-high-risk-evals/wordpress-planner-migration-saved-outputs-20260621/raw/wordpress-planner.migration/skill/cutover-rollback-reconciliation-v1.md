## Migration Scope

**Type:** Post-dry-run launch runbook — cutover, delta migration, rollback, and reconciliation.

**Focal surfaces:** Article content (4,800 expected), media library (61 known failures), staff profiles (37 with empty `office_location`), DNS cutover, content freeze window, legacy read-only period.

**Current launch-readiness status: NOT READY.** Three unresolved risks exist (70 missing articles, 61 media failures, 37 empty fields), no rollback trigger or owner is named, and one dry run is not proof the import script is idempotent or rerunnable. This runbook is the remediation path, not a green light.

---

## Current-State Evidence

| Signal | Observed | Expected | Gap | Status |
|---|---|---|---|---|
| Articles imported | 4,730 | 4,800 | 70 missing | **Unresolved risk** |
| Media files imported | Unknown success count | Unknown total | 61 path failures | **Unresolved risk** |
| Staff profiles imported | Count match | Count match | 37 empty `office_location` | **Unresolved risk** |
| Import idempotency | Not tested | Required | Not verified by one dry run | **Unresolved risk** |
| Rollback trigger | Not defined | Required | — | **Blocking** |
| Reconciliation owner | Not named | Required | — | **Blocking** |
| Delta migration process | Not defined | Required | — | **Blocking** |

**None of the three data gaps may be reclassified as "cleanup later" without a named owner explicitly accepting the risk in writing before launch.**

---

## Source Audit

### 70 Missing Articles

The import log is the primary diagnostic surface. Run this against the import tool's log table before any rerun:

```sql
SELECT source_id, source_url, error_message, attempted_at
FROM wp_import_log
WHERE status IN ('failed','skipped')
  AND content_type = 'article'
ORDER BY attempted_at DESC;
```

Cross-reference results against the source export manifest to classify each gap:

- **Recoverable failures** — import error (timeout, encoding, malformed HTML): fix transform and rerun.
- **Source data gaps** — record exists in source but content is empty or unpublishable: document with editorial owner decision (import as draft or exclude).
- **Out-of-scope exclusions** — records intentionally excluded but not communicated: confirm with project owner.

Stable ID tracking is required for reconciliation. If `_legacy_id` post meta is not already being stored on import, add it before the production run:

```php
// In the import script, after wp_insert_post():
update_post_meta( $post_id, '_legacy_id', $source_record['id'] );
```

This enables spot-check queries later:

```bash
wp post list --meta_key=_legacy_id --meta_value=<source_id> --fields=ID,post_title,post_status
```

### 61 Media Failures

All 61 failures are path-missing errors. Before production cutover, run:

```bash
# Export failed media records from import log
wp eval 'global $wpdb; $rows = $wpdb->get_results("SELECT source_path FROM wp_import_log WHERE status='"'"'failed'"'"' AND content_type='"'"'media'"'"'"); foreach($rows as $r) echo $r->source_path . "\n";' > failed_media_paths.txt
```

For each path, attempt recovery in this order:
1. Check source CMS media library for alternate path or renamed file.
2. Check source server filesystem or CDN for the asset.
3. If unrecoverable, flag for editorial owner review: either use a placeholder image or accept a broken media reference on that post.

For recoverable files, re-import individually:

```bash
wp media import /path/to/recovered/file.jpg \
  --post_id=$(wp post list --meta_key=_legacy_id --meta_value=<article_source_id> --field=ID) \
  --title="<title>" \
  --desc="<description>" \
  --path=/var/www/wordpress
```

**Release gate:** All 61 failures must be either re-imported or explicitly accepted by the editorial owner before production cutover. A count of unresolved media failures must appear in the launch checklist signoff document.

### 37 Empty `office_location` Fields

Diagnose source data before production:

```sql
-- Run against source database
SELECT id, name, office_location
FROM staff_profiles
WHERE office_location IS NULL OR office_location = ''
LIMIT 50;
```

Classify:
- **Source data genuinely empty** — remote/no-office staff: decide whether to leave blank, use a sentinel value like "Remote", or populate before migration.
- **Source field exists but transform dropped it** — fix the field mapping.
- **Source field in different column or meta key** — correct the mapping.

Do not proceed to production with 37 known empty fields without a classification and owner decision. Empty `office_location` on published staff profiles is a user-visible defect.

---

## Target Mapping

*Abbreviated for this fixture — mapping was established in the dry run. The three gaps above represent mapping failures that must be resolved before production.*

Key post meta fields requiring stable IDs for reconciliation:

| Meta Key | Purpose |
|---|---|
| `_legacy_id` | Source record ID — enables deduplication and delta re-import |
| `_legacy_url` | Source canonical URL — used by `wp search-replace` and redirect validation |
| `_import_run_id` | UUID per import run — enables auditing which run created/updated a record |

If `_import_run_id` is not currently being set, add it. This is what makes reruns auditable:

```bash
wp post list --meta_key=_import_run_id --meta_value=<run_uuid> --fields=ID,post_title --format=count
```

---

## Transform And Execution Plan

### Phase 1: Freeze Window

**Freeze start:** T-7 days before launch.

**What freezes:** All new articles and profile edits in the legacy CMS. Only urgent announcements are exempt.

**Urgent announcement exception process:**
- Defined ahead of time: who approves (editorial director or equivalent), what qualifies (breaking news, safety notices, etc.)
- Every exception creates a delta record that must be tracked: maintain a shared log (spreadsheet or Notion page) with legacy CMS ID, title, published timestamp, and migration owner.
- At cutover, this log is the delta migration checklist.

**Freeze enforcement:** WordPress capability controls are not yet relevant — the freeze is on the legacy CMS side. Communicate via editorial Slack/email and confirm with all editors before freeze start.

### Phase 2: Resolve Dry-Run Gaps Before Rerun

**In order:**

1. Diagnose and classify 70 missing articles (import log queries above).
2. Fix transform bugs for recoverable failures.
3. Recover or accept 61 media files.
4. Classify and resolve 37 empty `office_location` fields.
5. Update import script with `_legacy_id`, `_legacy_url`, `_import_run_id` meta if not present.

**Do not rerun on staging until gaps are classified.** A rerun before fixing root causes produces a second data point with the same 70 failures and no new information.

### Phase 3: Dry-Run Rerun (Staging)

After fixes are applied, run a full import on staging using a fresh production data snapshot:

```bash
# Reset staging WordPress to clean state
wp site empty --yes --path=/var/www/staging-wordpress
wp option update siteurl 'https://staging.example.com' --path=/var/www/staging-wordpress
wp option update home 'https://staging.example.com' --path=/var/www/staging-wordpress

# Run import with new run ID
IMPORT_RUN_ID=$(uuidgen) php import.php --run-id="$IMPORT_RUN_ID" --dry-run=false 2>&1 | tee import-rerun-$(date +%Y%m%d).log
```

Post-rerun count verification:

```bash
wp post list --post_type=post --post_status=any --format=count --path=/var/www/staging-wordpress
wp post list --post_type=staff_profile --post_status=any --format=count --path=/var/www/staging-wordpress
wp media list --format=count --path=/var/www/staging-wordpress
```

**Rerun acceptance gate:** Article count must reach 4,800 (or the residual gap must be documented with owner acceptance). If the rerun produces a different failure set than the dry run, the import script is non-deterministic — investigate before proceeding.

### Phase 4: Launch Rehearsal (Staging)

The rehearsal simulates the full production cutover sequence, end-to-end, on staging. It must be completed at least 48 hours before the production cutover window.

Rehearsal sequence:

1. Verify staging count matches expected (4,800 or accepted residual).
2. Run `wp search-replace` with `--dry-run` flag:
   ```bash
   wp search-replace 'http://legacy.example.com' 'https://new.example.com' \
     --skip-columns=guid \
     --dry-run \
     --report-changed-only \
     --path=/var/www/staging-wordpress
   ```
3. Apply search-replace without `--dry-run` and verify no broken internal links.
4. Verify redirects: sample 20 legacy URLs, confirm 301 to correct WP destination.
5. Run editorial smoke review: spot-check 10 articles, 5 staff profiles, 3 taxonomy pages.
6. Verify media: spot-check 10 featured images, 5 inline media embeds.
7. Simulate delta import: add a test article in source after the freeze timestamp, run delta import, verify it lands in staging WP.
8. Simulate rollback: restore staging from backup, verify article count returns to pre-import baseline.
9. Document rehearsal result (pass/fail per gate) in the signoff document.

### Phase 5: Delta Migration (Freeze Period → Cutover)

Any legacy content created or modified after the freeze timestamp but before production cutover must be captured.

Delta identification:

```sql
-- Run against source database
SELECT id, title, status, created_at, modified_at
FROM articles
WHERE modified_at > '<freeze_timestamp>'
ORDER BY modified_at DESC;
```

Delta import process:

```bash
php import.php \
  --run-id="delta-$(date +%Y%m%d-%H%M%S)" \
  --since='<freeze_timestamp>' \
  --upsert=true \
  --dry-run=false \
  2>&1 | tee import-delta-$(date +%Y%m%d).log
```

The `--upsert` flag must be implemented in the import script: if a record with a matching `_legacy_id` already exists in WordPress, update it rather than creating a duplicate. If `--upsert` is not implemented, this is a blocking gap — a delta import without upsert will double-import records.

Urgent announcement exceptions are imported via this same delta process. Verify each against the exception log before production cutover.

### Phase 6: Production Cutover Sequence

**T-0 prerequisites (all must pass):**

- [ ] Hosting backup verified restorable (tested, not assumed — see Rollback section).
- [ ] Rehearsal signoff document completed.
- [ ] Rollback owner named and reachable.
- [ ] Reconciliation owner named.
- [ ] Delta import tested on staging.
- [ ] All 3 unresolved risks classified and accepted or resolved.

**Cutover sequence:**

```
T-2h  Confirm legacy CMS editorial freeze is holding. Check exception log.
T-1h  Take final production backup. Record backup timestamp and location.
T-1h  Run final source-side delta query. Record expected delta record count.
T-0   Enable WordPress maintenance mode: wp maintenance-mode activate
T-0   Run production import:
        php import.php --run-id="prod-$(date +%Y%m%d-%H%M%S)" --dry-run=false
T+15m Run count verification (see Validation Plan).
T+15m Run wp search-replace for domain/URL normalization (dry-run first, then apply).
T+30m Verify siteurl and home options:
        wp option get siteurl
        wp option get home
T+30m Verify redirects (sample 20 legacy URLs).
T+45m Editorial smoke review (10 articles, 5 profiles, 3 taxonomy pages).
T+1h  DNS cutover (or load balancer switch).
T+1h  Disable maintenance mode: wp maintenance-mode deactivate
T+2h  Post-cutover count recheck (see Validation Plan).
T+2h  Rollback decision window opens. Owner must actively decide to proceed or roll back.
T+24h First post-launch reconciliation run.
```

---

## Validation Plan

### Count Reconciliation

Run after import, after search-replace, and at T+2h post-cutover:

```bash
# Article counts by status
wp post list --post_type=post --post_status=publish --format=count
wp post list --post_type=post --post_status=draft --format=count
wp post list --post_type=post --post_status=any --format=count

# Staff profile counts
wp post list --post_type=staff_profile --post_status=any --format=count

# Media counts
wp media list --format=count

# Taxonomy term counts (adjust taxonomy slugs to match your CPT registration)
wp term list category --format=count
wp term list post_tag --format=count
```

Compare against:
- Source export manifest counts.
- Dry-run counts (to detect regressions between runs).
- Expected totals (4,800 articles, full profile count).

Any count below the dry-run baseline is a regression and triggers the rollback decision process.

### Record-Level Reconciliation

Spot-check 10 specific articles using stable IDs:

```bash
for LEGACY_ID in 101 205 388 491 750 1003 1247 1890 2341 3012; do
  wp post list \
    --meta_key=_legacy_id \
    --meta_value=$LEGACY_ID \
    --fields=ID,post_title,post_status,post_date \
    --format=table
done
```

For each spot-checked record, verify: title, body content (spot-read, not word-count), featured image present, taxonomy terms assigned, `_legacy_url` meta present for redirect mapping.

### Failed Import Queue

After production import, query for any failures in this run:

```bash
wp eval 'global $wpdb;
  $run_id = "<prod-run-id>";
  $failed = $wpdb->get_results(
    $wpdb->prepare(
      "SELECT source_id, content_type, error_message FROM wp_import_log WHERE run_id = %s AND status = %s",
      $run_id, "failed"
    )
  );
  foreach($failed as $r) {
    echo $r->content_type . "\t" . $r->source_id . "\t" . $r->error_message . "\n";
  }'
```

Any failure not already in the dry-run failure set is a new regression and triggers a hold on the cutover.

### Redirect Validation

Sample 20 legacy URLs from the redirect map and verify 301 to correct WP destination:

```bash
while IFS=',' read -r legacy_url expected_wp_url; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -L "$legacy_url")
  FINAL=$(curl -s -o /dev/null -w "%{url_effective}" -L "$legacy_url")
  echo "$STATUS | $legacy_url -> $FINAL (expected: $expected_wp_url)"
done < redirect_sample.csv
```

Failure threshold: more than 2 of 20 sampled redirects returning non-301 or wrong destination triggers a hold.

### Media Validation

```bash
# List all attachment URLs and check HTTP status
wp post list --post_type=attachment --fields=ID,guid --format=csv | \
  tail -n +2 | \
  while IFS=',' read -r id url; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    [ "$STATUS" != "200" ] && echo "FAIL $STATUS | $id | $url"
  done
```

Run on a sample of 50 attachments if full check takes too long. Any 404s on attachments that were in the known-good dry-run set are regressions.

### SEO Metadata

Verify Yoast/RankMath or equivalent SEO plugin fields on 5 spot-checked articles:

```bash
wp post meta get <post_id> _yoast_wpseo_title
wp post meta get <post_id> _yoast_wpseo_metadesc
wp post meta get <post_id> _yoast_wpseo_canonical
```

If canonical URLs still point to the legacy domain after search-replace, the `--skip-columns=guid` flag may need adjustment.

---

## Rollback And Monitoring

### Backup Verification (Pre-Launch Gate)

The hosting backup existing is not the same as the backup being restorable. Before the rehearsal, not just before launch:

```bash
# Restore backup to a separate staging environment (not the rehearsal environment)
# Verify restored WordPress is functional:
wp option get siteurl --path=/var/www/backup-restore-test
wp post list --post_type=post --format=count --path=/var/www/backup-restore-test
```

Record: backup timestamp, restore duration, restored article count, who verified it. If this test has not been run, the backup is an assumption, not a gate.

### Rollback Trigger Criteria

Rollback is triggered by the named rollback owner if **any one** of the following is true at the T+2h checkpoint:

| Condition | Threshold |
|---|---|
| Article count below dry-run baseline | < 4,730 in WP |
| New import failures not in dry-run set | Any count > 0 |
| Redirect failure rate | > 2/20 sampled |
| Editorial smoke review hard fail | Any critical content unreadable |
| Media 404 rate on known-good assets | > 5% of sampled |
| Rollback owner unreachable | — (automatic hold, not proceed) |

The rollback decision window is **T to T+2h**. After T+2h, the rollback owner must actively close the window by signing off in the launch document. Silence does not equal sign-off.

### Rollback Owner

**Must be named before rehearsal.** This is a blocking gap. The rollback owner must:
- Be reachable (phone, not just Slack) for the full launch window (T-1h to T+4h).
- Have authority to execute the rollback without escalation.
- Know the backup restore procedure.

### Rollback Procedure

```bash
# Step 1: Immediately re-enable maintenance mode on WordPress
wp maintenance-mode activate --path=/var/www/wordpress

# Step 2: Point DNS/load balancer back to legacy site (or keep legacy live)
# [Document the specific DNS/LB command for this hosting environment here]

# Step 3: Restore WordPress from pre-cutover backup
# [Document the specific hosting backup restore command here]

# Step 4: Verify restoration
wp option get siteurl --path=/var/www/wordpress
wp post list --post_type=post --format=count --path=/var/www/wordpress

# Step 5: Disable maintenance mode only after count verification passes
wp maintenance-mode deactivate --path=/var/www/wordpress
```

Steps 2 and 3 must be documented with the exact hosting-specific commands before the rehearsal. Generic "restore from backup" is not an executable rollback plan.

### Rerun Strategy

After a rollback, before scheduling a second production attempt:

1. Run `wp post list --meta_key=_import_run_id --meta_value=<failed-run-id> --format=count` to confirm the rollback is clean (count should reflect the baseline, not the failed import).
2. Diagnose the failure using the production import log.
3. Fix the root cause in staging.
4. Run a full dry-run rerun on staging (same day, different run ID) to verify the fix holds.
5. Re-schedule production cutover with a minimum 48-hour gap for editorial re-communication.

### Reconciliation Owner

**Must be named before launch.** The reconciliation owner runs post-launch count checks, monitors the failed import queue, and owns the 30-day legacy read-only period coordination.

Responsibilities:
- T+24h: full count reconciliation (all types, compare against launch-day baseline).
- T+7d: media 404 audit.
- T+30d: legacy site decommission checklist (confirm all redirects tested, no remaining legacy-only content identified).

### Post-Launch Monitoring

For the first 7 days:

```bash
# Daily article count check (add to cron or run manually)
wp post list --post_type=post --post_status=publish --format=count

# Check for any posts with missing _legacy_id (indicates orphaned imports)
wp eval 'global $wpdb;
  $count = $wpdb->get_var(
    "SELECT COUNT(p.ID) FROM wp_posts p
     LEFT JOIN wp_postmeta m ON p.ID = m.post_id AND m.meta_key = '"'"'_legacy_id'"'"'
     WHERE p.post_type = '"'"'post'"'"' AND m.meta_id IS NULL"
  );
  echo "Posts missing _legacy_id: $count\n";'
```

Monitor server error logs for media 404s. If the hosting environment provides access logs, filter for `404` responses on `/wp-content/uploads/`.

---

## Assumption Register

| # | Assumption | Fragility | Verification Required Before |
|---|---|---|---|
| A1 | Import script is idempotent — reruns produce the same result | **HIGH** — one dry run proves execution, not idempotency | Dry-run rerun on staging |
| A2 | 70 missing articles are diagnosable from import log | MEDIUM — log may be incomplete or missing error context | Import log query before rerun |
| A3 | Media files for 61 failures exist somewhere (source server, CDN, archive) | **HIGH** — if source paths are gone, recovery requires editorial decision | Source file investigation |
| A4 | Import script supports `--upsert` for delta migration | **HIGH** — if not implemented, delta import will create duplicates | Code inspection before rehearsal |
| A5 | Hosting backup is restorable in < 2 hours | HIGH — restore duration determines whether rollback is viable in the launch window | Tested restore on isolated environment |
| A6 | Legacy CMS can be queried for delta records by `modified_at` timestamp | MEDIUM — depends on source CMS schema | Source DB schema inspection |
| A7 | `wp search-replace` with `--skip-columns=guid` is safe for this content model | MEDIUM — custom tables or serialized meta may not be covered | Dry-run output review |
| A8 | Editorial "urgent announcement" exceptions will be < 10 records during freeze | LOW — depends on news cycle | Accepted as planning assumption; exception log is the mitigation |
| A9 | Legacy site will remain read-only and accessible for 30 days | MEDIUM — depends on hosting contract and vendor cooperation | Confirm with legacy hosting owner before launch |

---

## Test Strategy

### Test 1: Import Idempotency (Staging)

**Purpose:** Prove the import script is rerunnable, not just runnable.

**Method:** Run import on clean staging. Record run ID and article count. Run import again with the same source data and a new run ID. Compare article counts — they must match. Compare `_legacy_id` meta — no duplicates should exist.

**Pass criteria:** Second run produces zero new posts (upsert only), same total count.

### Test 2: Delta Import (Staging)

**Purpose:** Prove the delta process captures freeze-window content.

**Method:** Record freeze timestamp. Add one test article and modify one existing article in source after the timestamp. Run delta import with `--since=<freeze_timestamp>`. Verify the new article appears in WP and the modified article reflects the update.

**Pass criteria:** New article present, modified article updated, no duplicates.

### Test 3: Media Re-Import (Staging)

**Purpose:** Prove recovered media files can be re-imported and associated with the correct post.

**Method:** Re-import 5 of the recovered media files using `wp media import` with the `--post_id` flag. Verify the media appears in the post's gallery/featured image.

**Pass criteria:** All 5 media items appear in the correct post with correct metadata.

### Test 4: Rollback (Staging Rehearsal)

**Purpose:** Prove the rollback procedure works within the launch window time constraint.

**Method:** Complete the full cutover sequence on staging. At T+30min, execute the rollback procedure. Time the restoration. Verify article count returns to pre-import baseline.

**Pass criteria:** Restore completes in < 90 minutes. Article count matches pre-import baseline exactly.

### Test 5: Redirect Coverage (Staging)

**Purpose:** Verify that `wp search-replace` and redirect rules produce correct behavior.

**Method:** After search-replace, test the 20-URL redirect sample against staging.

**Pass criteria:** ≥ 18/20 URLs return 301 to the correct WP destination.

### Launch Rehearsal Gate

The launch rehearsal (Phase 4 above) must pass all five tests before the production cutover window is scheduled. A rehearsal that fails Test 4 (rollback) means production launch is blocked until rollback is made reliable — the risk is too high to proceed.

---

## Acceptance Criteria

These gates must all be satisfied and documented in a signoff document before production cutover begins. Each gate requires a named human owner who has verified it.

**Data Gaps:**
- [ ] 70 missing articles: root cause identified; either all imported on rerun, or residual gaps have named editorial owner acceptance in writing.
- [ ] 61 media failures: all files either recovered and re-imported, or each one has named editorial owner acceptance in writing.
- [ ] 37 empty `office_location` fields: root cause classified; fields populated, or each profile has named owner acceptance.

**Migration Mechanics:**
- [ ] Import script proven idempotent: staging rerun produces same count, no duplicates.
- [ ] Delta migration tested: new and modified source content appears correctly in staging WP.
- [ ] `wp search-replace` dry-run reviewed and applied on staging without broken links.
- [ ] `wp option get siteurl` and `wp option get home` return correct production values on staging.

**Rollback:**
- [ ] Rollback owner named with contact information documented.
- [ ] Hosting backup tested restorable (not just confirmed to exist).
- [ ] Rollback procedure documented with hosting-specific commands.
- [ ] Rollback procedure timed during rehearsal: completes in < 90 minutes.

**Reconciliation:**
- [ ] Reconciliation owner named with responsibilities documented.
- [ ] Post-launch monitoring schedule documented (T+24h, T+7d, T+30d checkpoints).

**Rehearsal:**
- [ ] Launch rehearsal completed on staging within 48 hours before production cutover.
- [ ] All five test categories passed during rehearsal.
- [ ] Rehearsal signoff document signed by rollback owner and editorial lead.

**Freeze:**
- [ ] Content freeze communicated and confirmed with all editors.
- [ ] Urgent announcement exception process defined and distributed.
- [ ] Exception log (empty or populated) reviewed before cutover.

---

## Critic Handoff

This plan is ready for review by `wordpress-migration-critic` (if available) or `perf-critic` / `qa-critic` for validation coverage gaps.

Key review targets:
1. **Idempotency proof** — is the staging rerun test sufficient, or does it need more than two runs?
2. **Delta upsert logic** — is the `--upsert` implementation in the import script adequately specified, or is there more needed around conflict resolution?
3. **Rollback time budget** — is 90 minutes a reasonable constraint given the hosting backup mechanism, or should it be shorter?
4. **Media failure acceptance threshold** — the plan treats any unresolved media failure as requiring named owner sign-off. Is this the right threshold, or should some categories (e.g., decorative images with no editorial value) be handled differently?
5. **Legacy read-only period** — the 30-day window is stated as a fact but has no verification gate. The critic should flag whether the decommission checklist at T+30d is adequately specified.
