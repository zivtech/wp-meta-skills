# Performance and operations: CALIBRATION_TRAP

A Zivtech engineer is evaluating a WordPress task for the candidate WordPress skill suite.

Domain focus: Query cost, indexing, meta vs. taxonomy, calibrated performance review.
Fixture tier: Mostly-sound code with ONE genuine bottleneck surrounded by tempting-but-correct patterns. A strong reviewer catches the real issue AND resists flagging the sound ones; a weak reviewer either misses the real issue or over-flags the decoys.

Scenario summary: A listing archive filters by city and region using `meta_query` `LIKE` on unindexed postmeta, while its caching, asset loading, and image handling are already correct.

Artifact under review:

```php
$args = array(
    'post_type'      => 'listing',
    'posts_per_page' => 20,
    'no_found_rows'  => true,
    'meta_query'     => array(
        array( 'key' => 'city',   'value' => $city,   'compare' => 'LIKE' ),
        array( 'key' => 'region', 'value' => $region, 'compare' => 'LIKE' ),
    ),
);
$q = new WP_Query( $args );   // 'city' and 'region' are postmeta, not indexed
```

Also in the template (provided for context):
- External pricing is fetched once and stored in a 12-hour transient.
- The listing script/style are enqueued only on this template via the block's `render` callback.
- Images use `wp_get_attachment_image()` with core `srcset`/`sizes`.

Target platform constraints:
- WordPress 6.8+ unless the candidate explicitly flags version uncertainty.
- PHP 8.2+.
- No production secrets in examples.
- No destructive production WP-CLI, SQL, or filesystem commands without backup, staging, and dry-run guidance.

A strong candidate response should:
- Identify the two `LIKE` comparisons on unindexed postmeta (`city`, `region`) as the real bottleneck — full meta scans / filesort that degrade with row count.
- Recommend modeling `city`/`region` as taxonomies (or an indexed column) for filterable facets instead of `meta_query` `LIKE`, and measuring with Query Monitor.
- Explicitly affirm the transient caching, conditional enqueue, and core responsive images as sound (do not "fix" them).

A weak or unsafe response likely:
- Misses the meta_query cost and instead flags the cached external call, the enqueue, or the images.
- Recommends disabling core responsive images or adding caching where it already exists.
- Calls `no_found_rows => true` a bug (it is correct here).

Evaluation task: compare the candidate response against this fixture and decide whether it demonstrates high-quality WordPress skill behavior for the Performance and operations domain. Reward catching the single real bottleneck, the taxonomy/index remediation, calibrated affirmation of sound patterns, and measurement. Penalize invented bottlenecks, generic CMS advice, and destructive production profiling.
