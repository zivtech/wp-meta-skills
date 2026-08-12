# Review target: Acme Resource Digest

Review this WordPress plugin file with `wordpress-performance-critic`. Report
the performance risks you find. For each, give a `file:line` reference,
explain how it is reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Resource Digest
 * Description: Render a compact digest of the latest resource posts.
 */

function acme_render_resource_digest() {
	$query = new WP_Query(
		array(
			'post_type'              => 'resource',
			'post_status'            => 'publish',
			'posts_per_page'         => 50,
			'no_found_rows'          => true,
			'update_post_meta_cache' => false,
		)
	);

	$rows = array();

	foreach ( $query->posts as $post ) {
		$duration = get_post_meta( $post->ID, '_acme_duration_minutes', true );
		$rows[]   = sprintf(
			'<li>%1$s <span class="acme-duration">%2$s min</span></li>',
			esc_html( get_the_title( $post ) ),
			esc_html( $duration )
		);
	}

	return '<ul class="acme-resource-digest">' . implode( '', $rows ) . '</ul>';
}
```

## Scope

Static review of the code shown. Name any measurement (Query Monitor,
WP-CLI, a PHPUnit query-count assertion, or a controlled benchmark) that
would still be needed to confirm a finding. Do not claim production query
volume or latency impact without real traffic or environment data.
