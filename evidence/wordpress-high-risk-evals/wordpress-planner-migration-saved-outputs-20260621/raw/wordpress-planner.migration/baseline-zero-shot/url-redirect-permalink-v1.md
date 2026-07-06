This task is planning-heavy and should be treated as a migration URL preservation workstream, not a generic “configure redirects” item.

A safe WordPress migration plan should require these deliverables:

1. **Permalink Model**
   - Confirm WordPress permalink settings separately from redirects.
   - Required targets:
     - Articles: `/insights/%postname%/`
     - Staff profiles: `/people/%slug%/`
   - Validate with:
     - `wp option get permalink_structure`
     - Custom post type rewrite settings for staff profiles
     - `wp rewrite flush` after final rewrite configuration
   - Use `wp search-replace` only for internal URL references after the target URL model is finalized.

2. **Redirect Map Creation**
   - Build a normalized source inventory from:
     - 12,000 crawled URLs with status codes
     - 8,200 canonical legacy CMS URLs
     - Known aliases, vanity URLs, media URLs, and attachment URLs if available
   - Map each legacy URL to one of:
     - Exact WordPress destination
     - Intentional 410/404
     - Manual review
     - Deferred pending SEO metadata or stakeholder decision
   - Do not assume the 8,200 canonical URLs cover all live URLs.

3. **Acceptance Criteria**
   The launch team’s “all redirects handled” is not actionable yet. Require approval on:
   - Minimum redirect coverage for known 200 URLs
   - Maximum redirect chain length, ideally zero chains beyond one hop
   - Whether query strings are preserved, stripped, or selectively mapped
   - Treatment of tracking parameters
   - Treatment of legacy search/filter URLs
   - Handling of media, PDFs, images, and attachment pages
   - Acceptable 404 rate after launch
   - 404 sampling cadence and escalation process

4. **Validation Process**
   - Pre-launch crawl current site and staging WordPress.
   - Compare:
     - Legacy 200 URLs with mapped destinations
     - Target status codes
     - Redirect chains
     - Final destination canonical tags once SEO metadata is available
     - Internal links still pointing at legacy URLs
   - Use crawl tooling such as Screaming Frog, Sitebulb, or equivalent CLI/API crawl tooling.
   - Export redirect rules from the chosen WordPress redirect system/plugin and validate them outside the admin UI where possible.
   - If using a plugin such as Redirection, plan import/export testing and document the exact import format and rollback process.

5. **Canonical And SEO Uncertainty**
   - SEO metadata export is pending, so canonical URL decisions are not final.
   - The plan should explicitly mark canonical tags, meta titles/descriptions, and any legacy canonical overrides as unresolved until that export is reviewed.
   - Do not claim search-equity preservation yet.

6. **Launch And Post-Launch**
   - Freeze redirect map before launch.
   - Run a final crawl against production immediately after DNS/traffic cutover.
   - Sample 404s from server logs, analytics, Search Console, and redirect plugin logs.
   - Fix high-value misses quickly, but avoid creating chains or broad pattern redirects that mask mapping errors.

What this plan should **not** claim: that SEO/search equity is preserved simply because redirects exist. That claim is only defensible after a validated redirect map, pre/post-launch crawl comparison, and stakeholder-approved acceptance criteria.