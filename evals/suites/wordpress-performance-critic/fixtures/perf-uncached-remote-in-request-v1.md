# Review target: Acme Status Badge

Review this WordPress plugin file with `wordpress-performance-critic`. Report
the performance risks you find. For each, give a `file:line` reference,
explain how it is reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Status Badge
 * Description: Show a live upstream status badge via a shortcode.
 */

add_shortcode( 'acme_status_badge', 'acme_render_status_badge' );

function acme_render_status_badge( $atts ) {
	$atts = shortcode_atts(
		array(
			'service' => 'api',
		),
		$atts,
		'acme_status_badge'
	);

	$response = wp_remote_get(
		'https://status.acme-example.com/api/v1/services/' . rawurlencode( $atts['service'] ),
		array(
			'timeout' => 5,
		)
	);

	if ( is_wp_error( $response ) ) {
		return '<span class="acme-status acme-status--unknown">' . esc_html__( 'Status unavailable', 'acme' ) . '</span>';
	}

	$body  = json_decode( wp_remote_retrieve_body( $response ), true );
	$state = isset( $body['state'] ) ? sanitize_key( $body['state'] ) : 'unknown';

	return sprintf(
		'<span class="acme-status acme-status--%1$s">%2$s</span>',
		esc_attr( $state ),
		esc_html( ucfirst( $state ) )
	);
}
```

## Scope

Static review of the code shown. Name any measurement (Query Monitor's HTTP
API panel, a load test, or a PHPUnit test with a mocked HTTP transport) that
would still be needed to confirm a finding. Do not claim production latency
or outage impact without real traffic or upstream data.
