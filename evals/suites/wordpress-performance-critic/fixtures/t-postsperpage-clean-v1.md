# Review target: Acme Testimonials

Review this WordPress plugin file with `wordpress-performance-critic`. Report the
performance issues you find. For each, give a `file:line` reference, explain how it
is reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Testimonials
 * Description: Render the ten most recent testimonials on the homepage.
 */

function acme_render_recent_testimonials() {
	$testimonials = get_posts(
		array(
			'post_type'      => 'acme_testimonial',
			'post_status'    => 'publish',
			'posts_per_page' => 10,
			'orderby'        => 'date',
			'order'          => 'DESC',
		)
	);

	$html = '<div class="acme-testimonials">';

	foreach ( $testimonials as $testimonial ) {
		$html .= '<blockquote>' . esc_html( $testimonial->post_title ) . '</blockquote>';
	}

	return $html . '</div>';
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or measurement checks
(for example Query Monitor or a controlled benchmark) that would still be needed to
confirm a finding. Do not claim production latency, capacity, or cost impact
without real environment data.
