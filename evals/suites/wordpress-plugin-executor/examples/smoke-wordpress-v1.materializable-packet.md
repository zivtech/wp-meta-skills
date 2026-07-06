## Spec Conformance
Implements the approved Acme Runtime plugin spec without adding REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, build tooling, production write commands, or extra generated files.

## Generated File Map
- `acme-runtime/acme-runtime.php`
- `acme-runtime/readme.txt`

## Implementation Packets
### acme-runtime/acme-runtime.php
```php
<?php
/**
 * Plugin Name: Acme Runtime
 * Description: Minimal runtime fixture for WordPress executor certification.
 * Version: 0.1.0
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Text Domain: acme-runtime
 *
 * @package AcmeRuntime
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

register_activation_hook( __FILE__, 'acme_runtime_activate' );
register_deactivation_hook( __FILE__, 'acme_runtime_deactivate' );

/**
 * Create the default runtime mode on activation.
 */
function acme_runtime_activate() {
	add_option( 'acme_runtime_mode', 'safe' );
}

/**
 * Clear preview cache on deactivation.
 */
function acme_runtime_deactivate() {
	delete_transient( 'acme_runtime_preview' );
}

add_action( 'admin_init', 'acme_runtime_register_settings' );

/**
 * Register the runtime mode setting.
 */
function acme_runtime_register_settings() {
	register_setting(
		'acme_runtime',
		'acme_runtime_mode',
		array(
			'type'              => 'string',
			'sanitize_callback' => 'sanitize_key',
			'default'           => 'safe',
		)
	);
}

/**
 * Render the current runtime mode for administrators.
 */
function acme_runtime_render_status() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}

	echo esc_html( get_option( 'acme_runtime_mode', 'safe' ) );
}
```

### acme-runtime/readme.txt
```txt
=== Acme Runtime ===
Contributors: acme
Requires at least: 6.5
Tested up to: 6.5
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Minimal runtime fixture for WordPress executor certification.
```

## Security Notes
The plugin has no REST routes, AJAX endpoints, admin-post handlers, SQL, uploads, remote HTTP calls, or destructive filesystem commands. The only renderer is guarded by `current_user_can( 'manage_options' )` and escapes output with `esc_html()`. The setting is registered with `register_setting()` and sanitized with `sanitize_key()`. If a future form writes this option, add `check_admin_referer()` before processing.

## Deviation Log
No deviations from the approved spec.

## Verification Notes
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite` for the deterministic packet, materialization, and artifact gate.
- Run PHPCS/WPCS with `phpcs --standard=WordPress --extensions=php <generated-plugin-dir>` before code-review claims.
- Run PHPUnit where tests exist; this smoke fixture has no PHPUnit test files.
- Run WP-CLI smoke commands against a disposable environment, such as `wp plugin activate acme-runtime` and `wp option get acme_runtime_mode`.
- Run Plugin Check with `wp plugin check acme-runtime` before release claims.

## Critic Handoff
Send the materialized files and certification output to `wordpress-security-critic` for capability, sanitization, escaping, and lifecycle review, then to `wordpress-critic` for architecture, release-readiness, and operational calibration.
