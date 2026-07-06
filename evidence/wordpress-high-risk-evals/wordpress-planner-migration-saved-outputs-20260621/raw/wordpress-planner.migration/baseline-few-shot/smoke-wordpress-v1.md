**Scope**

Plan a builder-to-Gutenberg migration for a WordPress site, including:

- Migrating page/post content from a builder format into native Gutenberg blocks.
- Preserving URLs where possible.
- Defining redirects for changed URLs.
- Migrating or re-linking media assets.
- Maintaining SEO-critical metadata, headings, internal links, alt text, and canonical behavior.
- Producing a handoff suitable for downstream implementation and review.

Assumptions:

- The source site is WordPress.
- The target editing experience is native Gutenberg, not another page builder.
- Redirects are required because some URLs may change during content restructuring.
- Media may include images, PDFs, embeds, and builder-managed assets.
- No production commands should be run from the plan itself.

**WordPress-Specific Decisions**

Use WordPress-native structures wherever feasible:

- Map builder layouts to Gutenberg core blocks first.
- Use custom blocks only when the design or behavior cannot be represented cleanly with core blocks, patterns, reusable blocks, or block variations.
- Preserve post IDs only if the migration approach allows it safely; otherwise preserve URLs through redirects and canonical cleanup.
- Use the WordPress media library as the target system of record for migrated media.
- Preserve attachment metadata, alt text, captions, titles, and file references where available.
- Use WordPress redirect handling through a vetted plugin, server configuration, or application-level redirect layer, depending on the hosting environment.
- Avoid direct database rewrites unless there is a reviewed migration script, backups, staging validation, and rollback path.

Downstream handoff:

- Planner: `wordpress-planner.migration`
- Executor: WordPress migration executor or implementation agent
- Critic: WordPress critic, SEO critic, and QA critic as applicable

**Risks**

- Builder content may contain shortcodes, serialized data, inline styles, or proprietary modules that do not map cleanly to Gutenberg.
- Visual parity may be incomplete if the builder relied on custom responsive behavior.
- Media references may break if URLs are hardcoded inside builder fields.
- Redirect gaps can cause SEO loss, broken backlinks, or analytics discontinuity.
- Rewriting content without preserving metadata can damage accessibility and search visibility.
- Direct production migration without staging validation risks data loss or public regressions.
- Claims about speed, SEO gains, or performance improvements are unsupported unless measured before and after.

**Verification**

Verify in staging before production:

- Sample migrated pages across all major builder templates.
- Gutenberg editability without relying on legacy builder code.
- Frontend rendering on desktop and mobile.
- Media loads from the WordPress media library or approved CDN.
- Alt text, captions, embeds, and downloadable files remain intact.
- Redirect map covers all changed URLs.
- Internal links resolve without chains or loops.
- Canonicals, titles, meta descriptions, Open Graph data, and structured data remain valid.
- XML sitemap reflects final URLs.
- No critical PHP errors, JavaScript errors, or block validation errors.
- Rollback plan exists before launch.

**Open Questions**

- Which builder is the source system?
- How many posts, pages, custom post types, and templates are in scope?
- Are URLs expected to remain identical, or is an IA restructure planned?
- Which SEO plugin or metadata system is currently used?
- Are media files local, CDN-hosted, externally embedded, or mixed?
- Are there custom post types, ACF fields, shortcodes, or theme-specific builder integrations?
- Is the migration expected to prioritize visual parity, editorial maintainability, performance, or all three?
- Who owns final redirect approval and post-launch monitoring?