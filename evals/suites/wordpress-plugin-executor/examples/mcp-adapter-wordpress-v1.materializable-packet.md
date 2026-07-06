## Spec Conformance
Implements the approved Acme MCP Smoke plugin spec without adding REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, AI provider calls, credentials, production write commands, custom MCP Adapter server code, Composer dependencies, or extra generated files. Generated paths: `acme-mcp-smoke/acme-mcp-smoke.php` and `acme-mcp-smoke/readme.txt`.

## Generated File Map
- `acme-mcp-smoke/acme-mcp-smoke.php`
- `acme-mcp-smoke/readme.txt`

## Implementation Packets
### acme-mcp-smoke/acme-mcp-smoke.php
```php
<?php
/**
 * Plugin Name: Acme MCP Smoke
 * Description: Registers a deterministic MCP-public ability for WordPress MCP Adapter runtime certification.
 * Version: 0.1.0
 * Requires at least: 7.0
 * Requires PHP: 8.1
 * Text Domain: acme-mcp-smoke
 * License: GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 *
 * @package AcmeMcpSmoke
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_action( 'wp_abilities_api_categories_init', 'acme_mcp_smoke_register_category' );
add_action( 'wp_abilities_api_init', 'acme_mcp_smoke_register_ability' );

/**
 * Register the MCP smoke category.
 */
function acme_mcp_smoke_register_category(): void {
	if ( ! function_exists( 'wp_register_ability_category' ) ) {
		return;
	}

	wp_register_ability_category(
		'acme-mcp-smoke',
		array(
			'label'       => __( 'MCP Smoke', 'acme-mcp-smoke' ),
			'description' => __( 'Deterministic abilities for MCP Adapter runtime certification.', 'acme-mcp-smoke' ),
		)
	);
}

/**
 * Register the MCP-public marker ability.
 */
function acme_mcp_smoke_register_ability(): void {
	if ( ! function_exists( 'wp_register_ability' ) ) {
		return;
	}

	wp_register_ability(
		'acme-mcp-smoke/get-runtime-marker',
		array(
			'label'               => __( 'Get Runtime Marker', 'acme-mcp-smoke' ),
			'description'         => __( 'Returns a deterministic marker string for MCP Adapter runtime smoke tests.', 'acme-mcp-smoke' ),
			'category'            => 'acme-mcp-smoke',
			'input_schema'        => array(
				'type'                 => 'object',
				'properties'           => array(
					'marker' => array(
						'type'        => 'string',
						'description' => __( 'Marker text expected by the runtime smoke test.', 'acme-mcp-smoke' ),
					),
				),
				'required'             => array( 'marker' ),
				'additionalProperties' => false,
			),
			'output_schema'       => array(
				'type'       => 'object',
				'properties' => array(
					'marker' => array(
						'type'        => 'string',
						'description' => __( 'The returned marker text.', 'acme-mcp-smoke' ),
					),
					'source' => array(
						'type'        => 'string',
						'description' => __( 'The deterministic source label.', 'acme-mcp-smoke' ),
					),
				),
				'required'   => array( 'marker', 'source' ),
			),
			'execute_callback'    => 'acme_mcp_smoke_execute_marker',
			'permission_callback' => 'acme_mcp_smoke_can_execute_marker',
			'meta'                => array(
				'annotations' => array(
					'readonly'    => true,
					'destructive' => false,
				),
				'mcp'         => array(
					'public' => true,
				),
			),
		)
	);
}

/**
 * Check whether the current user can execute the marker ability.
 *
 * @param array<string,mixed> $input Ability input.
 * @return bool
 */
function acme_mcp_smoke_can_execute_marker( array $input = array() ): bool {
	unset( $input );
	return current_user_can( 'read' );
}

/**
 * Return the deterministic marker.
 *
 * @param array<string,mixed> $input Ability input.
 * @return array<string,string>
 */
function acme_mcp_smoke_execute_marker( array $input ): array {
	$marker = isset( $input['marker'] ) ? sanitize_text_field( (string) $input['marker'] ) : '';

	return array(
		'marker' => $marker,
		'source' => 'acme-mcp-smoke',
	);
}
```

### acme-mcp-smoke/readme.txt
```txt
=== Acme MCP Smoke ===
Contributors: acme
Requires at least: 7.0
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Registers the acme-mcp-smoke/get-runtime-marker ability for MCP Adapter runtime smoke certification.

== Description ==

Acme MCP Smoke registers a deterministic read-only ability with meta.mcp.public so the WordPress MCP Adapter default server can discover and execute it during runtime certification. The plugin does not ship a custom MCP server, AI provider, REST route, AJAX handler, SQL query, upload handler, or production write command.
```

## Security Notes
The plugin registers a single read-only ability with `wp_register_ability()` on `wp_abilities_api_init` and registers its category on `wp_abilities_api_categories_init`. It includes `label`, `description`, `category`, `input_schema`, `output_schema`, `execute_callback`, `permission_callback`, and `meta.mcp.public`. The permission callback requires `current_user_can( 'read' )`, the execute callback sanitizes the marker with `sanitize_text_field()`, and no external AI providers or network calls are made. MCP Adapter exposure is a runtime verification boundary through `wordpress/mcp-adapter`, `mcp-adapter-discover-abilities`, and `mcp-adapter-execute-ability`; this plugin does not implement custom adapter internals.

## Deviation Log
No deviations from the approved spec. The fixture is intentionally minimal so failures isolate MCP Adapter provisioning, STDIO tool discovery, and ability execution rather than unrelated plugin behavior.

## Verification Notes
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet evals/suites/wordpress-plugin-executor/examples/mcp-adapter-wordpress-v1.materializable-packet.md --out-dir evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-YYYYMMDD/generated-plugin --result-dir evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-YYYYMMDD --overwrite` for packet, materialization, static artifact, AI-surface heuristic, and PHP syntax gates.
- Run `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-mcp-adapter-artifact-cert-YYYYMMDD/generated-plugin/acme-mcp-smoke --ability-name acme-mcp-smoke/get-runtime-marker --mcp-adapter-smoke --mcp-adapter-execute-args-json '{"marker":"Runtime MCP smoke"}' --mcp-adapter-expected-output "Runtime MCP smoke" --provision-full-profile --write --run-id generated-mcp-adapter-full-profile-YYYYMMDD --timeout-sec 300` to install the MCP Adapter plugin in disposable `wp-env`, list the default server, call `tools/list`, discover the public ability, execute it through `mcp-adapter-execute-ability`, and require WPCS/PHPCS plus Plugin Check.
- Run WP-CLI smoke commands in that disposable environment, including `wp plugin activate acme-mcp-smoke` and `wp mcp-adapter list`, before claiming runtime availability.
- Run PHPCS/WPCS with `phpcs --standard=WordPress --extensions=php <generated-plugin-dir>/acme-mcp-smoke` before coding-standards claims if the provisioned full profile is not used.
- Run PHPUnit when tests exist; this minimal fixture intentionally has no PHPUnit suite, so no PHPUnit proof is claimed.
- Run Plugin Check with `wp plugin check acme-mcp-smoke` before release claims.
- This packet does not prove PHPUnit behavior, AI Client provider-call behavior, browser/editor behavior, long-run model variance, or release readiness.

## Critic Handoff
Send the materialized files, certification output, and MCP Adapter runtime smoke output to `wordpress-security-critic` for capability, schema, MCP exposure, and runtime-boundary review, then to `wordpress-critic` for architecture, release-readiness, and operational calibration.
