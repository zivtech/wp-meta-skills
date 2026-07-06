## Spec Conformance
Implements the approved Acme Runtime Tested plugin spec with a small pure helper and a PHPUnit suite. It does not add REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, production write commands, or provider credentials. Generated paths: `acme-runtime-tested/acme-runtime-tested.php`, `acme-runtime-tested/includes/mode.php`, `acme-runtime-tested/tests/bootstrap.php`, `acme-runtime-tested/tests/ModeTest.php`, `acme-runtime-tested/phpunit.xml`, `acme-runtime-tested/composer.json`, and `acme-runtime-tested/readme.txt`.

## Generated File Map
- `acme-runtime-tested/acme-runtime-tested.php`
- `acme-runtime-tested/includes/mode.php`
- `acme-runtime-tested/tests/bootstrap.php`
- `acme-runtime-tested/tests/ModeTest.php`
- `acme-runtime-tested/phpunit.xml`
- `acme-runtime-tested/composer.json`
- `acme-runtime-tested/readme.txt`

## Implementation Packets
### acme-runtime-tested/acme-runtime-tested.php
```php
<?php
/**
 * Plugin Name: Acme Runtime Tested
 * Description: Minimal runtime fixture with PHPUnit coverage for WordPress executor certification.
 * Version: 0.1.0
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Text Domain: acme-runtime-tested
 * License: GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 *
 * @package AcmeRuntimeTested
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

require_once __DIR__ . '/includes/mode.php';

register_activation_hook( __FILE__, 'acme_runtime_tested_activate' );
register_deactivation_hook( __FILE__, 'acme_runtime_tested_deactivate' );

/**
 * Create the default runtime mode on activation.
 */
function acme_runtime_tested_activate(): void {
	add_option( 'acme_runtime_tested_mode', 'safe' );
}

/**
 * Clear preview cache on deactivation.
 */
function acme_runtime_tested_deactivate(): void {
	delete_transient( 'acme_runtime_tested_preview' );
}

add_action( 'admin_init', 'acme_runtime_tested_register_settings' );

/**
 * Register the runtime mode setting.
 */
function acme_runtime_tested_register_settings(): void {
	register_setting(
		'acme_runtime_tested',
		'acme_runtime_tested_mode',
		array(
			'type'              => 'string',
			'sanitize_callback' => 'acme_runtime_tested_sanitize_mode',
			'default'           => 'safe',
		)
	);
}

/**
 * Sanitize the runtime mode setting.
 *
 * @param mixed $value Submitted mode value.
 * @return string Normalized mode.
 */
function acme_runtime_tested_sanitize_mode( $value ): string {
	return acme_runtime_tested_normalize_mode( (string) $value );
}

/**
 * Render the current runtime mode for administrators.
 */
function acme_runtime_tested_render_status(): void {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}

	echo esc_html( get_option( 'acme_runtime_tested_mode', 'safe' ) );
}
```

### acme-runtime-tested/includes/mode.php
```php
<?php
/**
 * Runtime mode helpers.
 *
 * @package AcmeRuntimeTested
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Normalize a submitted runtime mode to one supported option.
 *
 * @param string $value Raw submitted mode.
 * @return string Normalized supported mode.
 */
function acme_runtime_tested_normalize_mode( string $value ): string {
	$normalized = function_exists( 'sanitize_key' )
		? sanitize_key( $value )
		: preg_replace( '/[^a-z0-9_-]/', '', strtolower( $value ) );

	if ( ! is_string( $normalized ) || '' === $normalized ) {
		return 'safe';
	}

	$allowed = array( 'safe', 'preview', 'disabled' );
	if ( ! in_array( $normalized, $allowed, true ) ) {
		return 'safe';
	}

	return $normalized;
}
```

### acme-runtime-tested/tests/bootstrap.php
```php
<?php
/**
 * PHPUnit bootstrap for runtime helper tests.
 *
 * @package AcmeRuntimeTested
 */

if ( ! defined( 'ABSPATH' ) ) {
	define( 'ABSPATH', dirname( __DIR__ ) . '/' );
}

require_once dirname( __DIR__ ) . '/includes/mode.php';
```

### acme-runtime-tested/tests/ModeTest.php
```php
<?php
/**
 * Tests for runtime mode helpers.
 *
 * @package AcmeRuntimeTested
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

use PHPUnit\Framework\TestCase;

/**
 * Validate runtime mode normalization.
 */
final class ModeTest extends TestCase {
	/**
	 * Known modes pass through normalized.
	 */
	public function test_known_mode_is_normalized(): void {
		$this->assertSame( 'preview', acme_runtime_tested_normalize_mode( 'Preview' ) );
	}

	/**
	 * Unsupported modes fall back safely.
	 */
	public function test_unknown_mode_falls_back_to_safe(): void {
		$this->assertSame( 'safe', acme_runtime_tested_normalize_mode( 'delete-everything' ) );
	}

	/**
	 * Empty values fall back safely.
	 */
	public function test_empty_mode_falls_back_to_safe(): void {
		$this->assertSame( 'safe', acme_runtime_tested_normalize_mode( '###' ) );
	}
}
```

### acme-runtime-tested/phpunit.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<phpunit colors="false" cacheDirectory=".phpunit.cache" bootstrap="tests/bootstrap.php">
  <testsuites>
    <testsuite name="Acme Runtime Tested">
      <directory>tests</directory>
    </testsuite>
  </testsuites>
</phpunit>
```

### acme-runtime-tested/composer.json
```json
{
  "require-dev": {
    "phpunit/phpunit": "^12.0"
  }
}
```

### acme-runtime-tested/readme.txt
```txt
=== Acme Runtime Tested ===
Contributors: acme
Requires at least: 6.5
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Minimal runtime fixture with PHPUnit coverage for WordPress executor certification.
```

## Security Notes
The plugin has no REST routes, AJAX endpoints, admin-post handlers, SQL, uploads, remote HTTP calls, provider calls, or destructive filesystem commands. The only renderer is guarded by `current_user_can( 'manage_options' )` and escapes output with `esc_html()`. The setting is registered with `register_setting()` and sanitized through `acme_runtime_tested_sanitize_mode()`, which delegates to the covered helper. If a future form writes this option outside the Settings API, add `check_admin_referer()` before processing.

## Deviation Log
No deviations from the approved spec. The helper lives in `includes/mode.php` so PHPUnit can exercise deterministic plugin logic without bootstrapping the full WordPress test suite.

## Verification Notes
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --overwrite` for the deterministic packet, materialization, and static artifact gate.
- Run `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path <generated-plugin-dir>/acme-runtime-tested --phpunit-smoke --write --run-id generated-plugin-phpunit-smoke-YYYYMMDD --timeout-sec 300` to copy the generated plugin into a disposable `wp-env` project, activate it, install Composer dependencies, and require the PHPUnit gate to pass.
- Run PHPCS/WPCS with `phpcs --standard=WordPress --extensions=php <generated-plugin-dir>/acme-runtime-tested` before coding-standards claims.
- Run WP-CLI smoke commands against a disposable environment, such as `wp plugin activate acme-runtime-tested` and `wp option get acme_runtime_tested_mode`.
- Run Plugin Check with `wp plugin check acme-runtime-tested` before release claims.

## Critic Handoff
Send the materialized files, certification output, and PHPUnit runtime smoke output to `wordpress-security-critic` for capability, sanitization, escaping, and lifecycle review, then to `wordpress-critic` for architecture, release-readiness, and operational calibration.
