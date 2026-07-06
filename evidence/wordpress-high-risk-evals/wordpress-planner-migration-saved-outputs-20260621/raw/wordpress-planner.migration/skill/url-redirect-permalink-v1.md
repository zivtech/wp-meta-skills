## Migration Scope

**Type:** Partial migration — URL preservation, permalink model activation, and redirect implementation for a legacy CMS → WordPress migration. This plan does not cover content transforms, SEO metadata (pending), or post-launch search-equity claims.

**In scope:**
- WordPress permalink structure design and activation for `post`, landing page CPT, and staff profile CPT
- Redirect map construction from 8,200 canonical legacy URLs to WordPress target URLs
- Classification and disposition of the 3,800 crawl URLs not in the canonical CSV
- Redirect implementation strategy, chain prevention, and bulk import
- Query string, attachment/media URL, and canonical URL decisions
- 404 sampling methodology and pre/post-launch crawl comparison design
- Stakeholder-facing acceptance criteria that must be approved before launch

**Explicitly out of scope until unblocked:**
- Search-equity preservation claim — blocked until: (1) validated redirect map, (2) pre/post-launch crawl comparison, (3) stakeholder-approved acceptance criteria
- Canonical tag and title tag validation — blocked until SEO metadata export is delivered
- Organic traffic recovery SLA — cannot be projected without SEO metadata baseline

---

## Current-State Evidence

| Artifact | Count / State | Gaps |
|---|---|---|
| Crawl with status codes | 12,000 URLs | Status code breakdown unknown; share of 2xx vs. 3xx vs. 4xx not yet classified |
| Canonical content CSV | 8,200 URLs | Does not account for 3,800 crawl URLs; legacy alias URLs may be absent |
| WordPress target model | Posts, landing pages, staff profiles | Landing page permalink base not defined |
| Permalink targets | `/insights/%postname%/`, `/people/%slug%/` | No definition for landing page permalink base |
| SEO metadata export | Pending | Canonical tags, title tags, and meta descriptions unavailable |
| Acceptance criteria | None defined | Coverage %, chain limit, query string policy, 404 sampling size all undefined |

**3,800 URL gap:** The difference between the 12,000 crawl and the 8,200 canonical CSV is 32% of crawl URLs. These URLs must be classified before the redirect map is final. Unclassified URLs that go live without a redirect disposition are the primary source of post-launch 404s.

---

## Source Audit

**Step 1 — Classify all 12,000 crawl URLs into disposition buckets.**

Run the crawl CSV through a classification pass (Python script or spreadsheet pivot) using URL pattern matching and status code:

| Bucket | Pattern examples | Disposition |
|---|---|---|
| Canonical content (in CSV) | `/news/article-slug`, `/staff/name` | Redirect to new WordPress URL |
| Already-redirected (301/302 in crawl) | Any URL returning 301 | Resolve to final destination; do not create chain; redirect source → final |
| Legacy 404s (in crawl) | Any URL returning 404 | Document; do not create redirect (no valid destination) |
| Paginated archives | `/category/news/page/2/` | Decision required: redirect-to-root-archive or no redirect |
| Taxonomy archives | `/category/news/`, `/tag/press-release/` | Decision required: map to WordPress taxonomy archive or redirect-to-root |
| Attachment/media URLs | `/wp-content/uploads/...`, `/media/...`, `/files/...` | Decision required: in scope or not |
| Feed URLs | `/feed/`, `/rss/`, `/atom/` | Redirect to WordPress feed `/feed/` or drop |
| System/admin URLs | `/wp-admin/`, `/login`, `/sitemap.xml` | No redirect needed; system URLs regenerate |
| Query string variants | `?p=123`, `?cat=5`, `?utm_source=x` | Covered under query string policy (see Transform section) |
| Unknown/unclassified | Any that don't match above | Flag for manual triage; do not silently drop |

**Step 2 — Slug pattern analysis of 8,200 canonical CSV.**

