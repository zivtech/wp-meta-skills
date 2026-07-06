# Content modeling: CLEAN_CONTROL

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Plan CPTs, taxonomies, registered meta, ACF boundaries, editorial workflow, REST exposure, and search/discovery needs.
Fixture tier: The artifact is mostly sound and should not attract invented findings.

Scenario summary: A Resource Library model uses a Resource CPT, Topic taxonomy, Audience taxonomy, and registered metadata.

Artifact under review:
- Metadata fields include reading_time, external_url, and featured_resource via register_post_meta with auth and sanitize callbacks.
- ACF may provide editor UI but the canonical schema is registered in code and exposed to REST where needed.
- Editorial workflow uses draft, review, and scheduled publish states already supported by the site.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Recognizes sound CPT/taxonomy/meta boundaries.
- Checks REST exposure, search facets, editorial workflow, and field ownership.
- Does not force every field into ACF without schema registration.

A weak or unsafe response likely:
- Treats ACF UI as the whole content model.
- Misses taxonomy vs meta decision points.
- Invents need for custom database tables.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Content modeling domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
