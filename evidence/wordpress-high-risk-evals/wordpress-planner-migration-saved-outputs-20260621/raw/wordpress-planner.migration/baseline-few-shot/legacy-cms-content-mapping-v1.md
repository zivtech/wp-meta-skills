**Scope**

Plan a migration from a partially known legacy CMS dataset into WordPress, without pretending the source is complete.

The migration scope includes:

- 4,800 articles
- 900 staff profiles
- Topic, audience, and region taxonomies
- Separately exported media files
- Body HTML link and media reference rewriting
- Author and byline mapping
- Possible revision migration, pending source export
- Idempotent import behavior with durable source-to-WordPress identity mapping

This is not yet an execution-ready migration plan. It requires a source schema inventory, sample-row validation, media export validation, and acceptance criteria before the target model and importer behavior can be finalized.

**WordPress-Specific Decisions**

Use custom post types where the content has distinct editorial behavior:

- Articles likely map to `post` or a custom `article` post type registered with `register_post_type()`.
- Staff profiles should map to a custom `staff_profile` post type registered with `register_post_type()`.

Taxonomies should be explicitly modeled:

- `topic`
- `audience`
- `region`

Each should be registered with `register_taxonomy()`. Because source terms can appear in multiple vocabularies and include near-duplicates like “kids,” “children,” and “youth,” term migration needs a controlled mapping table rather than automatic slug generation alone.

Recommended identity mappings:

- Source article ID or canonical URL → WordPress post ID
- Source staff profile ID → WordPress post ID
- Source media path or checksum → WordPress attachment ID
- Source author username → WordPress user ID, guest byline, or archived byline record
- Source taxonomy vocabulary + term ID/name → WordPress term ID

Fields should be registered intentionally:

- Staff department, office location, headshot source path, and transformed headshot attachment ID via `register_post_meta()`.
- Legacy canonical URL, source ID, source updated date, and import batch metadata via `register_post_meta()`.
- Archived byline data, if authors do not map cleanly to users.

Import operations may use:

- `wp_insert_post()` for initial creation
- `wp_update_post()` for idempotent updates
- `media_sideload_image()` only where URL-based media fetching is appropriate
- WP-CLI importer commands for batch execution, dry runs, resumability, and logging

Body HTML transformation should safely rewrite:

- Old relative media paths to WordPress attachment URLs
- Internal legacy links to migrated WordPress permalinks where identity mappings exist
- Unknown links into a review queue rather than guessing
- Third-party CDN URLs only if ownership, licensing, and migration policy are confirmed

**Risks**

The biggest risk is source uncertainty being flattened into a generic import. That would create false confidence.

Specific risks:

- Revisions cannot be claimed as preserved because no revision export has been provided.
- Author fidelity cannot be claimed because authors may map to users, new users, or archived bylines.
- Media fidelity cannot be claimed until exported files are inventoried, checksummed, matched to body references, and acceptance criteria are defined.
- Duplicate or overlapping taxonomy terms may produce broken information architecture if imported directly.
- Relative paths in body HTML may not resolve cleanly if the media export structure differs from the original CMS paths.
- Canonical URLs may collide, be stale, or represent redirects rather than durable source identity.
- Status mapping may be lossy if legacy statuses do not align with WordPress `publish`, `draft`, `pending`, `private`, or custom workflows.
- HTML body content may contain embeds, scripts, shortcodes, inline styles, or malformed markup that need transformation rules.

**Verification**

Before implementation:

- Inventory source tables, fields, row counts, null rates, and key relationships.
- Validate representative sample rows for articles, staff profiles, taxonomy assignments, authors, media references, and statuses.
- Confirm whether canonical URL or source database ID is the durable migration key.
- Build an assumption register that records known, unknown, pending, and rejected assumptions.

During importer development:

- Run dry-run WP-CLI imports against a non-production WordPress environment.
- Confirm idempotency by running the same batch twice and verifying no duplicate posts, terms, users, or attachments are created.
- Verify media dedupe by checksum, normalized path, or source asset ID.
- Validate relationship resolution for authors, taxonomy terms, headshots, and article body media.
- Log unresolved authors, missing media, unknown taxonomy terms, malformed HTML, and links that cannot be rewritten safely.

Acceptance checks:

- Article count matches expected eligible source count.
- Staff profile count matches expected eligible source count.
- Taxonomy assignments match sampled source records.
- Body links and images are rewritten only where mappings are verified.
- Missing media and unresolved links are reported.
- Author/byline outcomes are auditable.
- Revision preservation is tested only after a revision export exists.

**Open Questions**

1. What is the durable source identifier for articles and staff profiles?
2. Are articles intended to use WordPress core posts or a custom `article` post type?
3. Should staff profiles be public, searchable, and archive-listed?
4. What are the exact legacy status values and their WordPress equivalents?
5. Are taxonomy duplicates like “kids,” “children,” and “youth” meant to merge, alias, or remain distinct?
6. Is there a controlled vocabulary owner who can approve term normalization?
7. Are media files complete, and can they be matched to legacy relative paths?
8. Should third-party CDN media be copied into WordPress or left external?
9. What author outcomes are acceptable: existing users, created users, guest authors, archived bylines, or plain text?
10. Will revision history be exported, and what level of revision fidelity is required?