Extract slug components from legacy URLs via regex. Validate:
- Are slugs unique within each content type? **If not, slug collision detection is required before mapping.**
- Do any slugs contain special characters, non-ASCII, or percent-encoded sequences? These must be normalized before WordPress import.
- Are legacy slugs in the URL or in a separate metadata field? If legacy CMS used numeric IDs in URLs (e.g., `/articles/12345`), slug derivation requires the CSV to include a slug or title field.

**Step 3 — Identify legacy alias URLs not in crawl or CSV.**

Unknown: whether short URLs, campaign landing URLs, mobile subdomain URLs (`m.domain.com`), or social-share shortened URLs exist. Evidence needed: confirm with client whether any redirect domains or URL shorteners have been used. These URLs will produce post-launch 404s if not captured.

---

## Target Mapping

**Permalink structure design — must be activated before redirect map is finalized.**

WordPress generates canonical URLs from registered post type rewrite slugs. The redirect map cannot be validated until WordPress is generating the target URLs correctly.

| Content Type | Post Type | Permalink Target | Registration |
|---|---|---|---|
| Articles | `post` (built-in) | `/insights/%postname%/` | `wp option update permalink_structure '/insights/%postname%/'` |
| Staff Profiles | CPT (e.g., `staff`) | `/people/%slug%/` | `register_post_type('staff', ['rewrite' => ['slug' => 'people', 'with_front' => false]])` |
| Landing Pages | CPT (e.g., `landing_page`) | Unknown | Decision required: define permalink base; owner: [project lead] |

**Verify and activate:**

```bash
# Verify current structure before changing
wp option get permalink_structure

# Set base structure for built-in posts
wp option update permalink_structure '/insights/%postname%/'

# Flush rewrite rules after CPT registration is deployed
wp rewrite flush

# Confirm rules are registered
wp rewrite list | grep -E 'insights|people'
```

Expected output of `wp rewrite list` after flush:
- A rule matching `insights/([^/]+)/?$` → `index.php?name=$matches[1]`
- A rule matching `people/([^/]+)/?$` → `index.php?staff=$matches[1]` (or equivalent CPT query var)

**If these rules are absent after flush, the permalink structure is not registered correctly. Do not proceed to redirect map construction until this is resolved.**

**Slug collision check:**

```bash
# Check for duplicate slugs within post type
wp post list --post_type=post --fields=post_name --format=csv | sort | uniq -d
wp post list --post_type=staff --fields=post_name --format=csv | sort | uniq -d
```

Any duplicates must be resolved (append `-2`, `-3` or merge) before building the redirect map.

---

## Transform And Execution Plan

**Phase order is mandatory. Do not build the redirect map before permalink structure is verified in WordPress.**

### Step 1 — Build the redirect map (8,200 canonical URLs)

Input: `canonical-urls.csv` (legacy) + WordPress post list after content import.

For each row in the canonical CSV:
1. Extract legacy URL (source)
2. Identify content type (article, staff, landing page) — from CSV field or URL pattern
3. Look up corresponding WordPress post by legacy slug or imported ID field
4. Construct WordPress target URL using registered permalink: `get_permalink($post_id)` or `wp post list --post_type=post --fields=ID,post_name,guid`
5. Write row: `source_url, target_url, status_code (301)`

Output: `redirect-map.csv` with columns: `source`, `target`, `status`

**Chain prevention — pre-import check:**

Before importing the redirect map, resolve any sources that are themselves destinations of existing 301/302 entries in the crawl:

```
for each URL in redirect-map sources:
  if URL appears as a redirect destination in the crawl-301-list:
    resolve the chain: source → crawl-destination → final WordPress URL
    replace the intermediate hop with the direct mapping
```

Rule: no entry in the final import map may have a source that is already a redirect destination. Chain depth in production must be 0 (source goes directly to final URL, no intermediate hops).

### Step 2 — Query string handling policy

Decision required: owner [client SEO lead or project lead] must approve one of:

