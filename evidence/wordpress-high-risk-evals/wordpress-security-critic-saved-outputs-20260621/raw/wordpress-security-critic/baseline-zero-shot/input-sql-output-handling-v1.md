**Security Review Findings**

**High: SQL injection through `$_POST['type']` and interpolated `LIKE` clause**

`$type` is read directly from `$_POST['type']` and interpolated into SQL:

```php
$type = $_POST['type'];

"WHERE note_type = '$type'"
```

A caller who can submit this admin action with a valid nonce can alter the SQL predicate through `type`. `$term` is also interpolated into a `LIKE` clause, and `sanitize_text_field()` is not SQL escaping.

Use `wp_unslash()`, validate `type` against a fixed allowlist, escape the `LIKE` fragment with `$wpdb->esc_like()`, and use `$wpdb->prepare()`:

```php
$term = isset( $_POST['term'] )
	? sanitize_text_field( wp_unslash( $_POST['term'] ) )
	: '';

$type = isset( $_POST['type'] )
	? sanitize_key( wp_unslash( $_POST['type'] ) )
	: '';

$allowed_types = array( 'editorial', 'review', 'private' );

if ( ! in_array( $type, $allowed_types, true ) ) {
	wp_die( esc_html__( 'Invalid note type.', 'acme' ) );
}

$like = '%' . $wpdb->esc_like( $term ) . '%';

$rows = $wpdb->get_results(
	$wpdb->prepare(
		"SELECT post_id, note_html
		 FROM {$wpdb->prefix}acme_notes
		 WHERE note_type = %s
		 AND note_html LIKE %s",
		$type,
		$like
	)
);
```

This does not prove database compromise by itself. The reachable issue is SQL injection through the authenticated `admin_post_acme_search_notes` handler when a caller can supply `type` and pass the nonce check.

**High: Missing authorization for private editorial note data**

`check_admin_referer()` verifies intent/CSRF protection, but it is not an authorization check. If these notes contain private editorial data, the handler needs a capability check before querying:

```php
if ( ! current_user_can( 'edit_posts' ) ) {
	wp_die( esc_html__( 'You are not allowed to search notes.', 'acme' ) );
}
```

Use the actual capability that matches the data sensitivity, possibly `edit_private_posts`, `manage_options`, or a custom capability.

**Medium: Direct superglobal handling without `wp_unslash()`**

WordPress request data is slashed. Both values should be unslashed before sanitization or validation:

```php
$term = sanitize_text_field( wp_unslash( $_POST['term'] ?? '' ) );
$type = sanitize_key( wp_unslash( $_POST['type'] ?? '' ) );
```

Also guard missing keys to avoid notices and ambiguous behavior.

**Medium: Admin output is not context-escaped**

Sanitizing input does not make it safe for all output contexts.

Current output:

```php
echo '<h1>Results for ' . $term . '</h1>';
echo '<article data-note="' . $row->post_id . '">' . $row->note_html . '</article>';
```

Problems:

- `$term` is rendered as HTML text, so use `esc_html()`.
- `$row->post_id` is inside an HTML attribute, so use `esc_attr()` or cast to int.
- `$row->note_html` is rendered as HTML. If the product intends to preserve safe rich text, do not strip all markup; use `wp_kses_post()`.

Safer rendering:

```php
echo '<div class="wrap">';
echo '<h1>' . esc_html( sprintf( 'Results for %s', $term ) ) . '</h1>';

foreach ( $rows as $row ) {
	echo '<article data-note="' . esc_attr( (string) absint( $row->post_id ) ) . '">';
	echo wp_kses_post( $row->note_html );
	echo '</article>';
}

echo '</div>';
```

**Summary**

The main issues are a reachable SQL injection path through interpolated request values, missing authorization beyond the nonce, missing `wp_unslash()` before sanitization/validation, and unsafe admin rendering. Preserve rich text with `wp_kses_post()` if safe markup is intended; do not replace that requirement with blanket markup stripping.