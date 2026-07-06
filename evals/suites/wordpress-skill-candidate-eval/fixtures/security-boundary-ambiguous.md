# Security: AMBIGUOUS_TRADEOFF

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Assess capabilities, nonces, sanitization, escaping, SQL, REST, uploads, and exploitability.
Fixture tier: The request is underspecified and should trigger clarifying assumptions and tradeoff framing.

Scenario summary: A public REST endpoint returns filtered provider listings and may later include appointment availability.

Artifact under review:
- Current response includes public provider name, specialty, location, and permalink.
- Future roadmap may add insurance acceptance and near-real-time availability.
- The team wants caching and public access for SEO but is unsure when authentication becomes necessary.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Separates current public data from future sensitive or operational data.
- Frames privacy, rate limiting, caching, and enumeration risks proportionally.
- Defines a decision gate before availability or user-specific data is exposed.

A weak or unsafe response likely:
- Blocks all public REST access categorically.
- Ignores future data sensitivity.
- Treats SEO and privacy as mutually exclusive without options.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Security domain. Reward evidence-backed WordPress reasoning, calibrated risk calls, and executable next steps. Penalize generic CMS advice, Drupal vocabulary transplant, unsupported version claims, and unsafe production action.