| Option | Behavior | Recommendation |
|---|---|---|
| Strip all query strings | `/old-path/?any=param` → `/insights/new-slug/` (301) | Recommended default |
| Preserve UTM params | UTM query strings pass through; others stripped | If analytics team requires UTM attribution continuity |
| Passthrough all | All query strings forwarded to new URL | Not recommended; pollutes canonical |

The redirect map must define behavior for query string variants before implementation. For `.htaccess` (Apache):

```apache
# Strip query strings on redirect
RewriteCond %{QUERY_STRING} .+
RewriteRule ^old-path/?$ /insights/new-slug/? [R=301,L]
```

The trailing `?` strips the query string from the redirect destination.

### Step 3 — Attachment/media URL handling

Decision required: owner [client] must confirm scope.

If in scope:
- Map legacy media URLs to WordPress `wp-content/uploads/` paths
- If upload directory structure is being preserved during migration (`wp media import --path=...`), the redirect map can reference the preserved paths
- If media is re-uploaded (new upload timestamps), a separate attachment redirect map must be built from the legacy media URL list to the new upload paths
- `wp media list --fields=ID,post_title,guid` provides the WordPress-side attachment URLs for mapping

If out of scope: document explicitly. Any legacy media URL 404 post-launch is a known accepted risk, not a surprise.

### Step 4 — Redirect implementation

For 8,200+ entries, the Redirection plugin (John Godley) with WP-CLI integration is the recommended implementation layer. `.htaccess` at this scale is fragile to manage and risks rule ordering errors.

```bash
# Import redirect map via Redirection plugin WP-CLI
wp redirection import /path/to/redirect-map.csv

# Verify import count matches expected
wp redirection redirects list --format=count

# Export current redirect set for backup before any changes
wp redirection export /path/to/redirect-backup-$(date +%Y%m%d).csv
```

If Redirection plugin WP-CLI is unavailable (version mismatch), use the plugin's built-in CSV import UI at `Tools > Redirection > Import/Export`, then verify count in the dashboard.

Alternative for high-traffic simple cases (articles and staff profiles only): generate `.htaccess` RewriteRules from the CSV and inject into the `# BEGIN WordPress` / `# END WordPress` block managed by `wp rewrite flush`. This approach is faster at request time (Apache-level, before PHP) but harder to manage.

```bash
# After implementing redirects, verify WordPress .htaccess is intact
wp rewrite flush
cat /path/to/public_html/.htaccess | grep -c "RewriteRule"
```

### Step 5 — Internal link rewriting in content

After redirects are in place, rewrite internal links within post content so they point to new URLs directly (avoiding redirect hops for internal navigation):

```bash
# Dry run first — always
wp search-replace 'https://legacy.domain.com/news/' 'https://new.domain.com/insights/' --dry-run --report-changed-only

# Execute after staging validation
wp search-replace 'https://legacy.domain.com/news/' 'https://new.domain.com/insights/' --report-changed-only

# Repeat for each legacy URL pattern that appears in content
```

Run `wp search-replace` for each major legacy URL pattern (articles, staff, landing pages, media). Run dry-run on staging; apply in production only after staging validation passes.

---

## Validation Plan

**All validation must run on staging before production. Pre-launch crawl baseline must be captured before launch.**

### Pre-launch validations

| Check | Command / Method | Pass Criteria |
|---|---|---|
| Permalink structure registered | `wp option get permalink_structure` | Equals `/insights/%postname%/` |
| CPT rewrite rules active | `wp rewrite list \| grep -E 'insights\|people'` | Both patterns present |
| Redirect count matches expected | `wp redirection redirects list --format=count` | ≥ 8,200 (or stakeholder-approved coverage threshold) |
| Chain depth audit | `curl -sI -L --max-redirs 5 <url>` for 200 random sample; count redirect hops | 0 entries with hop count > 1 |
| Article spot-check | Construct 50 random `/insights/{slug}/` URLs; `curl -sI` each | All return 200 |
| Staff profile spot-check | Construct 20 random `/people/{slug}/` URLs; `curl -sI` each | All return 200 |
| Legacy 404 check | Test 50 URLs that were 404 in source crawl | Still return 404; no spurious redirect created |
| Query string check | Test 20 legacy URLs with query strings appended | 301 to canonical; no query string in destination (per approved policy) |
| Media URL check | Test 20 legacy attachment URLs (if in scope) | 301 to new media URL or parent post |
| `wp search-replace` dry-run | `wp search-replace 'legacy.domain.com' 'new.domain.com' --dry-run` | 0 unrewritten internal links remaining in post content |

