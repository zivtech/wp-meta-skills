## Migration Scope

CMS-to-WordPress migration. Two content types in scope: articles (4,800) and staff profiles (900). Three taxonomies with known duplicate-term quality issues. Media sideload required with body-HTML path rewriting. Author/byline resolution has three possible dispositions. Revision history is **out of scope** until a source export and schema are provided. No claim of revision, author, or full media fidelity is made in this plan.

---

## Current-State Evidence

**Known:**
- 4,800 articles: title, body HTML, canonical URL, author username, created date, updated date, status
- 900 staff profiles: department, office location, headshot file path, biography
- Taxonomies: topic, audience, region — multi-vocabulary assignment possible
- Duplicate terms confirmed: "kids", "children", "youth" (likely others)
- Media: separately exported; body HTML contains old relative paths and third-party CDN URLs
- Revision history exists in source DB; no export provided

**Unknown and blocking:**
- Source DB schema: field names, types, table relationships
- Export format (CSV, XML, JSON, SQL dump, or mixed)
- Full list of article/profile status values
- Whether canonical URLs are same-domain or cross-domain
- User export: emails, roles, byline data structure
- Whether any articles have multiple authors
- Whether CDN URLs in body HTML are sideloadable
- Media manifest: file list, paths, types, sizes
- Revision export: schema and row count estimate

---

## Source Audit

Before any transform is finalized, require the following deliverables. Work stops at each BLOCKED gate until the item is received.

