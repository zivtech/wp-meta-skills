# Review target: Acme Search Highlight

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Search Highlight
 * Description: Show a "you searched for" banner above search results.
 */

add_action( 'template_redirect', 'acme_render_search_banner' );

function acme_render_search_banner() {
	if ( ! is_search() ) {
		return;
	}

	$query = isset( $_GET['s'] ) ? wp_unslash( $_GET['s'] ) : '';

	add_action( 'wp_body_open', function () use ( $query ) {
		if ( '' === $query ) {
			return;
		}

		echo '<div class="acme-search-banner">';
		echo 'You searched for: ' . $query;
		echo '</div>';
	} );
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