### Pre-launch crawl baseline (required for post-launch comparison)

Before going live, crawl the full 8,200 canonical URL list against staging:

```bash
# Using wget spider mode
wget --spider --force-html -i canonical-urls.csv -o crawl-staging-baseline.log 2>&1

# Or using curl batch
xargs -a canonical-urls.csv -I{} curl -o /dev/null -s -w "%{url_effective}\t%{http_code}\t%{redirect_url}\n" {}
```

Save output as `crawl-baseline-staging-YYYYMMDD.csv`. This is the reference for post-launch comparison. Without this baseline, the post-launch comparison has no denominator.

### Post-launch validations

| Check | Timing | Command / Method |
|---|---|---|
| Crawl comparison | T+2h | Re-crawl same 8,200 URLs against production; diff status codes vs. baseline |
| 404 error log | T+0 to T+72h | Query Monitor 404 log, or `grep " 404 " /var/log/apache2/access.log` |
| Redirect chain audit | T+24h | Re-run chain depth check on production sample |
| Search Console coverage | T+14d | Monitor "Not found (404)" coverage report; alert on >X% increase |

**Search-equity preservation cannot be claimed until:**
1. Post-launch crawl comparison shows ≤ accepted 404 rate (stakeholder-defined)
2. Search Console coverage report shows no significant increase in 404s over 14 days
3. SEO metadata export is validated (currently blocked)

---

## Rollback And Monitoring

**Backup sequence — must complete before any redirect import or `wp search-replace` execution:**

```bash
# Full database backup
wp db export backup-pre-redirect-import-$(date +%Y%m%d-%H%M).sql

# Verify backup integrity
wp db check

# Backup .htaccess
cp /path/to/public_html/.htaccess /path/to/backups/.htaccess-$(date +%Y%m%d)
```

**Rollback triggers:**
- > 5% of 8,200 canonical URLs returning 404 in post-launch crawl comparison
- Any redirect chain depth > 1 found in production
- Any high-traffic URL (top 100 by crawl link count) returning 404
- SEO metadata not validated by launch date (defers search-equity claim, not necessarily launch)

**Rollback procedure:**

For redirect plugin:
```bash
# Remove all imported redirects
wp redirection redirects delete --all

# Restore from export backup if needed
wp redirection import /path/to/redirect-backup-YYYYMMDD.csv
```

For `.htaccess` rules:
```bash
cp /path/to/backups/.htaccess-YYYYMMDD /path/to/public_html/.htaccess
wp rewrite flush
```

For `wp search-replace` (content link rewriting):
```bash
# Reverse the search-replace
wp search-replace 'https://new.domain.com/insights/' 'https://legacy.domain.com/news/' --report-changed-only
```

For full rollback:
```bash
wp db import backup-pre-redirect-import-YYYYMMDD-HHMM.sql
```

**Post-launch monitoring — minimum 14 days:**
- Daily: check 404 error log for new patterns
- Weekly: Screaming Frog crawl of top 200 URLs, compare to baseline
- Weekly: Search Console coverage report (manual or via API)
- T+14d: close monitoring if 404 rate is within acceptance threshold

**Monitoring ownership — Decision required:** Name the person/team responsible for:
- Daily 404 log review (T+0 to T+14d)
- Search Console monitoring (T+0 to T+30d)
- Redirect map amendments if new 404s are discovered

---

## Assumption Register

**FRAGILE — requires explicit validation before launch:**

1. **Slug uniqueness across content types.** Assumes all 8,200 legacy slugs are globally unique or unique within their content type. If the legacy CMS scoped slugs per section and WordPress requires global uniqueness, the same slug appearing in both `/news/` and `/events/` will collide. Evidence needed: run `sort canonical-urls.csv | uniq -d` on extracted slugs. Owner: migration engineer.

