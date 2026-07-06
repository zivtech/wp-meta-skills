This is a smoke fixture run — I'll produce the contract output for the given scenario.

---

## Migration Scope

**Classification:** Builder-to-Block (page-builder shortcode/meta content → Gutenberg block markup), with media sideload validation and redirect preservation.

**In scope:**
- Post and page content stored as builder shortcodes or serialized builder meta (assumed Elementor or Classic Editor with shortcodes — see Assumption Register)
- Attached and referenced media (featured images, inline images, gallery shortcodes)
- Existing permalink structure and any redirect rules in place
- Block template assignment post-migration

**Out of scope (deferred):** User migration, taxonomy restructure, multisite, headless/REST consumers. Flag if these surface during source audit.

---

## Current-State Evidence

**What must be established before planning continues:**

1. Run `wp post list --post_type=page,post --fields=ID,post_status,post_content --format=csv > content-inventory.csv` on a staging clone — never production — to get content counts and a sample of raw shortcode/builder markup.
2. Run `wp db export --tables=$(wp db tables --scope=blog --format=csv) staging-pre-migration.sql` to establish a restore point before any transforms.
3. Identify the builder plugin version: `wp plugin list --format=table | grep elementor` (or equivalent). Block transformer compatibility is version-specific.
4. Identify current PHP and WordPress versions: `wp core version` and `php --version`. Block API v2 (`block.json` with `apiVersion: 2`) requires WordPress ≥ 5.6.

**Gap:** Until the content inventory is run, content volume, shortcode diversity, and media reference patterns are fragile assumptions. The plan below names those assumptions explicitly.

---

## Source Audit

**Content shape:**
- Builder content is typically stored in `post_content` as shortcodes (Classic Editor / WPBakery) or as `<!-- wp:elementor/template -->` wrapper blocks (Elementor 3.x), with the canonical layout in `_elementor_data` post meta.
- Shortcode diversity audit: `wp eval 'global $wpdb; $rows = $wpdb->get_results("SELECT post_content FROM {$wpdb->posts} WHERE post_status = '"'"'publish'"'"'"); foreach($rows as $r) preg_match_all("/\[([a-z_]+)/", $r->post_content, $m); $counts = array_count_values(array_merge(...array_column($m, 1))); arsort($counts); print_r($counts);'` — run on staging.
- Meta inventory: identify all `_elementor_data`, `_elementor_page_settings`, and `_elementor_edit_mode` meta keys via `wp post meta list <ID>`.

**Media:**
- Identify orphaned vs. attached media: `wp media list --fields=ID,post_parent,post_status,file --format=csv`.
- Check for builder-injected absolute URLs in `post_content` or meta that reference the source domain — these will break on migration if not rewritten.
- Identify gallery shortcodes: `[gallery ids="..."]` → must map to `<!-- wp:gallery -->` block.

**URL / redirect inventory:**
- Export current redirect rules from the Redirection plugin (if in use): `wp eval 'echo json_encode(Red_Item::get_all());'` on staging, or export via Redirection plugin admin CSV export.
- Capture all published URLs: `wp post list --post_type=page,post --fields=ID,post_name,post_status --format=csv`.
- Identify custom permalink structures: `wp option get permalink_structure`.

**Users and permissions:** Out of scope for this migration type, but verify `current_user_can('edit_posts')` checks are not bypassed by any migration script running under an elevated CLI user.

---

## Target Mapping

**Block equivalents for common builder widgets:**

| Source | Target block | Notes |
|---|---|---|
| Text/HTML widget | `core/paragraph`, `core/heading`, `core/html` | Use `wp_kses_post()` on raw HTML content |
| Image widget | `core/image` | Reattach via `attachment_id`; rewrite `src` to `wp_get_attachment_url()` |
| Gallery shortcode | `core/gallery` | Map comma-separated IDs to `ids` attribute array |
| Button widget | `core/button` | Wrap in `core/buttons` |
| Columns/row | `core/columns` + `core/column` | Map column widths to `width` attribute |
| Video embed | `core/embed` (YouTube/Vimeo provider) or `core/video` for self-hosted |
| Accordion/Tabs | No core equivalent → **manual QA boundary** (see Hard Gate below) |
| Custom builder widgets | **Unsupported** → `core/html` with audit flag |

