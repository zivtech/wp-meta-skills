# WordPress Skills Reuse Ledger

No copied upstream passages are included in the initial V1 skill prompts.

The initial prompts are original Zivtech protocols informed by the candidate survey. Skill files include compatible reference notes naming upstream sources that should be used as evaluation comparators or future attribution anchors.

Active policy: direct copied or closely adapted third-party prompt text remains blocked inside `zivtech-meta-skills` until root license handling is standardized. See `license-reuse-policy.md`.

## Reference-Only Entries

| Local Area | Source | Commit | License | Reuse Class | Rationale |
|---|---|---:|---|---|---|
| WordPress planners/executors/critics | WordPress/agent-skills | `aa735ea7111c7924ee988306bcef70439e17dec9` | GPL-2.0-or-later | Reference only | Official coverage map and comparator |
| Performance critic | elvismdev/claude-wordpress-skills | `0ac0bbd5fd7c2a91f45af8ec3f5282537e52b075` | MIT | Reference only | Focused performance-review comparator |
| Migration/page-builder coverage | respira-press/agent-skills-wordpress | `e39a5c788e5a39d05157f804c8fd0c5a4f5e07a2` | MIT | Reference only | Broad site migration and page-builder skill inventory |
| Broad community comparison | jorgerosal/wordpress-skills | `8c964424d05ba34b3ea5641f7181d4c13829e06f` | MIT | Reference only | Broad WordPress skill inventory across ACF, security, CI/CD, REST, and WooCommerce |

## Tooling Dependencies (fetched at install time, never vendored)

The API-existence lint (`evals/harness/wp_api_lint.py`) shells out to a
Composer-installed toolchain pinned by `evals/harness/php-tools/composer.lock`.
Only `composer.json` and `composer.lock` are committed; the `vendor/` tree is
gitignored and fetched by each environment (2026-07-02).

| Package | Version | License | Handling |
|---|---:|---|---|
| phpstan/phpstan | 2.2.3 | MIT | Fetched dependency; invoked as a subprocess |
| php-stubs/wordpress-stubs | 7.0.0 | MIT | Fetched dependency; loaded by PHPStan as scan files |
| johnbillion/wp-compat | 1.5.0 | MIT | Fetched dependency; PHPStan rule set plus `symbols.json` used for did-you-mean suggestions |
| wp-hooks/wordpress-core | 1.12.0 | GPL-3.0 | Transitive dependency of wp-compat, consumed inside the fetched `vendor/` tree at analysis time — by wp-compat's PHPStan rules and (since the 2026-07-02 phase-2 merge) by the lint's hooks engine, which reads `vendor/wp-hooks/wordpress-core/hooks/*.json` directly at run time. Update 2026-07-03: the repository relicensed to GPL-3.0, so committing a hooks snapshot is now license-compatible if ever wanted (with a ledger entry); the vendor-side consumption remains the current implementation. |

## Committed Data Extraction Entries

`evals/harness/data/wp-symbols.json` (built by `scripts/build-wp-symbol-db.py`)
is a committed, MIT-sources-only snapshot for the lint's native engine. It
contains symbol names, deprecation versions, successor API names, and
introduced-in versions — no prose, descriptions, or code are copied.

| Data | Source | Ref | License | Extracted facts |
|---|---|---|---|---|
| Function/class existence, `@deprecated` versions and replacements | php-stubs/wordpress-stubs | `v7.0.0` | MIT | Symbol names, deprecation version, successor API name (via PHP reflection over the stubs) |
| Per-function `since` versions | johnbillion/wp-compat `symbols.json` | `trunk` (WP 7.0 data) | MIT | Function name → introduced-in version |