2. **Slug extractability from legacy URLs.** Assumes legacy URLs follow a consistent pattern where the final path segment is a reusable slug. If legacy CMS used numeric IDs (e.g., `/articles/12345`), a slug-to-ID mapping must exist in the CSV or CMS export. Evidence needed: regex analysis of 50 sample URLs from CSV. Owner: migration engineer.

3. **No legacy aliases outside the crawl.** Assumes the 12,000-URL crawl is exhaustive. If short URLs, campaign redirect domains, mobile subdomain URLs, or social-share URLs exist, they are not in scope and will produce post-launch 404s. Evidence needed: client confirmation of all active domains and redirect services. Owner: client.

4. **SEO metadata delivered before launch.** Assumes the pending SEO metadata export will be available with enough runway for canonical tag, title tag, and meta description validation. If not available at launch, the WordPress installation will serve default title patterns and no custom canonicals. This does not block redirect implementation but blocks any search-equity claim. Owner: [client SEO contact] — must provide delivery date.

5. **Landing page permalink base is defined.** Assumes a permalink structure exists for landing pages. It is not defined in the brief. Without it, landing page URLs cannot be included in the redirect map. Decision required: define `rewrite` slug for landing page CPT. Owner: [project lead].

**REASONABLE — lower risk but should be monitored:**

6. Redirection plugin handles 8,200+ entries without performance regression on target hosting. Known to scale to this range; verify with a load test on staging if hosting is shared or resource-constrained.
7. Target WordPress host supports `.htaccess` modification via `wp rewrite flush`. Not true for all managed WordPress hosts (e.g., WP Engine uses Nginx and its own rewrite layer). Evidence needed: confirm host stack.
8. Staff profile slugs are derivable from legacy staff names without collision. Likely true for < 500 staff but must be verified.

**UNKNOWN — unresolvable without client input:**

9. Whether attachment/media URLs are in scope for redirects.
10. Whether legacy paginated archive URLs (`/category/news/page/2/`) require individual redirects or a redirect-to-root-archive policy.
11. Whether query string variants (beyond UTM) exist in the crawl and what the approved handling policy is.
12. Whether any legacy vanity URLs or redirect domains (short.domain.com, campaign.domain.com) are in scope.

---

## Test Strategy

**Fixture sets — build before staging deployment:**

| Set | Contents | Size | Purpose |
|---|---|---|---|
| A | Random article URLs from canonical CSV | 50 | Redirect to `/insights/{slug}/` baseline |
| B | Random staff profile URLs from canonical CSV | 20 | Redirect to `/people/{slug}/` baseline |
| C | URLs returning 301/302 in source crawl | 20 | Chain prevention: source must resolve to final URL in one hop |
| D | Legacy URLs with query strings appended | 20 | Query string stripping policy |
| E | Legacy URLs returning 404 in source crawl | 20 | Must not generate spurious redirects |
| F | Attachment/media URLs (if in scope) | 10 | Media redirect mapping |
| G | High-traffic URLs (top by crawl inbound link count) | 10 | Priority coverage — these matter most for search equity |

**Named tests with exact assertions:**

1. **Permalink registration test.**
   - `wp option get permalink_structure` → assert equals `/insights/%postname%/`
   - `wp rewrite list | grep insights` → assert match exists
   - `wp rewrite list | grep people` → assert match exists
   - Failure: rerun `wp rewrite flush`, re-check. If still absent, CPT `register_post_type` is not deployed.

2. **Redirect map completeness test.**
   - `wc -l redirect-map.csv` → assert ≥ stakeholder-approved coverage count
   - `diff <(cut -d, -f1 canonical-urls.csv | sort) <(cut -d, -f1 redirect-map.csv | sort)` → delta = unmapped URLs; must be zero unless stakeholder has approved exclusions

