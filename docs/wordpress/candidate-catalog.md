# WordPress Skill Candidate Catalog

Survey date: 2026-06-16.

This catalog records candidate upstream skill sources for WordPress V1 evaluation. It is not an adoption decision. Candidates must pass the evaluation and provenance gates before copied or adapted material enters production skill prompts.

Screening result: `evals/results/wordpress-skill-candidate-eval/2026-06-16-candidate-screening.md`.

Current status: candidate screening is complete enough to preserve reference-only comparators, and the candidate-discrimination arc is closed as directional-internal only. Absolute scoring failed discrimination, blind pairwise did not certify reliable separation from a strong few-shot prompt, and answer-key diagnostics localized the measurable gap to exact WordPress API naming. The full 27-fixture superiority benchmark and any external adopt/adapt/build claim remain blocked unless the measurement target changes.

## Survey Notes

- skills.sh website search was performed on 2026-06-16 using the rendered public page at `https://www.skills.sh/?q=wordpress`, not the skills.sh API. The visible result set contained 74 WordPress-matching rows and is recorded in `skills-sh-website-survey.md`.
- GitHub commit metadata was gathered with `git ls-remote` on 2026-06-16.
- License checks used standard root license filenames on the default branch. Candidates without a verified compatible license are evaluation/reference candidates only, not reuse candidates.
- WordPress/agent-skills states GPL-2.0-or-later in its repository license/readme.

## Candidates

| Candidate | Commit | License | Skill Inventory | Initial Use |
|---|---:|---|---|---|
| [WordPress/agent-skills](https://github.com/WordPress/agent-skills) | `aa735ea7111c7924ee988306bcef70439e17dec9` | GPL-2.0-or-later by LICENSE/readme | skills.sh rows: `blueprint`, `wp-plugin-directory-guidelines`, `wp-abilities-audit`, `wp-abilities-verify`, `wordpress-router`, `wp-plugin-development`, `wp-rest-api`, `wp-block-themes`, `wp-performance`, `wp-block-development`, `wp-project-triage`, `wp-wpcli-and-ops`, `wp-phpstan`, `wp-abilities-api`, `wp-playground`, `wp-interactivity-api`, `wpds` | Primary official reference and comparator |
| [automattic/agent-skills](https://github.com/automattic/agent-skills) | `48d4aa21d0da0e7bda1c7ac155fef2e16b87aa25` | No standard root license found | skills.sh row: `wordpress-router` | Routing comparator only until license verified |
| [automattic/wordpress-agent-skills](https://github.com/automattic/wordpress-agent-skills) | `ea902bd8301564fa33e336c34114ab121f24c800` | No standard root license found | skills.sh rows: `wordpress-block-theming`, `design-systems`, `site-specification` | Block theming/design-system comparator only until license verified |
| [jeffallan/claude-skills](https://github.com/jeffallan/claude-skills) | `e8be415bc94d8d6ebddc2fb50e5d03c6e27d4319` | MIT | skills.sh row: `wordpress-pro` | Broad WordPress-generalist comparator |
| [jezweb/claude-skills](https://github.com/jezweb/claude-skills) | `0aa0f4437e0e70dda1e4e62df3a9d9cb8170f8ba` | MIT | skills.sh rows: `wordpress-elementor`, `wordpress-content`, `wordpress-setup`, `wordpress-plugin-core` | Page-builder, setup, content, and plugin-core comparator |
| [bartekmis/wordpress-performance-best-practises](https://github.com/bartekmis/wordpress-performance-best-practises) | `577a08fb1c157cef1055de450d4550c1af4e0845` | MIT | skills.sh row: `wordpress-performance-best-practices` | Performance critic comparator |
| [mindrally/skills](https://github.com/mindrally/skills) | `05a71308897983093248d719a2ffa1bca61d0768` | Apache-2.0 | skills.sh row: `wordpress` | General WordPress comparator |
| [bobmatnyc/claude-mpm-skills](https://github.com/bobmatnyc/claude-mpm-skills) | `8058595a0f812fd8b7e706c525fb9f9a4e0f2e2d` | MIT | skills.sh rows: `wordpress-security-validation`, `wordpress-block-editor-fse`, `wordpress-advanced-architecture`, `wordpress-plugin-fundamentals`, `wordpress-testing-qa` | Security, architecture, block editor, plugin, and QA comparator |
| [sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills) | `39660b6b4b9eee6dc2accbc4a22b89605d995662` | MIT | skills.sh rows: `wordpress-theme-development`, `wordpress-plugin-development`, `wordpress-woocommerce-development`, `wordpress`, `wordpress penetration testing`, SEO/blogging/conversion helpers | Theme/plugin/WooCommerce/security comparator |
| [elvismdev/claude-wordpress-skills](https://github.com/elvismdev/claude-wordpress-skills) | `0ac0bbd5fd7c2a91f45af8ec3f5282537e52b075` | MIT | `wp-performance-review` | Performance critic comparator |
| [trewknowledge/agent-skills](https://github.com/trewknowledge/agent-skills) | `ac851c91d8b1cd55ca77b7b31e5de8813554bd9b` | No standard root license found | skills.sh row: `wordpress-vip` | WordPress VIP comparator only until license verified |
| [wpacademy/wordpress-dev-skills](https://github.com/wpacademy/wordpress-dev-skills) | `5bb36a5ccab2acc62284025b85df8cb4bea2befb` | GPL-2.0 | skills.sh row: `wp-theme-dev` | Theme executor/critic comparator |
| [0xshe/php-code-audit-skill](https://github.com/0xshe/php-code-audit-skill) | `69d883e7983a09f72fd047a96e2377bee9a95d7e` | No standard root license found | skills.sh row: `php-wordpress-audit` | Security-audit comparator only until license verified |
| [respira-press/agent-skills-wordpress](https://github.com/respira-press/agent-skills-wordpress) | `e39a5c788e5a39d05157f804c8fd0c5a4f5e07a2` | MIT | 35 site-audit, migration, builder-conversion, onboarding, WooCommerce, SEO/AEO, image, and reporting skills | Migration, site audit, and page-builder comparator |
| [jorgerosal/wordpress-skills](https://github.com/jorgerosal/wordpress-skills) | `8c964424d05ba34b3ea5641f7181d4c13829e06f` | MIT | 18 skills including accessibility, ACF/content modeling, admin UI, blocks, CI/CD, headless/WPGraphQL, migrations, performance, PHPStan, Playground, plugins, REST, security, site audit, testing, themes, WooCommerce, WP-CLI | Broad community comparator |

## Evaluation Lanes

1. Raw upstream candidate output.
2. Fair zero-shot and few-shot baselines.
3. Zivtech V1 prototype output after initial build.

## Decision Rules

| Result | Action |
|---|---|
| Candidate wins its domain, has no critical gaps, and passes license/provenance gate | Adopt as reference or reuse with attribution |
| Candidate has strong domain signal but lacks Zivtech protocol/output contract | Adapt into Zivtech format with attribution |
| Candidate underperforms or misses Zivtech consulting needs | Build original Zivtech skill behavior |
| Candidate domain has low client relevance or insufficient evidence | Defer |

## Source Evidence

- The skills.sh website search for `wordpress` returned 74 visible results ranked by relevance, publisher, and installs.
- WordPress/agent-skills `docs/ai-authorship.md` states skills were generated from official WordPress/Gutenberg docs, reviewed by WordPress contributors, tested against WP Bench tasks, and not yet run through a formal evaluation system.
- WordPress 7.0 was verified as the current release on the official WordPress News site before evaluating WP 7.0-aware candidate claims.