| Deliverable | Required before |
|---|---|
| Full DB schema dump (articles, profiles, taxonomy, users, junction tables) | Finalizing target mapping |
| 20 representative article rows (including HTML-heavy, multi-term, unusual status) | Finalizing field transforms |
| 20 representative staff profile rows | Finalizing profile field transforms |
| Content counts by status (articles and profiles) | Finalizing status mapping |
| Full taxonomy export: all terms per vocabulary with term IDs and parent/child structure | Taxonomy deduplication sign-off |
| User export: username, email, role, disposition flag | Author mapping table |
| Media manifest: source path → file type → file size → MD5 hash | Media sideload design |
| Revision export schema and row count (even if the export isn't ready) | Revision scope decision |

**Data quality issues already identified that require editorial decisions, not algorithmic resolution:**
- Taxonomy duplicates ("kids", "children", "youth") — a content editor must approve the canonical term mapping before taxonomy import
- Author three-way split — a mapping table, not a heuristic, must govern disposition
- Third-party CDN URLs — sideload or leave-as-external is a project decision, not a default

---

## Target Mapping

### Post Types

**Articles → `article` CPT** (or `post` if editorial workflow permits sharing a type with future blog content — project decision required)

```php
register_post_type( 'article', [
    'supports'     => [ 'title', 'editor', 'author', 'thumbnail', 'revisions', 'custom-fields', 'excerpt' ],
    'has_archive'  => true,
    'rewrite'      => [ 'slug' => 'articles' ], // slug confirmed from canonical URL audit
    'show_in_rest' => true,
] );
```

**Staff Profiles → `staff_profile` CPT**

```php
register_post_type( 'staff_profile', [
    'supports'     => [ 'title', 'editor', 'thumbnail', 'custom-fields' ],
    'has_archive'  => true,
    'show_in_rest' => true,
] );
```

**Meta fields via `register_post_meta()`:**

```php
// Staff profile fields
foreach ( [ 'department', 'office_location' ] as $key ) {
    register_post_meta( 'staff_profile', $key, [
        'type'          => 'string',
        'single'        => true,
        'show_in_rest'  => true,
        'sanitize_callback' => 'sanitize_text_field',
        'auth_callback' => function() { return current_user_can( 'edit_posts' ); },
    ] );
}
```

`biography` maps to `post_content`. Headshot maps to `_thumbnail_id` (featured image) after sideload.

**Idempotency anchor — `_source_id` on both CPTs:**

```php
register_post_meta( 'article', '_source_id', [
    'type'          => 'string',
    'single'        => true,
    'show_in_rest'  => false,  // internal only — never expose via REST
    'auth_callback' => '__return_false',
] );
// identical registration for 'staff_profile'
```

Every import run resolves `get_posts( [ 'meta_key' => '_source_id', 'meta_value' => $id, 'post_type' => 'article', 'posts_per_page' => 1 ] )` before deciding insert vs. update.

### Taxonomies

```php
register_taxonomy( 'topic',    [ 'article' ], [ 'hierarchical' => false, 'show_in_rest' => true ] );
register_taxonomy( 'audience', [ 'article' ], [ 'hierarchical' => false, 'show_in_rest' => true ] );
register_taxonomy( 'region',   [ 'article' ], [ 'hierarchical' => false, 'show_in_rest' => true ] );
```

**Deduplication protocol** — before import:
1. Export all source terms per vocabulary
2. Produce a mapping table: `source_term_id → canonical_wp_term_slug`
3. For duplicates ("kids/children/youth"), mark one as canonical — **editorial sign-off required**
4. On insert: `get_term_by( 'slug', $canonical_slug, $taxonomy )` — if exists, reuse; if not, `wp_insert_term()`
5. Store source term ID: `update_term_meta( $term_id, '_source_term_id', $source_id )`
6. Assign terms: `wp_set_object_terms( $post_id, $term_ids, $taxonomy, false )` — replace mode on first import; append (`true`) on delta runs to preserve editorial additions

**BLOCKED** until taxonomy export and editorial sign-off are complete.

### Author / Byline Mapping

Three paths; all require the user export to proceed.

| Disposition | Mechanism |
|---|---|
| Existing WP user | `get_user_by( 'login', $source_username )` → `post_author = user_id` |
| New WP user | `wp_insert_user( [ 'user_login', 'user_email', 'role' => 'author' ] )` |
| Archived byline | `_legacy_byline` string meta OR Co-Authors Plus guest author — **project decision required before import** |

Mapping table format (CSV, committed to migration repo):

```
source_username, wp_user_id_or_null, new_user_email_or_null, byline_display_name, disposition
```

**BLOCKED** until user export is received and byline data structure is confirmed.

### Status Mapping

FRAGILE — enumerated from schema audit once available. Working assumption:

| Source status | WordPress `post_status` |
|---|---|
| `published` | `publish` |
| `draft` | `draft` |
| `archived` | `private` or custom via `register_post_status()` — project decision |
| `deleted` | skip (do not import) |

### Revisions

**BLOCKED.** Revision history exists in source but no export is available. Options:
- Import without revisions (WordPress creates one revision on `wp_insert_post()`)
- Wait for export, then insert revisions via `wp_insert_post()` with `post_type => 'revision'` and `post_parent` set to the article's post ID

**This plan makes no claim of revision fidelity.** Decision must be made before cutover is scoped.

---

## Transform And Execution Plan

### Idempotency Gate

Every insert/update follows this sequence:

```
1. $existing = get_posts([ 'meta_key' => '_source_id', 'meta_value' => $source_id, 'post_type' => 'article', 'posts_per_page' => 1 ])
2. $post_data = wp_slash( $prepared_post_array )  // wp_slash() required before wp_insert_post() / wp_update_post()
3. if $existing: wp_update_post( array_merge( $post_data, [ 'ID' => $existing[0]->ID ] ) )
4. if empty: $post_id = wp_insert_post( $post_data ); update_post_meta( $post_id, '_source_id', $source_id )
5. dry-run mode: log action + source_id, skip DB writes
```

### Field Transforms — Articles

| Source field | WordPress target | Transform |
|---|---|---|
| `title` | `post_title` | `html_entity_decode()`, `trim()` |
| `body_html` | `post_content` | URL rewrite pass (post media sideload); `wp_kses_post()` on write |
| `canonical_url` | `_source_canonical` meta + 301 redirect | Parse path; redirect created after post ID is known |
| `author_username` | `post_author` | Lookup via mapping table; fail loudly if no match |
| `created_date` | `post_date` / `post_date_gmt` | ISO 8601 → MySQL datetime; normalize to UTC |
| `updated_date` | `post_modified` / `post_modified_gmt` | Same |
| `status` | `post_status` | Via status mapping table |

### Field Transforms — Staff Profiles

| Source field | WordPress target | Transform |
|---|---|---|
| Name | `post_title` | `trim()` |
| `biography` | `post_content` | `wp_kses_post()` |
| `department` | `department` meta | `sanitize_text_field()` → `update_post_meta()` |
| `office_location` | `office_location` meta | `sanitize_text_field()` → `update_post_meta()` |
| `headshot_path` | `_thumbnail_id` | Sideload via `media_sideload_image()` |

### Media Sideload and Path Rewriting

**Step 1 — Manifest audit:** Before import, produce source path → file type → MD5 hash manifest. Deduplication is hash-based; same file from different paths → one attachment.

**Step 2 — Type validation:** `wp_check_filetype( $filename )` before every sideload call; reject or log files with disallowed MIME types.

**Step 3 — Sideload:**
```php
$attachment_id = media_sideload_image( $file_url_or_path, $post_id, $alt_text, 'id' );
if ( is_wp_error( $attachment_id ) ) {
    log_migration_error( 'media_sideload', $source_path, $attachment_id->get_error_message() );
    // do NOT rewrite the URL in post_content — leave original path and flag for review
}
```

Track source path → `attachment_id` in a migration lookup table (custom DB table or a flat JSON file for small volumes). All subsequent references to the same source path resolve to the same attachment — no duplicate uploads.

**Step 4 — URL rewrite in `post_content`:** After all media is sideloaded, rewrite article bodies:
- Old relative path (`/uploads/2019/image.jpg`) → `wp_get_attachment_url( $attachment_id )`
- CDN URL (`https://cdn.example.com/...`) → same lookup; if the file was not sideloaded, leave the CDN URL intact and document it in the validation report
- All URLs written into HTML attributes pass through `esc_url()`

**Third-party CDN URLs:** This plan does NOT claim CDN content will be sideloaded. That requires the media manifest audit to confirm which CDN URLs are included in the media export.

### Redirect Creation

For every article with a `canonical_url`, after the post is created and its new permalink is known:

```bash
wp redirection add-redirect --url="/old/path/slug/" --action="/articles/new-slug/" --code=301
```

Or via the Redirection plugin REST API if WP-CLI access is restricted. Redirects are created in a separate pass after content import so the new permalink is known.

### Execution Sequence

1. Source schema dump + sample-row validation — **BLOCKED**
2. Taxonomy deduplication editorial sign-off — **BLOCKED**
3. Author mapping table — **BLOCKED**
4. Media manifest audit + CDN sideload decision — **BLOCKED**
5. Dry run: articles (log insert/update counts, no DB writes)
6. Dry run: staff profiles
7. Dry run: media sideload plan
8. Staging full import: articles → staff profiles → media sideload → body URL rewrite → redirects → taxonomy assignment
9. Staging validation (full plan below)
10. Editorial freeze on source CMS
11. Delta import: new/updated content since staging run
12. Cutover: DNS / domain switch
13. Post-launch monitoring

**WP-CLI operational commands:**
- `wp db export pre-import-$(date +%Y%m%d-%H%M%S).sql` — snapshot before each run
- `wp eval-file import-articles.php --url=staging.example.com` — run import script
- `wp post list --post_type=article --fields=ID,post_status --format=csv > post-audit.csv`
- `wp term list topic --fields=term_id,slug,count --format=csv`
- `wp cache flush` — after bulk imports
- `wp cron event run --due-now` — if using Action Scheduler for async sideloads

**Batch size:** 200 posts per batch. Log batch start/end/count. On failure, record last successful `_source_id` — resume from that point, do not restart from zero.

**Performance note:** If a full import run exceeds 4 hours on staging, route sideloads through Action Scheduler (`wp_schedule_event()` / `wp_next_scheduled()`) to avoid PHP timeout failures.

---

## Validation Plan

**Count checks (automated):**
- `wp post count --post_type=article` vs. expected 4,800 (by status)
- `wp post count --post_type=staff_profile` vs. expected 900
- `wp term list topic --format=count` vs. deduplicated term count from mapping table
- Media attachment count vs. manifest count

**URL audit:**
- Sample 50 canonical URLs → `curl -I` → assert HTTP 301 → follow to new URL → assert HTTP 200
- `wp redirection list --format=csv` → spot-check 20 entries against source canonical URLs

**Media checks:**
- 10% random article sample: parse `post_content` for `<img>` src values → assert all are WordPress-hosted or documented CDN references (no broken relative paths)
- All staff profiles with a non-null source headshot path: assert `has_post_thumbnail( $post_id )` returns true

**Taxonomy integrity:**
- `wp term list topic --fields=slug --format=csv` → assert no duplicate slugs
- 20-article spot-check: assert term assignments match mapping table

**Author integrity:**
- `wp post list --post_type=article --fields=ID,post_author --format=csv` → assert `post_author` is non-zero for all published posts
- If Co-Authors Plus: assert guest author terms exist for all archived-byline articles

**Performance spot-check:**
- Query Monitor active: load 3 article URLs and 3 profile URLs — confirm no N+1 queries from meta lookups

**Sample editorial review:**
- 10 articles: title, body rendering, author credit, taxonomy labels, media rendering, date display
- 5 staff profiles: name, bio, headshot, department, office location

---

## Rollback And Monitoring

**Backups before each run:**
- `wp db export pre-import-TIMESTAMP.sql` (off-server: S3 or remote storage)
- Media directory rsync snapshot before sideload run

**Rollback triggers (stop the import if any apply):**
- Post count check fails by >2%
- Media sideload error rate >5%
- More than 10 redirect resolution failures in URL audit
- Any published article with `post_author = 0`
- `wp_insert_post()` returning `WP_Error` at >1% rate

**Rollback procedure:**
```bash
wp db import pre-import-TIMESTAMP.sql
# restore media directory from rsync snapshot
wp cache flush
```
Re-run dry run to confirm clean state before retrying.

**Post-launch monitoring (first 7 days):**
- Google Search Console: watch for 404 spike
- Server error log: PHP fatals and media 404s
- Redirection plugin dashboard or access log: confirm redirects are firing
- Query Monitor: slow query alert on article/profile page loads

**Error queue:**
- Failed sideloads logged to `migration_errors` table or CSV with source path, error code, timestamp
- Failed inserts logged similarly
- Both queues reviewed and cleared before production cutover sign-off

---

## Assumption Register

### VERIFIED (confirmed from the brief)
- 4,800 articles with title, body HTML, canonical URL, author username, created/updated dates, status
- 900 staff profiles with department, office location, headshot path, biography
- Topic, audience, region taxonomies; multi-vocabulary term assignment is possible
- Duplicate terms exist including "kids", "children", "youth"
- Media exported separately; body HTML contains old relative paths and CDN URLs
- Revision history exists in source DB but no export is available
- Author resolution has three dispositions: existing WP user, new WP user, archived byline

### REASONABLE (working assumptions, low risk of being wrong)
- Source statuses map to a small set matching WordPress publish/draft/private with no exotic custom statuses
- Article canonical URLs are same-domain
- Headshot files are standard web image formats (JPEG, PNG, WebP)
- WordPress target is self-hosted with WP-CLI access
- PHP memory limit ≥ 256M for batch sideloads

### FRAGILE (must be resolved before the plan is finalized)

| # | Assumption | Risk if wrong | Resolution |
|---|---|---|---|
| F1 | Source DB schema is known and stable | All field mappings are wrong | Schema dump + 20 sample rows |
| F2 | "Archived byline" has a defined data structure | Co-Authors Plus or `_legacy_byline` meta may not apply | User export with byline field definition |
| F3 | Revision history can be exported in a format suitable for WordPress import | Revisions permanently lost | Revision export schema + row count estimate |
| F4 | Third-party CDN URLs in body HTML can be sideloaded or are intentionally left external | Silent content corruption if sideload fails and URL is rewritten anyway | Audit CDN URL list; explicit sideload vs. leave-as-is decision |
| F5 | Taxonomy deduplication is an editorial, not algorithmic, decision | Distinct audience segments collapsed incorrectly | Editorial sign-off on canonical term mapping table |
| F6 | Author usernames are unique stable identifiers across the source system | Author mismapping on articles | User export with username + email pairs |
| F7 | Article and profile status values are fully enumerable | Unknown statuses cause import failures or wrong visibility | Full status value list from schema audit |
| F8 | Media file paths in the export match paths referenced in body HTML | Path rewrite misses references; broken images post-launch | 50-article path consistency audit |
| F9 | All 4,800 articles share a single export format | Import script needs multi-format handling | Export format confirmation |
| F10 | No article has more than one author | Co-Authors Plus is not needed | Schema confirmation of author field cardinality |

---

## Test Strategy

**Fixture sets** — 5 representative edge cases:

1. Article with nested tables, inline styles, one relative image path, one CDN image URL
2. Article with an ambiguously mapped status (e.g., `archived`)
3. Staff profile with a null headshot path
4. Article assigned to all three taxonomies, including a term that was deduplicated
5. Article whose source author username maps to the archived-byline disposition

For each fixture:
- Dry-run: assert insert vs. update decision is logged correctly
- Live import: assert `_source_id` meta set, `post_status` correct, term assignments match mapping table, `post_author` non-zero or `_legacy_byline` meta populated
- Rerun: assert no duplicate post created; assert `post_modified` updates only when source `updated_date` changed
- Media assertions: assert `post_content` contains no old relative paths; CDN URLs either resolve to WordPress-hosted URLs or are documented as intentional external references

**Smoke assertions (post-import, automated):**
- `wp post list --post_type=article --format=count` = expected count ± 0
- `wp post list --post_type=staff_profile --format=count` = expected count ± 0
- `wp term list topic --format=count` = expected deduplicated count
- HTTP 301 + 200 chain on 20 sampled canonical URLs

**Rerun test:**
- Import all 4,800 articles twice → assert count is identical after second run

**Rollback test (staging only):**
- Full import → snapshot → restore → assert post counts return to pre-import state

**Permission tests:**
- Confirm `_source_id` is not in REST API response for article: `curl /wp-json/wp/v2/article/{id}` → assert no `_source_id` field
- Confirm `department` meta requires authentication: unauthenticated PUT to staff profile meta → assert 401

**Launch rehearsal:**
- Full import run on a staging environment identical to production (same PHP version, same WP version, same active plugins)
- Complete validation plan
- Time the run — if >4 hours, route media sideloads through Action Scheduler

---

## Acceptance Criteria

No cutover proceeds without all rows signed off.

| Criterion | Owner | Status |
|---|---|---|
| Source schema dump received and audited | Migration engineer | **BLOCKED** |
| 20 sample article rows validated | Migration engineer | **BLOCKED** |
| 20 sample profile rows validated | Migration engineer | **BLOCKED** |
| Full status value list confirmed | Migration engineer | **BLOCKED** |
| Taxonomy deduplication mapping table signed off | Content editor | **BLOCKED** |
| User export received; author mapping table complete | Migration engineer | **BLOCKED** |
| Byline data structure confirmed; Co-Authors Plus vs. meta decision made | Project lead | **BLOCKED** |
| Revision scope decision made (import or skip) | Project lead | **BLOCKED** |
| Media manifest audited; CDN sideload decision made | Migration engineer | **BLOCKED** |
| Staging import complete with zero critical errors | Migration engineer | — |
| Count checks pass (all content types, taxonomies, media) | Migration engineer | — |
| URL/redirect audit passes (50 sampled canonical URLs) | Migration engineer | — |
| 10 articles + 5 profiles reviewed by content editor | Content editor | — |
| Rollback procedure tested on staging | Migration engineer | — |
| Launch rehearsal timed and performance-checked | Migration engineer | — |
| Production cutover go/no-go | Project lead | — |

**Explicit non-claims:**
- This plan does **not** claim revision fidelity — revisions are out of scope until F3 is resolved.
- This plan does **not** claim all third-party CDN URLs will be sideloaded — depends on F4.
- This plan does **not** claim author resolution is complete — mapping table is a design until F2 and F6 are resolved.
- This plan does **not** claim the taxonomy deduplication is correct — "kids/children/youth" requires editorial sign-off (F5).
- This plan does **not** guarantee zero data loss — it guarantees a known, audited loss surface documented in the assumption register.

---

## Critic Handoff

Invoke `wordpress-migration-critic` with this plan. Specific review prompts:

**Idempotency and identity:**
- Is `_source_id` robust to source ID collisions or reuse across article and profile tables? (Consider prefixing: `article__{source_id}` vs. `profile__{source_id}`)
- Does the `get_posts()` idempotency gate correctly use `posts_per_page => 1` and `post_type` scope to avoid cross-type collisions?

**Media integrity:**
- Does the sideload error path correctly avoid rewriting `post_content` URLs when `media_sideload_image()` returns `WP_Error`?
- Is `wp_update_attachment_metadata()` called after sideload for images that need generated sizes?
- Is `wp_check_filetype()` called before every sideload to reject disallowed MIME types?

**Data transforms:**
- Is `wp_slash()` applied to all `$post_data` arrays before `wp_insert_post()` / `wp_update_post()`? (Missing `wp_slash()` causes silent data corruption on backslash characters.)
- Is `wp_kses_post()` applied to `post_content` before insert, or is it deferred? (Deferred is acceptable if the content team controls the source — but must be documented.)

**Taxonomy:**
- Does `wp_set_object_terms()` use replace vs. append correctly for first-import vs. delta runs?
- Are term IDs confirmed to be from the correct taxonomy before assignment? (Passing a term ID from the wrong taxonomy to `wp_set_object_terms()` creates a silent invalid assignment.)

**Security surface:**
- Is `$wpdb->prepare()` used for any custom SQL that bypasses `get_posts()` (e.g., direct `_source_id` lookups for performance)?
- Is `wp_safe_redirect()` used for all redirect writes?
- Are migration scripts removed or access-restricted on production after launch?

**Assumption register completeness:**
- Are all BLOCKED acceptance criteria treated as hard gates (no executor invocation until resolved), not soft reminders?

**Minimum bar before executor invocation:**
- F1 (source schema), F2 (byline structure), F5 (taxonomy sign-off), and F6 (author usernames) must all move from FRAGILE to VERIFIED before implementation begins.
