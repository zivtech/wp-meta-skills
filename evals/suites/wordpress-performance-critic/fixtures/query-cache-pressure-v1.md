# Focused Fixture: Query And Cache Pressure

Review the following WordPress implementation excerpt with
`wordpress-performance-critic`. The review target is query shape, cache
strategy, and measurement discipline. Do not treat every `WP_Query` as a defect;
identify the specific risks that can be measured.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Related Resources
 */

function acme_render_related_resources( $topic_ids ) {
	$html = '<ul class="acme-related-resources">';

	foreach ( $topic_ids as $topic_id ) {
		$query = new WP_Query(
			array(
				'post_type'      => 'resource',
				'posts_per_page' => 10,
				'meta_query'     => array(
					array(
						'key'     => '_acme_topic_id',
						'value'   => $topic_id,
						'compare' => '=',
					),
				),
			)
		);

		foreach ( $query->posts as $post ) {
			$html .= '<li>' . esc_html( get_the_title( $post ) ) . '</li>';
		}
	}

	return $html . '</ul>';
}
```

## Expected Review Focus

- Detect N+1 query shape from one `WP_Query` per topic in a render path.
- Require measurement before claiming impact: Query Monitor, database query
  logs, `wp profile` where available, or a controlled page-render benchmark.
- Identify avoidable query costs such as default found-row counts and cache
  priming when only IDs or titles are needed.
- Recommend concrete WordPress surfaces such as `no_found_rows`,
  `fields => 'ids'`, `update_post_meta_cache`, `update_post_term_cache`,
  `pre_get_posts` only where appropriate, and object-cache keys with explicit
  invalidation.
- Avoid the cache-as-fix trap: caching cannot be the only recommendation if the
  query shape itself is unbounded.

## Required Boundaries

Do not claim production latency or capacity impact without real environment
data. Do not require custom tables unless scale evidence and data access
patterns justify that larger architectural move.
