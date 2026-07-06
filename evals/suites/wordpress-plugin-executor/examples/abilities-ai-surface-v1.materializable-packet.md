## Spec Conformance
Implements the approved Acme Editorial Assistant plugin spec without adding REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, build tooling, provider plugins, credentials, production write commands, custom MCP Adapter server code, or extra generated files.

## Generated File Map
- `acme-editorial-assistant/acme-editorial-assistant.php`
- `acme-editorial-assistant/readme.txt`

## Implementation Packets
### acme-editorial-assistant/acme-editorial-assistant.php
```php
<?php
/**
 * Plugin Name: Acme Editorial Assistant
 * Description: Minimal Abilities API and AI Client boundary fixture.
 * Version: 0.1.0
 * Requires at least: 7.0
 * Requires PHP: 8.1
 * Text Domain: acme-editorial-assistant
 *
 * @package AcmeEditorialAssistant
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_action( 'wp_abilities_api_init', 'acme_editorial_assistant_register_abilities' );

/**
 * Register read-only editorial abilities.
 */
function acme_editorial_assistant_register_abilities() {
	if ( ! function_exists( 'wp_register_ability' ) ) {
		return;
	}

	wp_register_ability(
		'acme-editorial-assistant/get-post-summary',
		array(
			'label'               => __( 'Get post summary', 'acme-editorial-assistant' ),
			'description'         => __( 'Returns a deterministic excerpt-based summary for a post the current user can edit.', 'acme-editorial-assistant' ),
			'category'            => 'site-information',
			'input_schema'        => array(
				'type'                 => 'object',
				'properties'           => array(
					'post_id' => array(
						'type'        => 'integer',
						'minimum'     => 1,
						'description' => __( 'Post ID to summarize.', 'acme-editorial-assistant' ),
					),
				),
				'required'             => array( 'post_id' ),
				'additionalProperties' => false,
			),
			'output_schema'       => array(
				'type'       => 'object',
				'properties' => array(
					'post_id' => array( 'type' => 'integer' ),
					'title'   => array( 'type' => 'string' ),
					'summary' => array( 'type' => 'string' ),
				),
				'required'   => array( 'post_id', 'title', 'summary' ),
			),
			'execute_callback'    => 'acme_editorial_assistant_get_post_summary',
			'permission_callback' => 'acme_editorial_assistant_can_read_summary',
			'meta'                => array(
				'annotations' => array(
					'readonly'    => true,
					'destructive' => false,
				),
			),
		)
	);
}

/**
 * Check ability access for the supplied post.
 *
 * @param array $input Ability input.
 * @return bool
 */
function acme_editorial_assistant_can_read_summary( $input = array() ) {
	$post_id = isset( $input['post_id'] ) ? absint( $input['post_id'] ) : 0;
	return $post_id > 0 && current_user_can( 'edit_post', $post_id );
}

/**
 * Return a deterministic summary for an editable post.
 *
 * @param array $input Ability input.
 * @return array|WP_Error
 */
function acme_editorial_assistant_get_post_summary( $input ) {
	$post_id = isset( $input['post_id'] ) ? absint( $input['post_id'] ) : 0;
	if ( $post_id <= 0 || ! current_user_can( 'edit_post', $post_id ) ) {
		return new WP_Error( 'acme_editorial_assistant_forbidden', __( 'You cannot summarize this post.', 'acme-editorial-assistant' ) );
	}

	$post = get_post( $post_id );
	if ( ! $post instanceof WP_Post ) {
		return new WP_Error( 'acme_editorial_assistant_missing_post', __( 'Post not found.', 'acme-editorial-assistant' ) );
	}

	$source = has_excerpt( $post ) ? get_the_excerpt( $post ) : wp_strip_all_tags( $post->post_content );
	$summary = wp_trim_words( $source, 40, '' );

	return array(
		'post_id' => $post_id,
		'title'   => get_the_title( $post ),
		'summary' => $summary,
	);
}

/**
 * Demonstrate a guarded future AI Client summary helper.
 *
 * @param int $post_id Post ID.
 * @return string|WP_Error
 */
function acme_editorial_assistant_generate_ai_summary( $post_id ) {
	$post_id = absint( $post_id );
	if ( $post_id <= 0 || ! current_user_can( 'edit_post', $post_id ) ) {
		return new WP_Error( 'acme_editorial_assistant_forbidden', __( 'You cannot summarize this post.', 'acme-editorial-assistant' ) );
	}
	if ( ! function_exists( 'wp_ai_client_prompt' ) ) {
		return new WP_Error( 'acme_editorial_assistant_ai_unavailable', __( 'The WordPress AI Client is not available.', 'acme-editorial-assistant' ) );
	}

	$post = get_post( $post_id );
	if ( ! $post instanceof WP_Post ) {
		return new WP_Error( 'acme_editorial_assistant_missing_post', __( 'Post not found.', 'acme-editorial-assistant' ) );
	}

	$plain_text = wp_strip_all_tags( $post->post_content );
	$summary = wp_ai_client_prompt( 'Summarize this WordPress post for an editor: ' . $plain_text )
		->generate_text();

	if ( is_wp_error( $summary ) ) {
		return $summary;
	}

	return wp_kses_post( $summary );
}
```