**Unsupported-widget handling (Hard Gate):** Any builder widget without a direct block equivalent must be:
1. Converted to `core/html` as a fallback, preserving rendered HTML.
2. Flagged in a per-post audit log with `post_id`, `widget_type`, and `manual_review_required: true`.
3. Reviewed by an editor before the post is republished. Do not silently drop content.

**Block validation recovery:** If a migrated post fails block validation on editor open (invalid block markup), WordPress surfaces "This block contains unexpected or invalid content." The recovery path is `block.json` `deprecated` versions with a `migrate` callback — define one for any custom blocks introduced by the migration. For core blocks, use `wp.blocks.getBlockType('core/image').deprecated` to verify expected versions.

**Templates:** Map existing page templates (PHP template files or builder templates) to block template files (`templates/*.html`) under the active block theme, or to `wp_get_block_template()` if the theme uses template parts. This requires the target theme to be a block theme — verify with `wp theme list --status=active`.

**Meta:** Identify which builder meta keys should be preserved vs. deleted post-migration. Register surviving meta with `register_post_meta()` using `show_in_rest`, `auth_callback`, and `sanitize_callback` before the migration run.

---

## Transform And Execution Plan

**Idempotency requirement:** Every transform script must be safe to rerun. Use a `_migration_run_id` post meta key (e.g., `migration-2026-06-21-v1`) to mark processed posts. On rerun, skip already-processed posts unless `--force` flag is passed.

**Two-pass approach:**

**Pass 1 — Content transform (staging only):**
1. Export staging DB: `wp db export pre-migration-$(date +%Y%m%d).sql`.
2. For each post, extract builder data from `_elementor_data` (or parse shortcodes from `post_content`).
3. Convert widget tree → block tree using a custom PHP script (not raw SQL). Use `parse_blocks()` to validate intermediate block strings. Use `serialize_blocks()` to write the final `post_content`.
4. Sanitize all HTML content through `wp_kses_post()` before writing to `post_content`.
5. Update `post_content` via `wp_update_post(['ID' => $id, 'post_content' => $block_markup])` — never via direct `$wpdb->update()` on `wp_posts` without `$wpdb->prepare()`.
6. Set `_migration_run_id` meta on success. Log failures to `migration-errors.log`.

**Pass 2 — Reference resolution:**
1. Rewrite media URLs: for each `<img src="...">` in converted content, resolve to `attachment_id` via `attachment_url_to_postid()`, then replace with block-native `wp_get_attachment_url($id)`.
2. Rewrite internal links: use `home_url()` as the base — do not hardcode domain strings.
3. Media sideload for any external images not in the media library: `media_sideload_image($url, $post_id, null, 'id')`. Dedupe by checking `attachment_url_to_postid()` before sideloading.
4. Gallery shortcode → block: extract `ids` attribute, verify each attachment exists in the library, write `<!-- wp:gallery {"ids":[...]} -->` block markup.

**Redirect handling:**
- Do not delete old slugs until redirects are verified.
- For URL changes resulting from the migration (e.g., slug normalization), insert redirect rules via the Redirection plugin's `Red_Item::create()` or via `wp eval` on staging. Use 301 (permanent) for SEO-preserving moves.
- `wp_safe_redirect($new_url, 301)` is the correct PHP surface; for plugin-managed redirects, use the plugin's own API to avoid conflicts with `.htaccess` or Nginx rules.

**WP-CLI batch execution pattern:**
```bash
wp eval-file migration/pass1-transform.php --batch=50 --dry-run
# Review migration-errors.log
wp eval-file migration/pass1-transform.php --batch=50
wp eval-file migration/pass2-references.php --batch=50 --dry-run
wp eval-file migration/pass2-references.php --batch=50
```

**Editorial freeze:** No content edits during migration window. Enforce via a maintenance mode plugin or `define('DISALLOW_FILE_EDIT', true)` equivalent for content — or communicate freeze window explicitly to editors.

