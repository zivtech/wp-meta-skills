# Schema: `wordpress-security-gate/v1`

Report shape emitted by `evals/harness/wp_security_gate.py`
(`run_security_gate(...)`) and persisted by the certifier as
`security-gate.json`. Mirrors the API-lint gate's `schema`/`schema_version`
field split (decisions "remaining defaults").

```json
{
  "schema": "wordpress-security-gate",
  "schema_version": 1,
  "target": "path/to/plugin",
  "profile": "static",
  "status": "pass | fail | blocked | skip",
  "tools": [
    {"id": "phpcs-security", "status": "pass", "command": ["php", "phpcs", "--standard=WordPress", "--sniffs=...", "--report=json"]},
    {"id": "phpcs-suppression-diff", "status": "fail", "command": ["php", "phpcs", "...", "--ignore-annotations", "--report=json"]}
  ],
  "findings": [
    {
      "tool": "phpcs",
      "rule_id": "WordPress.DB.PreparedSQL",
      "file": "suppression-abuse.php",
      "line": 27,
      "severity": "error",
      "vuln_class": "sqli",
      "enforced": true,
      "message": "...",
      "source_excerpt": "..."
    }
  ],
  "suppressed_annotations": [
    {
      "file": "suppression-abuse.php",
      "line": 26,
      "annotation": "phpcs:ignore",
      "suppressed_rules": ["WordPress.DB.PreparedSQL"],
      "security_relevant": true,
      "reappears_without_annotations": true,
      "reviewed_safe_api": null,
      "source_excerpt": "$wpdb->get_results( ... )"
    }
  ],
  "summary": {"errors": 1, "warnings": 0, "advisory": 0, "suppressed_security": 1, "reviewed_suppressed": 0},
  "negative_space": [
    "No taint or cross-function data-flow analysis.",
    "No authorization/IDOR/capability-correctness reasoning (the security critic owns this).",
    "Plugin Check, PHPStan, and Semgrep advisory tools are phase P4.",
    "Block/theme JavaScript is out of scope for the static PHP profile."
  ]
}
```

Status rules (decision #6):

- **`fail`** — at least one `finding` with `enforced: true`: a
  `WordPress.DB.Prepared*` or `WordPress.Security.EscapeOutput` **error**, or a
  `suppressed_annotations[]` entry with `security_relevant` **and**
  `reappears_without_annotations` true.
- **`pass`** — no enforced finding (advisory findings may still be present for
  the critic). A known-safe WordPress helper suppression, currently
  `get_block_wrapper_attributes()`, is recorded in `suppressed_annotations[]`
  with `reviewed_safe_api` and `security_relevant: false`; it remains evidence
  for the critic but does not hard-fail the static gate.
- **`blocked`** — phpcs absent or WordPress standards not installed.
- **`skip`** — no PHP files under the target.

`enforced` distinguishes the hard-gate subset (enters `failing_gates`) from
advisory evidence the critic adjudicates.