### acme-editorial-assistant/readme.txt
```txt
=== Acme Editorial Assistant ===
Contributors: acme
Requires at least: 7.0
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Minimal Abilities API and AI Client boundary fixture for executor certification.
```

## Security Notes
The registered ability uses `wp_register_ability()` on `wp_abilities_api_init` and includes `input_schema`, `output_schema`, `execute_callback`, and `permission_callback`. Both the ability callback and the future AI helper check `current_user_can( 'edit_post', $post_id )`. The ability callback is deterministic and does not call external providers. The AI helper checks `function_exists( 'wp_ai_client_prompt' )`, returns `WP_Error` when unsupported or unauthorized, handles `is_wp_error()`, and escapes model output with `wp_kses_post()`. No credentials, provider plugins, REST routes, AJAX endpoints, admin-post handlers, SQL, uploads, or custom MCP Adapter server code are generated.

## Deviation Log
No deviations from the approved spec. `wordpress/mcp-adapter`, `mcp-adapter-discover-abilities`, and `mcp-adapter-execute-ability` are named only as verification/discovery boundaries, not generated as custom server code.

## Verification Notes
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet <candidate-output.md> --out-dir <generated-plugin-dir> --result-dir <result-dir> --require-tool php-lint --overwrite` for packet, materialization, static artifact, AI-surface heuristic, and PHP syntax gates.
- Run PHPCS/WPCS with `phpcs --standard=WordPress --extensions=php <generated-plugin-dir>` before coding-standards claims.
- Run PHPUnit where tests exist; this fixture has no PHPUnit test files.
- Run WP-CLI smoke in a disposable WordPress 7.0+ environment to confirm plugin activation and ability registration after `wp_abilities_api_init`.
- Confirm provider configuration through the `wp_connectors_init` boundary only when provider plugins are in scope.
- If using `wordpress/mcp-adapter`, verify ability discovery with `mcp-adapter-discover-abilities` and execution with `mcp-adapter-execute-ability` against `acme-editorial-assistant/get-post-summary`.
- Run Plugin Check with `wp plugin check acme-editorial-assistant` before release claims.
- These commands were not run while drafting this packet; WPCS, PHPUnit, Plugin Check, wp-env, MCP Adapter discovery/execution, AI Client runtime calls, browser/editor behavior, and release readiness are not claimed by the packet alone.

## Critic Handoff
Send the materialized files and certification output to `wordpress-security-critic` for capability, schema, prompt, and AI/Abilities boundary review, then to `wordpress-critic` for architecture, release-readiness, and operational calibration.