**Content delta handling:** If a production run follows a staging run, identify posts modified after the staging freeze via `wp post list --after=<freeze-date> --fields=ID,post_modified`. Replay transforms only on delta posts.

---

## Validation Plan

**Automated checks (run via WP-CLI on staging, then production):**

1. **Count check:** `wp post list --post_type=page,post --post_status=publish --format=count` before and after — counts must match.
2. **Block validity:** `wp eval 'foreach(get_posts(["numberposts"=>-1]) as $p) { $blocks = parse_blocks($p->post_content); foreach($blocks as $b) if(empty($b["blockName"])) echo "invalid: {$p->ID}\n"; }'` — zero invalid blocks expected.
3. **Media check:** For each post, verify `has_post_thumbnail()` matches pre-migration inventory. Spot-check 10% of inline images resolve to `200 OK` via `wp_remote_head()`.
4. **Redirect sampling:** For 20% of migrated URLs, issue `wp_remote_get($old_url)` and verify `301` status and correct `Location` header.
5. **SEO metadata:** Verify Yoast/RankMath meta fields (if in scope) survive on a 10% sample: `wp post meta get <ID> _yoast_wpseo_metadesc`.
6. **Block render smoke:** Load 10 representative posts via `do_blocks($post->post_content)` — no PHP errors, no `[block rendering failed]` output.

**Manual QA boundaries:**
- All posts flagged `manual_review_required: true` (unsupported widgets).
- Any post where Pass 2 logged a media sideload failure.
- Accordion, tabs, and interactive widgets converted to `core/html` fallback.
- Landing pages and high-traffic pages (top 20 by analytics).

**Performance check:** Run Query Monitor on 5 representative migrated pages. Block renders should not introduce N+1 queries. Flag any `render_callback` or `render.php` that issues unbounded `WP_Query` calls.

---

## Rollback And Monitoring

**Backup strategy:**
- `wp db export` before Pass 1 and before Pass 2 on both staging and production.
- Store exports off-server (S3, managed backup plugin, or hosting snapshot).
- Verify restore works before starting production run: `wp db import pre-migration.sql` on a test clone.

**Rollback trigger:** Roll back if:
- Post count drops after migration.
- More than 5% of sampled redirects return non-301 or wrong `Location`.
- Block validation errors on more than 2% of posts.
- Any data loss confirmed in manual QA.

**Rollback procedure:**
1. `wp db import pre-migration-<date>.sql` on production (staging-validated first).
2. Re-activate builder plugin if it was deactivated.
3. Verify content renders via spot-check before communicating rollback to editors.

**Post-launch monitoring (first 30 days):**
- Monitor 404 rate in Google Search Console and server logs.
- Monitor Core Web Vitals for migrated page templates (block themes can improve or regress LCP/CLS vs. builder output).
- Run Query Monitor on 3 random pages weekly for the first two weeks.
- Check Redirection plugin's 404 log daily for the first week to catch missed redirects.

**Error queues:** Log all migration script failures to `migration-errors.log` with `post_id`, `error_type`, and `raw_data` snapshot. Review before cutover.

**Ownership:** Assign one named person responsible for monitoring each of: redirects, media, block rendering, performance. Do not distribute ownership without explicit assignment.

---

## Assumption Register

| # | Assumption | Fragility | Resolution |
|---|---|---|---|
| A1 | Builder is Elementor 3.x with data in `_elementor_data` meta | FRAGILE — Classic Editor, WPBakery, Beaver Builder, Divi all store data differently | Confirm builder plugin and version from `wp plugin list` before starting |
| A2 | Target theme is a block theme (FSE) | FRAGILE — if the active theme is a classic theme, block templates do not apply; migration still works but template mapping is different | `wp theme list --status=active` and check for `theme.json` |
| A3 | Media library is on the same WordPress install (not CDN-offloaded or externally hosted) | REASONABLE — most installations; CDN-offloaded media requires sideload step for all assets | Check `wp option get upload_url_path` and Offload Media plugin status |
| A4 | Redirection plugin is managing redirects (not Apache/Nginx config-level rules) | REASONABLE — most shared/managed hosting; config-level rules require sysadmin coordination | Check `.htaccess` and Nginx config for `Redirect` or `rewrite` directives |
| A5 | Permalink structure is not changing (no slug normalization) | FRAGILE — if slugs change, every redirect must be explicitly created | Confirm slug policy before Pass 1 |
| A6 | No headless/REST consumers depend on `post_content` format | FRAGILE — if a mobile app or external system parses raw `post_content`, block markup will break it | Audit `register_rest_route` consumers and WooCommerce REST if applicable |
| A7 | Editorial freeze is achievable for the migration window | REASONABLE — depends on editorial team size and publishing cadence | Confirm with stakeholders before setting migration date |

