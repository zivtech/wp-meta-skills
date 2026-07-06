**Scope**

Plan the URL preservation workstream for a migration into WordPress, covering:

- Target permalink rules for WordPress content.
- Redirect-map creation from legacy URLs to WordPress URLs.
- Validation criteria for redirect coverage and behavior.
- Pre-launch and post-launch crawl comparison.
- Handling of canonical URLs, query strings, media URLs, aliases, chains, and 404s.

This is not a guarantee of search-equity preservation. That claim would require a validated redirect map, stakeholder-approved acceptance criteria, and crawl evidence before and after launch.

**WordPress-Specific Decisions**

Permalink model should be designed separately from redirect implementation.

For WordPress URLs:

- Articles should use `/insights/%postname%/`.
- Staff profiles should use `/people/%slug%/`.
- Landing pages need a separately defined URL pattern, especially if they overlap with legacy top-level paths.
- Confirm WordPress permalink settings with `wp option get permalink_structure`.
- Apply permalink changes through WordPress settings or configuration, then flush rewrites with `wp rewrite flush`.
- Avoid using redirects to compensate for an unstable target permalink model.

Redirect implementation should be based on a generated and reviewed redirect map, not ad hoc plugin entries.

Possible WordPress redirect surfaces:

- A redirect plugin with CSV import/export support.
- Server-level redirects if the hosting platform supports managed rules.
- Custom rewrite handling only if plugin/server options cannot meet requirements.

If content bodies or metadata contain legacy absolute URLs, use controlled search/replace after backups and review, for example with `wp search-replace`, but this is separate from external redirects.

**Redirect-Map Process**

Create a single redirect source of truth with at least:

- Legacy URL.
- Legacy status code from crawl.
- Canonical legacy URL, if known.
- Target WordPress URL.
- Content type.
- Match type: exact, pattern, query-aware, media, retired.
- Redirect status: usually 301 for permanent moves.
- Confidence level.
- Notes or unresolved issue.

Input sources:

- 12,000 crawled URLs with status codes.
- 8,200 canonical content URLs from the legacy CMS.
- WordPress target content inventory.
- Pending SEO metadata export when available.
- Any known vanity URLs, campaign URLs, historical aliases, PDFs, and media paths.

Acceptance criteria should be defined before implementation. At minimum:

- 100% of canonical legacy content URLs either redirect to a valid WordPress equivalent or are explicitly approved as intentionally retired.
- No redirect chains beyond the agreed limit, preferably zero chains.
- No redirect loops.
- Redirect targets return 200-class responses.
- Query-string policy is documented and tested.
- Media and attachment URL policy is documented.
- A sampled set of 404s is reviewed after launch.
- Pre-launch and post-launch crawl deltas are reviewed with stakeholders.

**Canonical URL Decisions**

Canonical handling is currently uncertain because the SEO metadata export is pending.

Decisions needed:

- Whether legacy canonical URLs override crawled URL variants.
- Whether duplicate legacy URLs collapse into one WordPress target.
- How WordPress canonical tags will be generated for posts, landing pages, and staff profiles.
- Whether SEO metadata migration will set canonical URLs explicitly or rely on WordPress/SEO plugin defaults.

Do not finalize redirect confidence for duplicate or alias URLs until canonical metadata and legacy alias behavior are reviewed.

**Query Strings**

Define query-string behavior explicitly.

Common categories:

- Tracking parameters such as `utm_*`: usually ignored while preserving the clean target.
- Search/filter parameters: may need functional equivalents or approved retirement.
- Pagination parameters: need mapping if indexed or linked.
- Legacy IDs or campaign parameters: may need exact-match redirects.
- Unknown query strings: should be sampled from crawl/log data before deciding.

Acceptance criteria should state whether query strings are stripped, preserved, matched exactly, or ignored by parameter class.

**Attachments And Media URLs**

Media URLs need their own policy because they may not map cleanly to WordPress posts.

Decisions:

- Redirect legacy PDFs/images to imported WordPress media files where equivalent assets exist.
- Redirect replaced assets to the closest landing/content page only with stakeholder approval.
- Return 404/410 for intentionally retired files if approved.
- Include high-value media URLs from crawl data and analytics if available.

Do not assume all attachment URLs are covered by content redirects.

**Risks**

- “All redirects handled” is not actionable without acceptance criteria.
- The 12,000 crawled URLs and 8,200 canonical URLs may not include historical aliases, campaign URLs, backlinks, or URLs blocked from crawling.
- SEO metadata is pending, so canonical decisions may change.
- WordPress slug generation may produce collisions or changed slugs unless controlled during migration.
- Redirect chains may be introduced if legacy redirects are imported without normalization.
- Query-string behavior can cause lost campaign, search, or indexed URL handling if not specified.
- Media URLs may be missed if only content nodes are mapped.
- `wp rewrite flush` fixes rewrite registration, but it does not validate redirect coverage.

**Verification**

Before launch:

- Confirm WordPress permalink settings with `wp option get permalink_structure`.
- Confirm article and staff profile URLs match required patterns.
- Generate the redirect map from crawl, canonical CSV, and migrated WordPress URLs.
- Validate all redirect targets in a crawl tool.
- Check for loops, chains, 404 targets, 500s, and wrong content-type targets.
- Export redirect rules from the chosen plugin or platform and compare against the approved map.
- Run a pre-launch crawl against staging if accessible.
- Spot-check representative posts, landing pages, staff profiles, media URLs, query-string cases, and retired URLs.

At launch:

- Apply/import redirects through the approved WordPress/plugin/platform mechanism.
- Flush rewrite rules with `wp rewrite flush` only after permalink/rewrite changes are deployed.
- Avoid broad unsafe production commands without backups, dry runs, and approval.

After launch:

- Run a full crawl of legacy URLs against production.
- Compare results against the approved redirect map.
- Sample production 404s from logs or analytics.
- Review redirect chains and unexpected query-string behavior.
- Capture exceptions and route them through an agreed remediation process.

**Open Questions**

- What does “all redirects handled” mean numerically and operationally?
- Are retired URLs allowed to return 404 or 410, or must every known URL redirect?
- What is the maximum acceptable redirect-chain length?
- Should query strings be preserved, stripped, or matched by parameter type?
- Are media and attachment URLs in scope?
- Are legacy vanity URLs, aliases, and campaign URLs available outside the crawl?
- Which WordPress SEO plugin or canonical-tag system will be used?
- Who approves unresolved mappings and intentionally retired URLs?
- What crawl tool and reporting format will be used for acceptance?
- Are server-level redirects available, or must implementation happen inside WordPress?