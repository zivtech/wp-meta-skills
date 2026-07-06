# Focused Fixture: Security Gate Evidence Consumption

Review the following WordPress plugin excerpt with `wordpress-security-critic`.
The artifact includes a supplied `security-gate.json` sidecar from the
deterministic static profile. Consume that sidecar as evidence; do not rerun
PHPCS/WPCS. Your review must distinguish gate-derived evidence from
critic-derived reachability analysis and must include a suppression-review note
for every `suppressed_annotations[]` entry.

## Artifact Under Review

```php
<?php
/**
 * Plugin Name: Acme Report Export
 */

add_action( 'admin_post_acme_report_export', 'acme_report_export' );

function acme_report_export() {
	global $wpdb;

	check_admin_referer( 'acme-report-export' );

	$report_id = $_POST['report_id'];
	$format    = sanitize_text_field( $_POST['format'] );

	// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	$row = $wpdb->get_row(
		"SELECT id, title, body_html FROM {$wpdb->prefix}acme_reports WHERE id = $report_id"
	);

	echo '<h1>' . $row->title . '</h1>';
	echo '<div class="report-body">' . $row->body_html . '</div>';
	echo '<a href="' . admin_url( 'admin.php?page=acme-report&format=' . $format ) . '">Back</a>';
}
```

## Supplied `security-gate.json`

```json
{
  "schema": "wordpress-security-gate",
  "schema_version": 1,
  "status": "fail",
  "profile": "static",
  "tools": [
    {"id": "phpcs-security", "status": "fail"},
    {"id": "phpcs-suppression-diff", "status": "fail", "command": ["phpcs", "--ignore-annotations"]}
  ],
  "findings": [
    {
      "tool": "phpcs",
      "rule_id": "WordPress.Security.EscapeOutput.OutputNotEscaped",
      "file": "acme-report-export.php",
      "line": 26,
      "severity": "error",
      "vuln_class": "xss",
      "enforced": true,
      "message": "All output should be run through an escaping function."
    },
    {
      "tool": "phpcs",
      "rule_id": "WordPress.DB.DirectDatabaseQuery.DirectQuery",
      "file": "acme-report-export.php",
      "line": 21,
      "severity": "warning",
      "vuln_class": "sqli",
      "enforced": false,
      "message": "Direct database query detected."
    }
  ],
  "suppressed_annotations": [
    {
      "file": "acme-report-export.php",
      "line": 20,
      "annotation": "phpcs:ignore",
      "suppressed_rules": ["WordPress.DB.PreparedSQL.InterpolatedNotPrepared"],
      "security_relevant": true,
      "reappears_without_annotations": true,
      "vuln_class": "sqli",
      "message": "Use placeholders and $wpdb->prepare()."
    },
    {
      "file": "blocks/report-card/render.php",
      "line": 14,
      "annotation": "phpcs:ignore",
      "suppressed_rules": ["WordPress.Security.EscapeOutput.OutputNotEscaped"],
      "security_relevant": false,
      "reappears_without_annotations": true,
      "reviewed_safe_api": "get_block_wrapper_attributes",
      "message": "All output should be run through an escaping function."
    }
  ],
  "summary": {
    "errors": 1,
    "warnings": 1,
    "advisory": 1,
    "suppressed_security": 1,
    "reviewed_suppressed": 1
  },
  "negative_space": [
    "No authorization/IDOR/capability-correctness reasoning: permission_callback and right-capability judgment belong to the security critic.",
    "No taint or cross-function data-flow analysis in phase 1."
  ]
}
```

## Expected Review Focus

- Cite the sidecar status `fail`, the enforced
  `WordPress.Security.EscapeOutput.OutputNotEscaped` finding, and the
  `phpcs-suppression-diff` evidence for
  `WordPress.DB.PreparedSQL.InterpolatedNotPrepared`.
- Review every suppression entry by file and line, including the reviewed-safe
  `get_block_wrapper_attributes` suppression.
- Treat direct-query/caching noise as advisory evidence unless the reachable
  SQL injection path is shown.
- Do critic-derived reachability analysis for the `admin_post` path,
  `check_admin_referer()` without `current_user_can()`, unslashed
  `$_POST`, `$wpdb->prepare()`, `esc_html()`, `esc_url()`, and `wp_kses_post()`.

## Required Boundaries

Do not claim the gate proves authorization or IDOR correctness. Do not ignore
the failed gate because the plugin has a nonce. Do not convert the reviewed
`get_block_wrapper_attributes()` note into a blanket `EscapeOutput` allowlist.
