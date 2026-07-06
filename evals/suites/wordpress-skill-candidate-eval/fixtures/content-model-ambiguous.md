# Content modeling: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Plan CPTs, taxonomies, registered meta, ACF boundaries, editorial workflow, REST exposure, and search/discovery needs.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: The client calls every offering a Program, but some behave like landing pages, some like events, and some like evergreen services.

Artifact under review:
- Marketing wants flexible page design for each Program.
- Search needs consistent filters for age, geography, and eligibility.
- Editors are split between one CPT with fields and separate CPTs by program type.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Frames one CPT plus taxonomy/type fields vs multiple CPTs and page hybrids.
- Asks about lifecycle, search, permissions, URLs, and reporting.
- Avoids premature modeling until content samples are classified.

A weak or unsafe response likely:
- Creates one CPT solely because the client uses one noun.
- Splits CPTs solely by layout differences.
- Ignores search/filter requirements.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Content modeling domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
