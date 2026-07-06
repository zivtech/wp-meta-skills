**Scope**

Review target: request handling in `admin_post_acme_search_notes`, specifically data flow from `$_POST` into SQL and rendered admin HTML.

The main issues are:

- Direct `$_POST` access without `wp_unslash()`.
- Unvalidated request values used in SQL.
- SQL string interpolation instead of `$wpdb->prepare()`.
- Sanitization treated as if it were output escaping.
- Admin output lacks context-specific escaping.
- Nonce check without an explicit capability check before exposing note data.

**WordPress-Specific Decisions**

1. **Request input must be unslashed before sanitization or validation**

Current code:

```php
$term = sanitize_text_field( $_POST['term'] );
$type = $_POST['type'];
```

WordPress request data is slashed. Use `wp_unslash()` first, and handle missing keys.

Example direction:

```php
$term = isset( $_POST['term'] )
	? sanitize_text_field( wp_unslash( $_POST['term'] ) )
	: '';

$type = isset( $_POST['type'] )
	? sanitize_key( wp_unslash( $_POST['type'] ) )
	: '';
```

2. **Nonce is not authorization**

`check_admin_referer()` verifies intent, not permission. If this action returns private editorial notes, require a capability check before querying.

Example:

```php
if ( ! current_user_can( 'edit_posts' ) ) {
	wp_die( esc_html__( 'Sorry, you are not allowed to search notes.', 'acme' ) );
}
```

The exact capability depends on the note data model. If notes are tied to posts, `edit_posts`, `edit_others_posts`, or per-post capability checks may be more appropriate.

3. **SQL must use `$wpdb->prepare()` and constrained values**

Current SQL is injectable because `$type` is placed directly into the query, and `$term` is interpolated into a `LIKE` clause:

```php
WHERE note_type = '$type' AND note_html LIKE '%$term%'
```

A safer shape:

```php
$allowed_types = array( 'editorial', 'internal', 'review' );

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

This addresses both placeholder binding and `LIKE` wildcard escaping.

4. **Sanitization is not output escaping**

`sanitize_text_field()` helps normalize input. It does not make a value safe for all later contexts.

Current output issues:

```php
echo '<h1>Results for ' . $term . '</h1>';
echo '<article data-note="' . $row->post_id . '">' . $row->note_html . '</article>';
```

Safer output:

```php
echo '<h1>' . esc_html( sprintf( __( 'Results for %s', 'acme' ), $term ) ) . '</h1>';

foreach ( $rows as $row ) {
	echo '<article data-note="' . esc_attr( (string) $row->post_id ) . '">';
	echo wp_kses_post( $row->note_html );
	echo '</article>';
}
```

Use `wp_kses_post()` only if preserving safe markup is intended. I am not recommending stripping all rich text, because the fixture states that safe markup may be valid product behavior.

**Risks**

- **SQL injection:** Reachable through `$_POST['type']` and potentially `$_POST['term']`, because both are interpolated into SQL. The caller must be able to submit the `admin_post_acme_search_notes` action with a valid nonce. The nonce reduces exposure but does not make the query safe.
- **Stored or reflected XSS:** `$term` is rendered into an `<h1>` without escaping. `$row->note_html` is rendered directly from the database. If unsafe HTML is stored in `note_html`, it can execute in the admin page.
- **Attribute injection risk:** `$row->post_id` is rendered inside `data-note` without `esc_attr()`.
- **Unauthorized data exposure:** A valid nonce alone does not prove the user should be allowed to search or view editorial notes.

I am not claiming database compromise by itself. The concrete SQL injection path is request-controlled input flowing from `$_POST['type']` and the `LIKE` term into an interpolated SQL query.

**Verification**

Review should confirm:

- `$_POST` values are checked with `isset()` or equivalent before use.
- Input is passed through `wp_unslash()` before sanitization or validation.
- `$type` is constrained to an allowed set of note types.
- SQL uses `$wpdb->prepare()`.
- `LIKE` values use `$wpdb->esc_like()` before being passed to `%s`.
- Admin output uses `esc_html()` for text nodes.
- Attribute values use `esc_attr()`.
- Stored note markup uses `wp_kses_post()` or a stricter allowlist if safe rich text is required.
- A capability check runs before querying private note data.

**Open Questions**

- What users are supposed to access this action: all admins, editors, authors, or only users who can edit the related post?
- Is `note_html` trusted editor-authored markup, imported content, or user-submitted content?
- What are the valid `note_type` values?
- Should results be scoped by post ownership, status, site, or other editorial permissions?
- Should the handler redirect back to an admin page instead of echoing raw output directly from `admin_post`?