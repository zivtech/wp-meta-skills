# Focused Fixture: Legacy CMS Content Mapping

Plan a migration from a legacy CMS into WordPress. The source data is partially
known and partially missing:

- 4,800 articles with title, body HTML, canonical URL, author username, created
  date, updated date, and status.
- 900 staff profiles with department, office location, headshot file path, and
  biography.
- 3 taxonomies: topic, audience, and region. Source terms can be assigned in
  multiple vocabularies and include duplicates such as "kids", "children", and
  "youth".
- Media files are exported separately; article body HTML references old
  relative paths and a few third-party CDN URLs.
- Revision history exists in the source database, but no export has been
  provided yet.
- Authors may map to existing WordPress users, new WordPress users, or archived
  bylines.

## Expected Planning Focus

- Preserve source uncertainty in an assumption register instead of flattening
  the migration into a generic import plan.
- Define post type, taxonomy, media attachment, author/byline, revision, and
  field-transform mappings.
- Require a source schema inventory and sample-row validation before finalizing
  the target model.
- Include idempotent identity mapping, media dedupe, relationship resolution,
  and safe link rewriting.
- Name WordPress surfaces such as `register_post_type()`,
  `register_taxonomy()`, `register_post_meta()`, `wp_insert_post()`,
  `media_sideload_image()`, `wp_update_post()`, and WP-CLI importer commands
  where relevant.

## Required Boundaries

Do not claim the migration can preserve revisions, authors, or media fidelity
until the missing source exports and acceptance criteria exist.
