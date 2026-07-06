# Focused Fixture: Upload And Filesystem Boundary

Review the following WordPress plugin excerpt with `wordpress-security-critic`.
The review target is whether upload and path handling can become arbitrary file
write, MIME bypass, or unsafe local include.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Import Templates
 */

add_action( 'admin_post_acme_import_template', 'acme_import_template' );
function acme_import_template() {
	check_admin_referer( 'acme-import-template' );

	$upload = wp_handle_upload(
		$_FILES['template'],
		array(
			'test_form' => false,
		)
	);

	if ( ! empty( $upload['file'] ) && str_ends_with( $upload['file'], '.php' ) ) {
		include $upload['file'];
	}

	$target = plugin_dir_path( __FILE__ ) . 'templates/' . $_POST['template_name'] . '.php';
	copy( $upload['file'], $target );

	wp_safe_redirect( admin_url( 'admin.php?page=acme-import-template&imported=1' ) );
	exit;
}
```

## Expected Review Focus

- Detect missing capability and nonce pairing. `check_admin_referer()` alone
  does not prove the user can import executable templates.
- Detect that `wp_handle_upload()` is not enough when code later includes or
  copies files into executable plugin paths.
- Require MIME and extension validation with `wp_check_filetype_and_ext()` and a
  constrained allowlist appropriate to the feature.
- Detect path traversal or unsafe filename composition from `$_POST['template_name']`.
- Require `wp_unslash()`, `sanitize_key()` or a stricter filename policy,
  `wp_normalize_path()`, `realpath()` boundary checks, and safe directory
  creation with `wp_mkdir_p()` where applicable.

## Required Boundaries

Do not claim antivirus or malware scanning coverage. Do not assume every admin
upload is a vulnerability; calibrate severity to the missing capability,
executable destination, include behavior, and caller role.
