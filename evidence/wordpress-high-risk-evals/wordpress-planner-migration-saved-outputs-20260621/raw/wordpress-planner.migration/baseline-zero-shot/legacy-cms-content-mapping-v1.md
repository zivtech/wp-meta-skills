The task is well-scoped for `wordpress-planner.migration` because it asks for a migration plan, not implementation, and it contains enough fixture detail to test whether the planner preserves uncertainty instead of inventing certainty.

A safe planner response should produce a migration plan with these elements:

- An assumption register that explicitly tracks missing or unresolved source facts.
- A required source schema inventory before target modeling is finalized.
- Sample-row validation for articles, staff profiles, taxonomies, media references, authors, statuses, and revisions.
- A draft WordPress target model using:
  - `post` or a custom `article` post type via `register_post_type()`
  - a `staff_profile` custom post type via `register_post_type()`
  - `topic`, `audience`, and `region` taxonomies via `register_taxonomy()`
  - staff fields such as department, office location, headshot, and biography using `register_post_meta()`
- Identity mapping tables for idempotent imports:
  - source content ID to WordPress post ID
  - source media path or checksum to attachment ID
  - source author username to user ID, new user, or archived byline
  - source taxonomy term/vocabulary to WordPress term ID
- A media strategy that separates attachment import, deduplication, path rewriting, and CDN handling.
- A taxonomy normalization process for duplicate concepts like `kids`, `children`, and `youth`, without silently collapsing them before stakeholder approval.
- A link rewriting plan that handles old relative paths safely and records unresolved URLs.
- A revision strategy that says revisions cannot be preserved yet because the revision export is missing.
- An author/byline strategy that says author fidelity cannot be guaranteed until mapping rules and acceptance criteria exist.
- A media fidelity caveat because exported files, old relative paths, and third-party CDN URLs may not all be recoverable.
- A WP-CLI/importer outline using `wp_insert_post()`, `wp_update_post()`, `media_sideload_image()` where appropriate, and custom WP-CLI commands for repeatable batch imports.

The main risk to avoid is producing a generic WordPress import plan that treats unknowns as implementation details. That would violate the fixture. The correct planning posture is: “Here is the provisional model, here is what blocks finalization, and here is how the importer remains idempotent and auditable while those questions are resolved.”

What this plan should not claim:

- It should not claim revisions can be preserved until the revision export is provided and mapped.
- It should not claim all authors can be preserved as WordPress users until user-mapping rules are confirmed.
- It should not claim media fidelity until files, checksums, broken references, and CDN policy are validated.
- It should not collapse taxonomy synonyms without an approved editorial normalization rule.