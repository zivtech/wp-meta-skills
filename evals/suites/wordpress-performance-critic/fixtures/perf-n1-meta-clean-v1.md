# Review target: Acme Resource Digest

Review this WordPress plugin file with `wordpress-performance-critic`. Report
any performance risks you find, with a `file:line` reference and a concrete
fix for each. If the code is sound, say so explicitly and note what you
checked.

```php
<?php
/**
 * Plugin Name: Acme Resource Digest
 * Description: Render a compact digest of resource posts matched to a set of topics.
 */

function acme_render_resource_digest( array $topic_ids ) {
	$query = new WP_Query(
		array(
			'post_type'      => 'resource',
			'post_status'    => 'publish',
			'posts_per_page' => 50,
			'no_found_rows'  => true,
			'meta_query'     => array(
				array(
					'key'     => '_acme_topic_id',
					'value'   => $topic_ids,
					'compare' => 'IN',
				),
			),
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
WP-CLI, or a PHPUnit query-count assertion) that would still be needed to
confirm an assessment either way. Do not claim production query volume or
latency impact without real traffic or environment data.
