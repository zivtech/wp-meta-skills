# Block development: MIGRATION_SUBTLE

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Static block serialization, `deprecated` migrations, block validation, content safety.
Fixture tier: A breaking block change that LOOKS handled because a migration shipped — but the migration touches a setting, not block validation, so existing posts will silently break. A reviewer that equates "a migration exists" with "handled" will miss it.

Scenario summary: A static block's v2 renames an attribute and changes its saved markup. A migration was added on activation, but no `deprecated` entry was registered.

Artifact under review:

```php
// v1 saved markup in post_content:
//   <section class="card"><h2>{heading}</h2><p>{body}</p></section>
//
// v2 save() now emits:
//   <div class="acme-card"><h3>{title}</h3><p>{body}</p></div>
//   (attribute "heading" renamed to "title"; wrapper + tag changed)

function acme_card_migrate() {
    if ( get_option( 'acme_card_v2' ) ) {
        return;
    }
    update_option( 'acme_card_default_style', 'modern' ); // updates a plugin setting only
    update_option( 'acme_card_v2', 1 );
}
register_activation_hook( __FILE__, 'acme_card_migrate' );

// registerBlockType( 'acme/card', { ... save, /* no deprecated: [] */ } );
```

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Identify that with no `deprecated` array, every existing post containing the v1 block will fail block validation ("this block contains unexpected or invalid content") because v2 `save()` no longer matches stored markup.
- Point out that the activation migration only updates a setting and does nothing for block markup/validation — "a migration exists" does not mean the breaking change is handled.
- Require a `deprecated` entry mapping v1 attributes/markup to v2 as the correct fix, not a bulk `post_content` rewrite.

A weak or unsafe response likely:
- Concludes the change is safe because a migration script is present.
- Recommends a blind find/replace of `post_content` as the remedy.
- Treats the attribute rename as a cosmetic refactor with no compatibility impact.

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Block development domain. Reward identifying the validation break, distinguishing the setting-migration from a deprecation path, and the correct `deprecated`-array fix. Penalize "migration exists = handled" reasoning, destructive `post_content` rewrites, and invented issues.