---

## Test Strategy

**Fixture migrations (staging-only dry runs):**

1. Select 5 representative posts: one simple text page, one media-heavy page, one with gallery shortcodes, one with unsupported widgets (accordion/tabs), one with custom meta.
2. Run Pass 1 + Pass 2 transforms on the 5 fixtures only (`--ids=1,2,3,4,5`).
3. Assert per fixture:
   - `post_content` is valid block markup (no raw shortcodes remain): `wp eval 'echo count(parse_blocks(get_post($id)->post_content));'` > 0.
   - Featured image attachment ID unchanged.
   - All `<img>` src attributes resolve to `wp_get_attachment_url()` output (not raw source-domain URLs).
   - `_migration_run_id` meta is set.
   - Unsupported-widget posts have `manual_review_required` meta set.

**Rerun tests:**
- Run Pass 1 on the same 5 fixtures a second time without `--force`.
- Assert: `post_content` is unchanged (idempotency), no duplicate media sideloads, `_migration_run_id` meta still matches original run ID.

**Rollback test:**
- After fixture migration, `wp db import pre-migration.sql` on staging clone.
- Assert: `post_content` matches pre-migration export, builder plugin renders correctly.

**Redirect tests:**
- For each fixture post with a known old URL, assert `wp_remote_get($old_url)` returns `301` with correct `Location`.

**Permission tests:**
- Run migration script as `--user=contributor` (or equivalent low-privilege user).
- Assert: script exits with permission error rather than proceeding. Migration must run as admin or CLI; it must not be triggerable by unprivileged users.

**Launch rehearsal:**
- Run full migration on a production-data staging clone 48 hours before the production window.
- Validate all automated checks pass.
- Complete manual QA sign-off checklist.
- Only proceed to production if rehearsal passes without rollback.

---

## Acceptance Criteria

- [ ] Post count on production matches pre-migration count after Pass 1 and Pass 2.
- [ ] Zero raw builder shortcodes in `post_content` of migrated posts (verified via `parse_blocks()`).
- [ ] Zero block validation errors on automated sample (100% of posts via `parse_blocks()` check).
- [ ] 100% of sampled old URLs return `301` to correct new URL.
- [ ] Zero 404s on media referenced by migrated posts (10% sample via `wp_remote_head()`).
- [ ] All `manual_review_required` posts have been reviewed and signed off by an editor.
- [ ] Query Monitor shows no regressions on 5 representative pages vs. pre-migration baseline.
- [ ] Rollback procedure verified on staging clone within 48 hours of production run.
- [ ] Migration error log reviewed; all entries resolved or accepted.

---

## Critic Handoff

**Downstream routing:**

| Next step | Agent | Input |
|---|---|---|
| Review this plan for gaps, unsafe recommendations, or missing hard gates | `wordpress-migration-critic` | This document |
| Generate WP-CLI / PHP migration scripts from this plan | `drupal-config-executor` (if adapted) or a custom executor | Transform And Execution Plan section |
| Review block conversion output for block API correctness | `wordpress-critic` | Post-transform `post_content` samples |
| Review performance of migrated pages | `perf-critic` | Query Monitor output from launch rehearsal |

**To invoke the migration critic after reviewing this plan:**
```
/wordpress-critic [paste this document or link to the PR]
```

**Unresolved before implementation can start:**
- A1 (builder identity) and A5 (slug policy) must be resolved — they change the transform design significantly.
- A6 (REST consumers) must be confirmed before production cutover — block markup in `post_content` is a breaking change for non-block consumers.
