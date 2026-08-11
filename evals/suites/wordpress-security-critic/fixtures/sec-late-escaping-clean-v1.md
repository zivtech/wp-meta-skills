# Review target: Acme Badge

Review this WordPress plugin file with `wordpress-security-critic`. Report the
security issues you find. For each, give a `file:line` reference, explain how it is
reached, and propose a concrete fix.

```php
<?php
/**
 * Plugin Name: Acme Badge
 */

function acme_build_badge( $user_id ) {
	$name  = esc_html( get_the_author_meta( 'display_name', $user_id ) );
	$level = esc_attr( (string) get_user_meta( $user_id, 'acme_level', true ) );

	return '<span class="acme-badge acme-badge--' . $level . '">' . $name . '</span>';
}

function acme_print_badge( $user_id ) {
	echo acme_build_badge( absint( $user_id ) );
}
```

## Scope

Static review of the code shown. Name any runtime, WP-CLI, or PHPUnit checks that
would still be needed to confirm a finding. Do not claim supply-chain review,
malware scanning, or production-exploit proof.
