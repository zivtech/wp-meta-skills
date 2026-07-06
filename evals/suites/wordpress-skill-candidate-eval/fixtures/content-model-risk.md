# Content modeling: HAS_RISK

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Plan CPTs, taxonomies, registered meta, ACF boundaries, editorial workflow, REST exposure, and search/discovery needs.
Fixture tier: The artifact includes non-obvious WordPress risks that a strong skill should find and calibrate.

Scenario summary: A migration plan stores program data as JSON blobs inside post_content and uses ACF options for repeatable locations.

Artifact under review:
- Programs need filtering by audience, service area, eligibility, and location.
- The plan stores all values in a serialized block comment and a global ACF option page.
- Editors need revisions and bulk updates, and the public API must expose selected fields.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Flags filterability, revisions, API exposure, and editorial maintenance risks.
- Proposes CPT, taxonomies, registered post meta, or custom table only if scale demands it.
- Calls out migration and search index implications.

A weak or unsafe response likely:
- Accepts post_content JSON because blocks can store attributes.
- Misses global option misuse for repeatable content.
- Ignores API exposure and bulk editing.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Content modeling domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