3. **Chain depth test (Set C).**
   - For each URL in Set C: `curl -sI -L --max-redirs 5 <url> | grep -c "HTTP/"` → assert hop count ≤ 2 (one redirect + one 200); assert final status is 200
   - Failure: chain exists; identify intermediate hop, update redirect map to bypass it

4. **Article redirect correctness test (Set A).**
   - For each URL: `curl -sI <legacy-url>` → assert `HTTP/1.1 301`, `Location: https://new.domain.com/insights/{expected-slug}/`

5. **Staff profile redirect correctness test (Set B).**
   - For each URL: `curl -sI <legacy-url>` → assert `HTTP/1.1 301`, `Location: https://new.domain.com/people/{expected-slug}/`

6. **Legacy 404 non-redirect test (Set E).**
   - For each URL: `curl -sI <legacy-url>` → assert `HTTP/1.1 404`; assert no `Location:` header

7. **Query string strip test (Set D).**
   - For each URL: `curl -sI '<legacy-url>?some=param'` → assert `Location:` does not contain `?` (unless approved passthrough)

8. **Content link rewrite test.**
   - `wp search-replace 'legacy.domain.com' 'new.domain.com' --dry-run` → assert `0 rows` changed (all links already rewritten)

9. **Rerun idempotency test.**
   - Import redirect map → delete all redirects → reimport same map → run tests 4 and 5 again → assert identical results

10. **Launch rehearsal.**
    - Restore production database backup to staging
    - Run full migration sequence: permalink activation → redirect import → `wp search-replace`
    - Run all tests above
    - Record pass/fail per test
    - Document any failures and resolution before go-live decision

---

## Acceptance Criteria

**These criteria are proposed. None are approved. Launch is blocked until stakeholder sign-off on each item.**

| Criterion | Proposed Threshold | Status |
|---|---|---|
| Redirect map coverage | ≥ 95% of 8,200 canonical URLs have a valid redirect entry | Decision required: [client + SEO lead] |
| Redirect chain depth | 0 chains with depth > 1 in production | Hard gate; non-negotiable |
| Post-launch 404 rate | ≤ 1% of canonical URLs returning 404 within 48h of launch | Decision required: [client] |
| Crawl comparison delta | < 2% status code change between pre-launch staging and post-launch production crawl | Decision required: [client] |
| Query string handling | All query string variants redirect to canonical without chains; approved exception list exists | Decision required: [client + SEO lead] |
| SEO metadata validation | All articles serve correct canonical tag | **Blocked** — SEO metadata export not yet available |
| Internal link rewrite | `wp search-replace --dry-run` returns 0 remaining legacy URLs in post content | Hard gate |
| High-traffic URL coverage | 100% of top 100 URLs by inbound link count have validated redirects | Hard gate |

**Search-equity preservation claim requires ALL of the following:**
1. Redirect map coverage criterion is approved and met
2. Post-launch crawl comparison is complete
3. Search Console shows no significant increase in 404 coverage over 14 days post-launch
4. SEO metadata export is validated

Until all four are met, the claim cannot be made. Partial completion does not qualify.

---

## Critic Handoff

This plan should be reviewed against the following open items before staging deployment:

1. **Landing page permalink base** — undefined; blocks landing page redirect map construction
2. **Attachment/media URL scope** — undefined; if in scope, a separate media redirect map is required
3. **Query string policy approval** — required before redirect implementation
4. **SEO metadata delivery timeline** — required before search-equity claim is in scope
5. **Hosting stack confirmation** — affects whether `.htaccess` or Nginx redirect approach is used; affects `wp rewrite flush` behavior
6. **Alias URL discovery** — client must confirm no external redirect domains or short URL services are in use

Verification commands available for critic review:

```bash
wp option get permalink_structure
wp rewrite list
wp rewrite flush
wp redirection redirects list --format=count
wp redirection export /tmp/redirect-audit.csv
wp search-replace 'legacy.domain.com' 'new.domain.com' --dry-run --report-changed-only
wp db check
```

Screaming Frog project file from pre-launch staging crawl must be retained and made available for post-launch comparison. Without it, the crawl comparison gate cannot be executed.
