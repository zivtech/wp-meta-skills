# Focused Fixture: Input, SQL, And Output Handling

Review the following WordPress plugin excerpt with `wordpress-security-critic`.
The review target is unsafe request handling from superglobal input through SQL
and rendered admin output.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Search Notes
 */

add_action( 'admin_post_acme_search_notes', 'acme_search_notes' );
function acme_search_notes() {
	global $wpdb;

	check_admin_referer( 'acme-search-notes' );

	$term = sanitize_text_field( $_POST['term'] );
	$type = $_POST['type'];

	$rows = $wpdb->get_results(
		"SELECT post_id, note_html FROM {$wpdb->prefix}acme_notes WHERE note_type = '$type' AND note_html LIKE '%$term%'"
	);

	echo '<div class="wrap">';
	echo '<h1>Results for ' . $term . '</h1>';
	foreach ( $rows as $row ) {
		echo '<article data-note="' . $row->post_id . '">' . $row->note_html . '</article>';
	}
	echo '</div>';
}
```

## Expected Review Focus

- Detect direct use of `$_POST` without `wp_unslash()` before sanitization or
  validation.
- Detect interpolated SQL and require `$wpdb->prepare()` with appropriate
  placeholders and a constrained value domain.
- Distinguish sanitization from output escaping: `sanitize_text_field()` does
  not make `$term`, `$type`, or database HTML safe for every output context.
- Require context-specific escaping such as `esc_html()`, `esc_attr()`, and
  `wp_kses_post()` where preserving safe markup is intended.
- Require authorization beyond a nonce if the action exposes private editorial
  note data.

## Required Boundaries

Do not recommend stripping all rich text if the intended product behavior is to
preserve safe markup. Do not claim database compromise without naming the
reachable SQL injection path and caller capability.
