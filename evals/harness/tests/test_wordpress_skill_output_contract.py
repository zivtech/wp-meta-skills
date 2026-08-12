"""Tests for WordPress saved skill-output contract validation."""

import json

import pytest

import validate_wordpress_skill_output as oracle


GOOD_PLANNER = """\
## Plugin Scope
Build an editorial review plugin for an existing WordPress admin workflow.

## Current-State Evidence
The repo already uses `register_post_type()` and `register_post_meta()` with `show_in_rest`.

## Architecture And File Map
Use a small plugin bootstrap plus an admin settings class.

## Hook And Data Flow
Use `register_setting()`, `current_user_can()`, and `check_admin_referer()`.

## Security And Data Integrity
Rich text uses `wp_kses_post()` and redirects use `wp_safe_redirect()`.

## Operations And Release Plan
Run PHPCS/WPCS, PHPUnit, WP-CLI smoke, and Plugin Check before release.

## Assumption Register
    Assumption: no exact WordPress API applies to external CRM ownership because
    WordPress does not control the vendor account; the CRM owner must confirm it
    against the vendor API contract.

## Test Strategy
PHPUnit covers settings persistence; Plugin Check covers package readiness.

## Acceptance Criteria
Admin save succeeds only for users with the mapped capability.

## Executor Handoff
Generate plugin files and tests.

## Critic Handoff
Send to wordpress-security-critic and wordpress-critic.
"""


BAD_PLANNER = """\
## Plugin Scope
[Finding]

## Architecture
Use WordPress APIs, use nonces, use capabilities, and run tests.
"""


GOOD_BLOCK_PLANNER = """\
## Block Scope
Build one dynamic `acme/runtime-card` block. This does not claim cross-browser coverage.

Block identity: acme/runtime-card
Primary serialization: dynamic
Interaction pattern: server-rendered block

## Current-State Evidence
The plugin registers blocks from `block.json` with `register_block_type()`.

## Metadata And Attribute Plan
`block.json` declares the block name, title, and category. The block has no
attributes and no saved content; its saved-markup contract is intentionally empty.

Metadata file: block.json
Attributes: none
Saved markup: self-closing

## Render And Interaction Plan
Use `render_callback` for dynamic output. A missing record is a render failure
that returns empty output after logging an error.

Render surface: render_callback
Failure behavior: log-and-return-empty

## Compatibility And Migration Plan
There is no existing saved content. Keep a saved-content fixture containing the
self-closing block delimiter so future metadata changes can be checked.

Compatibility decision: new-contract
Saved-content fixture: required

## Security Performance And Accessibility Notes
The callback uses `esc_html()` and has no REST, SQL, upload, or remote-call path.

## Assumption Register
Assumption: the host loads the plugin before editor smoke; the runtime oracle verifies it.

## Test Strategy
Run a Playwright editor smoke for insertion/save and a separate frontend smoke
for the `.wp-block-acme-runtime-card` output, plus PHPUnit for the callback.

Editor oracle: required
Editor oracle method: playwright-insert-save-reload
Editor oracle block: acme/runtime-card
Frontend oracle: required
Frontend oracle method: playwright-selector-visible-text
Frontend oracle selector: .wp-block-acme-runtime-card
Frontend expected text: Runtime block smoke

## Acceptance Criteria
The editor saves the block and the front end renders the fixture-owned text.

## Executor Handoff
Generate the exact block files and recorded verification packet.

## Critic Handoff
Send the packet to wordpress-critic after the runtime evidence exists.
"""


UNRELATED_BLOCK_PLANNER = """\
## Block Scope
Create a content feature for an existing WordPress site. This does not claim release readiness.

## Current-State Evidence
The site has `register_post_type()` and `WP_Query` usage.

## Metadata And Attribute Plan
Keep the content type fields in post meta.

## Render And Interaction Plan
Render the archive with a PHP template and show a friendly error.

## Compatibility And Migration Plan
Keep old posts available in a fixture export.

## Security Performance And Accessibility Notes
Use `current_user_can()` for admin access.

## Assumption Register
Assumption: the content owner supplies sample data.

## Test Strategy
Use PHPUnit and Playwright for a browser check.

## Acceptance Criteria
The archive lists published records.

## Executor Handoff
Implement the content feature.

## Critic Handoff
Send it to wordpress-critic.
"""


GOOD_GUTENBERG_MIGRATION_PLANNER = """\
## Migration Scope
Migrate Contentful Rich Text into Gutenberg blocks. This does not prove production cutover readiness.

## Current-State Evidence
The importer writes `post_content` and has a disposable wp-env fixture.

## Source Audit
Inspect the Rich Text document/container schema and localized fields.

## Target Mapping
Map source nodes to core block mappings in `post_content`; use an explicit
custom block allowlist and record every unsupported or unmapped node.

Gutenberg target: post_content
Block mapping: core+custom
Unsupported content: accounted

## Transform And Execution Plan
Use WordPress block serialization, stable source identity, and an idempotent,
rerunnable two-pass import.

Serialization API: serialize_blocks
Rerun policy: idempotent

## Validation Plan
Use `parse_blocks()` for block validation, a semantic oracle for expected text
and href values, a Playwright editor smoke, and a separate frontend smoke.

Block validation oracle: parse_blocks
Semantic oracle: required
Semantic oracle fields: text,href,attributes,unsupported,freeform
Editor oracle: required
Editor oracle method: playwright-clone-save-reload-restore
Frontend oracle: required
Frontend oracle method: playwright-selector-visible-text

## Rollback And Monitoring
Keep run-scoped before-images and execute a rollback test in wp-env.

## Assumption Register
Assumption: only the mapped locales are in scope.

## Test Strategy
Use a canonical source fixture plus malformed-container negative fixtures.

Fixture: required
Fixture identity: article-42-rich-text

## Acceptance Criteria
Every mapped node is present and every unsupported node is accounted for.

## Critic Handoff
Review serialization, idempotence, editor evidence, and rollback evidence.
"""


GOOD_CLASSIC_MIGRATION_PLANNER = """\
## Migration Scope
Import CSV article rows into classic WordPress posts. Gutenberg and the Block Editor are explicitly out of scope. This does not prove production cutover readiness.

## Current-State Evidence
The importer uses `wp_insert_post()` and writes sanitized HTML into `post_content`.

## Source Audit
Inspect the CSV header, UTF-8 encoding, stable source ID, and required columns.

## Target Mapping
Map title, body, and publication state to `post_title`, `post_content`, and `post_status`; log unsupported columns.

## Transform And Execution Plan
Use `wp_kses_post()` before `wp_insert_post()`, retain the stable source ID, and make reruns idempotent.

## Validation Plan
Use `wp post list`, exact expected title and body assertions, and a front-end browser smoke.

## Rollback And Monitoring
Keep run-scoped before-images and execute a rollback test in the disposable environment.

## Assumption Register
Assumption: the supplied CSV is the authoritative locale for this import.

## Test Strategy
Use a canonical CSV fixture plus malformed-row and duplicate-ID fixtures.

## Acceptance Criteria
Every valid row maps once, unsupported columns are accounted for, and rollback restores the prior posts.

## Critic Handoff
Review sanitization, idempotence, semantic evidence, and rollback evidence.
"""


GOOD_CRITIC = """\
**VERDICT: REVISE**

**Overall Assessment**
The implementation has a real REST authorization gap.

**Pre-commitment Predictions**
Expected issue: missing `permission_callback` on a custom route.

**Critical Findings**
- None.

**Major Findings**
- `register_rest_route()` lacks a specific `permission_callback` using `current_user_can()`.

**Minor Findings**
- None.

**What's Missing**
This review does not prove runtime behavior or editor smoke results.

**Multi-Perspective Notes**
Security and operations agree the route needs a capability boundary.

**Verdict Justification**
REVISE because the code is close but cannot ship without authorization.

**Remediation Guide**
Add a `permission_callback`, cover it with PHPUnit, then run WP-CLI smoke and Plugin Check.

**Open Questions**
Unknown: which role should receive the new capability.
"""


BAD_CRITIC = """\
**VERDICT: MAYBE**

**Overall Assessment**
Looks fine.
"""


SECURITY_GATE_REPORT = {
    "schema": "wordpress-security-gate",
    "schema_version": 1,
    "status": "fail",
    "tools": [
        {"id": "phpcs-security", "status": "fail"},
        {"id": "phpcs-suppression-diff", "status": "fail"},
    ],
    "findings": [
        {
            "rule_id": "WordPress.Security.EscapeOutput.OutputNotEscaped",
            "file": "acme-report/admin.php",
            "line": 38,
            "severity": "error",
            "enforced": True,
        },
        {
            "rule_id": "WordPress.DB.DirectDatabaseQuery.DirectQuery",
            "file": "acme-report/admin.php",
            "line": 40,
            "severity": "warning",
            "enforced": False,
        }
    ],
    "suppressed_annotations": [
        {
            "file": "acme-report/admin.php",
            "line": 42,
            "suppressed_rules": ["WordPress.DB.PreparedSQL.InterpolatedNotPrepared"],
            "security_relevant": True,
            "reappears_without_annotations": True,
        },
        {
            "file": "blocks/render.php",
            "line": 16,
            "suppressed_rules": ["WordPress.Security.EscapeOutput.OutputNotEscaped"],
            "security_relevant": False,
            "reviewed_safe_api": "get_block_wrapper_attributes",
        },
    ],
    "summary": {"errors": 1, "warnings": 0, "suppressed_security": 1, "reviewed_suppressed": 1},
    "negative_space": ["No authorization/IDOR/capability-correctness reasoning."],
}


GOOD_SECURITY_CRITIC_WITH_GATE = """\
**VERDICT: REVISE**

**Overall Assessment**
The artifact fails the supplied `security-gate.json` static profile and needs
reachability review before release.

**Pre-commitment Predictions**
Expected failures: suppressed SQL preparation and escaped-output gaps.

**Security Gate Evidence**
Gate-derived evidence from `security-gate.json` reports status `fail`.
`phpcs-suppression-diff` / `--ignore-annotations` found
`WordPress.DB.PreparedSQL.InterpolatedNotPrepared` at
`acme-report/admin.php:42`. The enforced PHPCS finding
`WordPress.Security.EscapeOutput.OutputNotEscaped` is at
`acme-report/admin.php:38`. Advisory gate-derived evidence includes
`WordPress.DB.DirectDatabaseQuery.DirectQuery` at `acme-report/admin.php:40`.

**Critical Findings**
- None until the caller path is proven.

**Major Findings**
- The report query suppression hides a `$wpdb->prepare()` failure, and the
  rendered admin output must use `wp_kses_post()` or `esc_html()` by context.

**Minor Findings**
- None.

**Suppression Review**
- `acme-report/admin.php:42` is a security-relevant suppression because
  `WordPress.DB.PreparedSQL.InterpolatedNotPrepared` reappears without
  annotations.
- `blocks/render.php:16` suppresses
  `WordPress.Security.EscapeOutput.OutputNotEscaped`; it is not
  security-relevant because the reviewed safe API is
  `get_block_wrapper_attributes`.

**What's Missing**
The gate's negative space does not prove authorization, IDOR, or capability
correctness; that critic-derived path review remains open.

**Multi-Perspective Notes**
Security and operations agree the deterministic sidecar blocks release.

**Exploitability Notes**
No CRITICAL finding until a role, route, or admin-post caller path is named.

**Verdict Justification**
REVISE because gate-derived evidence is deterministic and the critic-derived
reachability review is incomplete.

**Remediation Guide**
Remove the SQL suppression, prepare the query with `$wpdb->prepare()`, keep
contextual output escaping with `wp_kses_post()` or `esc_html()`, then rerun
PHPCS/WPCS and the security gate.

**Open Questions**
Unknown: which capability is required to reach `acme-report/admin.php`.
"""


def test_good_planner_output_passes():
    result = oracle.validate_output("wordpress-plugin-planner", GOOD_PLANNER)

    assert result["pass"] is True
    assert result["score"] == 1.0


def test_good_block_planner_passes_section_local_contract():
    result = oracle.validate_output("wordpress-planner.block", GOOD_BLOCK_PLANNER)
    checks = {check["id"]: check for check in result["checks"]}

    assert result["pass"] is True
    assert checks["block_scope_contract"]["passed"] is True
    assert checks["block_metadata_attribute_contract"]["passed"] is True
    assert checks["block_render_contract"]["passed"] is True
    assert checks["block_compatibility_contract"]["passed"] is True
    assert checks["block_editor_frontend_contract"]["passed"] is True


def test_unrelated_wordpress_apis_cannot_pass_block_planner_contract():
    result = oracle.validate_output("wordpress-planner.block", UNRELATED_BLOCK_PLANNER)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert {
        "block_scope_contract",
        "block_metadata_attribute_contract",
        "block_render_contract",
        "block_compatibility_contract",
        "block_editor_frontend_contract",
    } <= failed


@pytest.mark.parametrize(
    ("old", "new", "expected_gate"),
    [
        ("Primary serialization: dynamic", "Primary serialization: not defined", "block_scope_contract"),
        ("Metadata file: block.json", "Metadata file: not defined", "block_metadata_attribute_contract"),
        ("Render surface: render_callback", "Render surface: not defined", "block_render_contract"),
        ("Compatibility decision: new-contract", "Compatibility decision: not-defined", "block_compatibility_contract"),
        ("Frontend oracle: required", "Frontend oracle: skipped", "block_editor_frontend_contract"),
    ],
)
def test_block_plan_single_fact_mutants_kill_the_intended_gate(old, new, expected_gate):
    candidate = GOOD_BLOCK_PLANNER.replace(old, new)
    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert expected_gate in failed
    domain_gates = {
        "block_scope_contract",
        "block_metadata_attribute_contract",
        "block_render_contract",
        "block_compatibility_contract",
        "block_editor_frontend_contract",
    }
    assert failed & domain_gates == {expected_gate}


def test_static_block_negative_space_does_not_create_dynamic_classification():
    candidate = (
        GOOD_BLOCK_PLANNER
        .replace(
            "Build one dynamic `acme/runtime-card` block.",
            "Build one static `acme/runtime-card` block; it is not a dynamic block.",
        )
        .replace("Primary serialization: dynamic", "Primary serialization: static")
        .replace("Render surface: render_callback", "Render surface: save()")
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)

    assert result["pass"] is True


def test_interactivity_pattern_is_orthogonal_to_static_serialization():
    candidate = (
        GOOD_BLOCK_PLANNER
        .replace("Primary serialization: dynamic", "Primary serialization: static")
        .replace("Interaction pattern: server-rendered block", "Interaction pattern: Interactivity API")
        .replace("Render surface: render_callback", "Render surface: save()")
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)

    assert result["pass"] is True


@pytest.mark.parametrize(
    ("old", "new", "gate"),
    [
        (
            "Failure behavior: log-and-return-empty",
            "Failure behavior: not-defined",
            "block_render_contract",
        ),
        (
            "Saved-content fixture: required",
            "Saved-content fixture: never",
            "block_compatibility_contract",
        ),
        (
            "Editor oracle: required",
            "Editor oracle: skipped",
            "block_editor_frontend_contract",
        ),
    ],
)
def test_negated_block_decision_records_fail_their_owning_gate(old, new, gate):
    result = oracle.validate_output("wordpress-planner.block", GOOD_BLOCK_PLANNER.replace(old, new))
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert gate in failed


def test_duplicate_decision_record_is_rejected():
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Editor oracle: required",
        "Editor oracle: required\nEditor oracle: skipped",
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_editor_frontend_contract" in failed


def test_decision_record_inside_example_fence_is_not_contract_evidence():
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Primary serialization: dynamic",
        "```text\nPrimary serialization: dynamic\n```",
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_scope_contract" in failed


@pytest.mark.parametrize(
    "replacement",
    [
        "```text\nPrimary serialization: dynamic\n````",
        "```text\nPrimary serialization: dynamic",
        "    Primary serialization: dynamic",
        "   \tPrimary serialization: dynamic",
        "<!-- Primary serialization: dynamic -->",
    ],
    ids=(
        "longer-closing-fence", "unclosed-fence", "indented-code",
        "mixed-tab-indented-code", "html-comment",
    ),
)
def test_hidden_decision_record_variants_are_not_contract_evidence(replacement):
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Primary serialization: dynamic", replacement
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_scope_contract" in failed


@pytest.mark.parametrize(
    ("skill", "document", "wrapper"),
    [
        ("wordpress-planner.block", GOOD_BLOCK_PLANNER, "```markdown\n{}\n````"),
        ("wordpress-planner.migration", GOOD_GUTENBERG_MIGRATION_PLANNER, "~~~~md\n{}\n~~~~"),
        ("wordpress-planner.block", GOOD_BLOCK_PLANNER, "<!--\n{}\n-->"),
        ("wordpress-planner.migration", GOOD_GUTENBERG_MIGRATION_PLANNER, "<!--\n{}\n-->"),
    ],
)
def test_whole_hidden_document_cannot_satisfy_output_contract(skill, document, wrapper):
    result = oracle.validate_output(skill, wrapper.format(document))
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "required_output_headings" in failed


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea", "template"])
def test_whole_raw_html_code_block_cannot_satisfy_output_contract(tag):
    result = oracle.validate_output(
        "wordpress-planner.block",
        f"<{tag}>\n{GOOD_BLOCK_PLANNER}\n</{tag}>",
    )
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "required_output_headings" in failed


@pytest.mark.parametrize(
    "wrapper",
    [
        "<![CDATA[\n{}\n]]>",
        "<?raw\n{}\n?>",
        "<!DOCTYPE html\n{}\n>",
    ],
    ids=("cdata", "processing-instruction", "declaration"),
)
def test_whole_commonmark_raw_block_cannot_satisfy_output_contract(wrapper):
    result = oracle.validate_output(
        "wordpress-planner.block", wrapper.format(GOOD_BLOCK_PLANNER)
    )
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "required_output_headings" in failed


@pytest.mark.parametrize("tag", ["div", "section", "table", "details", "custom-element"])
def test_raw_html_block_opening_hides_following_contract_section(tag):
    result = oracle.validate_output(
        "wordpress-planner.block", f"<{tag}>\n{GOOD_BLOCK_PLANNER}\n</{tag}>"
    )
    headings = next(
        check for check in result["checks"] if check["id"] == "required_output_headings"
    )

    assert result["pass"] is False
    assert headings["passed"] is False


@pytest.mark.parametrize("tag", ["div", "section", "table"])
def test_type_six_raw_html_prefix_with_trailing_content_hides_record(tag):
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Primary serialization: dynamic",
        f'<{tag} style="display:none">hidden\nPrimary serialization: dynamic\n</{tag}>',
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_scope_contract" in failed


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        ('<span style="display:none">hidden', "</span>"),
        ("<a hidden>", "</a>"),
        ("<custom-element hidden>", "</custom-element>"),
    ],
)
def test_inline_html_wrapper_cannot_hide_authoritative_record(opening, closing):
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Primary serialization: dynamic",
        f"{opening}\nPrimary serialization: dynamic\n{closing}",
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_scope_contract" in failed


def test_list_continuation_cannot_supply_authoritative_decision_record():
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Primary serialization: dynamic",
        "- <span hidden>hidden\n  Primary serialization: dynamic\n  </span>",
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_scope_contract" in failed


def test_midline_html_opener_cannot_hide_authoritative_record():
    candidate = GOOD_BLOCK_PLANNER.replace(
        "Primary serialization: dynamic",
        "Prose <span hidden>\nPrimary serialization: dynamic\n</span>",
    )

    result = oracle.validate_output("wordpress-planner.block", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert "block_scope_contract" in failed


@pytest.mark.parametrize(
    ("skill", "document", "duplicate"),
    [
        (
            "wordpress-planner.block",
            GOOD_BLOCK_PLANNER,
            "## Block Scope\nBlock identity: acme/wrong\nPrimary serialization: static\n\n",
        ),
        (
            "wordpress-planner.migration",
            GOOD_GUTENBERG_MIGRATION_PLANNER,
            "## Target Mapping\nGutenberg target: post_content\nBlock mapping: core-only\nUnsupported content: accounted\n\n",
        ),
    ],
)
def test_duplicate_required_heading_is_rejected(skill, document, duplicate):
    result = oracle.validate_output(skill, duplicate + document)
    headings = next(
        check for check in result["checks"] if check["id"] == "required_output_headings"
    )

    assert result["pass"] is False
    assert headings["passed"] is False
    assert "duplicate headings" in headings["detail"]


def test_gutenberg_migration_plan_passes_domain_contract():
    result = oracle.validate_output(
        "wordpress-planner.migration", GOOD_GUTENBERG_MIGRATION_PLANNER
    )
    domain = {
        check["id"]: check["passed"]
        for check in result["checks"]
        if check["id"].startswith("gutenberg_migration_")
    }

    assert result["pass"] is True
    assert domain == {
        "gutenberg_migration_mapping_contract": True,
        "gutenberg_migration_serialization_contract": True,
        "gutenberg_migration_oracle_contract": True,
    }


def test_gutenberg_migration_plan_cannot_omit_semantic_or_editor_frontend_oracles():
    candidate = (
        GOOD_GUTENBERG_MIGRATION_PLANNER
        .replace("Semantic oracle: required", "Semantic oracle: skipped")
        .replace("Editor oracle: required", "Editor oracle: skipped")
        .replace("Frontend oracle: required", "Frontend oracle: skipped")
    )
    assert candidate != GOOD_GUTENBERG_MIGRATION_PLANNER
    result = oracle.validate_output("wordpress-planner.migration", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "gutenberg_migration_oracle_contract" in failed


def test_generic_semantic_and_fixture_flags_do_not_replace_bound_contract():
    candidate = (
        GOOD_GUTENBERG_MIGRATION_PLANNER
        .replace(
            "Semantic oracle fields: text,href,attributes,unsupported,freeform",
            "Semantic oracle fields: required",
        )
        .replace(
            "Fixture identity: article-42-rich-text",
            "Fixture identity: required",
        )
    )
    assert candidate != GOOD_GUTENBERG_MIGRATION_PLANNER

    result = oracle.validate_output("wordpress-planner.migration", candidate)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "gutenberg_migration_oracle_contract" in failed


def test_negated_gutenberg_decision_records_fail_all_domain_gates():
    candidate = (
        GOOD_GUTENBERG_MIGRATION_PLANNER
        .replace("Gutenberg target: post_content", "Gutenberg target: not defined")
        .replace("Block mapping: core+custom", "Block mapping: forbidden")
        .replace("Unsupported content: accounted", "Unsupported content: ignored")
        .replace("Serialization API: serialize_blocks", "Serialization API: forbidden")
        .replace("Rerun policy: idempotent", "Rerun policy: non-idempotent")
        .replace("Block validation oracle: parse_blocks", "Block validation oracle: skipped")
        .replace("Semantic oracle: required", "Semantic oracle: skipped")
        .replace("Editor oracle: required", "Editor oracle: skipped")
        .replace("Frontend oracle: required", "Frontend oracle: skipped")
    )

    result = oracle.validate_output("wordpress-planner.migration", candidate)
    failed = {
        check["id"] for check in result["checks"]
        if check["id"].startswith("gutenberg_migration_") and not check["passed"]
    }

    assert failed == {
        "gutenberg_migration_mapping_contract",
        "gutenberg_migration_serialization_contract",
        "gutenberg_migration_oracle_contract",
    }


def test_negative_block_prose_outside_decision_records_does_not_activate_migration_lane():
    candidate = (
        GOOD_CLASSIC_MIGRATION_PLANNER
        .replace(
            "Map title, body, and publication state",
            "Custom block mapping is out of scope. Map title, body, and publication state",
        )
        .replace(
            "Use `wp_kses_post()`",
            "Do not use serialize_blocks(). Use `wp_kses_post()`",
        )
        .replace(
            "Use `wp post list`",
            "parse_blocks and block validation are out of scope. Use `wp post list`",
        )
    )

    result = oracle.validate_output("wordpress-planner.migration", candidate)
    domain = [
        check["id"] for check in result["checks"]
        if check["id"].startswith("gutenberg_migration_")
    ]

    assert result["pass"] is True
    assert domain == ["gutenberg_migration_scope"]


def test_classic_post_content_migration_does_not_activate_gutenberg_contract():
    result = oracle.validate_output(
        "wordpress-planner.migration", GOOD_CLASSIC_MIGRATION_PLANNER
    )
    domain = {
        check["id"]: check["passed"]
        for check in result["checks"]
        if check["id"].startswith("gutenberg_migration_")
    }

    assert result["pass"] is True
    assert domain == {"gutenberg_migration_scope": True}


@pytest.mark.parametrize(
    "scope",
    [
        "This is not a Gutenberg or Block Editor migration.",
        "No Gutenberg transformation is planned; import classic posts.",
        "Import classic posts, not Gutenberg content.",
        "Import classic posts rather than Gutenberg blocks.",
    ],
)
def test_negative_gutenberg_scope_phrasings_do_not_activate_domain_contract(scope):
    candidate = GOOD_CLASSIC_MIGRATION_PLANNER.replace(
        "Gutenberg and the Block Editor are explicitly out of scope.", scope
    )

    result = oracle.validate_output("wordpress-planner.migration", candidate)
    domain = [
        check for check in result["checks"]
        if check["id"].startswith("gutenberg_migration_")
    ]

    assert result["pass"] is True
    assert [check["id"] for check in domain] == ["gutenberg_migration_scope"]


@pytest.mark.parametrize(
    "scope",
    [
        "Migrate article rows into Gutenberg without changing permalinks.",
        "Migrate article rows into Gutenberg blocks but exclude media.",
        "Migrate article rows into the Block Editor and do not change authors.",
    ],
)
def test_affirmative_gutenberg_target_survives_unrelated_negative_qualifier(scope):
    candidate = GOOD_CLASSIC_MIGRATION_PLANNER.replace(
        "Import CSV article rows into classic WordPress posts. Gutenberg and the Block Editor are explicitly out of scope.",
        scope,
    )

    result = oracle.validate_output("wordpress-planner.migration", candidate)
    failed = {
        check["id"] for check in result["checks"]
        if check["id"].startswith("gutenberg_migration_") and not check["passed"]
    }

    assert result["pass"] is False
    assert failed == {
        "gutenberg_migration_mapping_contract",
        "gutenberg_migration_serialization_contract",
        "gutenberg_migration_oracle_contract",
    }


def test_blanket_non_applicability_cannot_replace_exact_surfaces():
    check = oracle.check_exact_surfaces(
        "No exact WordPress API applies.",
        {"min_surfaces": 2},
    )

    assert check.passed is False
    assert "expected at least 2" in check.detail


def test_generic_argument_words_require_key_context():
    prose = oracle.check_exact_surfaces(
        "The category and description are useful prose labels.",
        {"min_surfaces": 2},
    )
    keys = oracle.check_exact_surfaces(
        "The schema requires `category` and `description`.",
        {"min_surfaces": 2},
    )

    assert prose.passed is False
    assert keys.passed is True


def test_exact_surface_matching_is_boundary_and_order_aware():
    partial = oracle.check_exact_surfaces(
        "current_user_canary and register_rest_routeable are custom names.",
        {"min_surfaces": 1},
    )
    scattered = oracle.check_exact_surfaces(
        "Use register_rest_route. In a separate sentence, add permission_callback.",
        {"min_surfaces": 2},
    )
    scattered_matches = oracle.find_surface_matches(
        "Use register_rest_route. In a separate sentence, add permission_callback."
    )
    exact = oracle.check_exact_surfaces(
        "Use current_user_can() and register_rest_route() permission_callback.",
        {"min_surfaces": 2},
    )

    assert partial.passed is False
    assert scattered.passed is False
    assert not any(match.category == "reviewed_composed" for match in scattered_matches)
    assert exact.passed is True
    assert "core_function:current_user_can()" in exact.detail
    assert "reviewed_composed:register_rest_route() permission_callback" in exact.detail


def test_permission_callback_key_context_supports_abilities_api():
    check = oracle.check_exact_surfaces(
        "Use wp_register_ability(). Configure `permission_callback` for the ability.",
        {"min_surfaces": 2},
    )

    assert check.passed is True
    assert "argument_key:permission_callback" in check.detail


@pytest.mark.parametrize(
    "statement",
    [
        "No exact WordPress API applies because this is external; verify it with the owner.",
        "No exact WordPress API applies to external CRM ownership; verify it with the CRM owner.",
        "No exact WordPress API applies to external CRM ownership because WordPress does not control it.",
    ],
)
def test_non_applicability_requires_scope_reason_and_oracle(statement):
    text = f"Use current_user_can() and register_post_type(). {statement}"

    check = oracle.check_exact_surfaces(text, {"min_surfaces": 2})

    assert check.passed is False
    assert "invalid non-applicability" in check.detail


def test_scoped_non_applicability_does_not_waive_surface_minimum():
    statement = (
        "No exact WordPress API applies to external CRM ownership because WordPress "
        "does not control the vendor account; verify it with the CRM owner against "
        "the vendor API contract."
    )

    too_few = oracle.check_exact_surfaces(
        f"Use current_user_can(). {statement}",
        {"min_surfaces": 2},
    )
    enough = oracle.check_exact_surfaces(
        f"Use current_user_can() and register_post_type(). {statement}",
        {"min_surfaces": 2},
    )

    assert too_few.passed is False
    assert enough.passed is True
    assert "scoped non-applicability" in enough.detail


@pytest.mark.parametrize(
    "statement",
    [
        "No exact WordPress API applies to foo bar because owner.",
        "No exact WordPress API applies to foo bar because yes; documentation.",
        "No exact WordPress API applies to external CRM ownership because the owner.",
    ],
)
def test_non_applicability_rejects_vacuous_scope_reason_and_oracle(statement):
    check = oracle.check_exact_surfaces(
        f"Use current_user_can() and register_post_type(). {statement}",
        {"min_surfaces": 2},
    )

    assert check.passed is False
    assert "invalid non-applicability" in check.detail


def test_dynamic_reviewed_hook_and_safe_project_path_match():
    check = oracle.check_exact_surfaces(
        "Handle wp_ajax_save_report in plugin/includes/class-report.php.",
        {"min_surfaces": 2},
    )

    assert check.passed is True
    assert "hook:wp_ajax_save_report" in check.detail
    assert "file_glob:plugin/includes/class-report.php" in check.detail


def test_dynamic_hook_and_path_matching_rejects_partial_and_traversal_forms():
    check = oracle.check_exact_surfaces(
        "Ignore my_wp_ajax_save, wp_ajax_, and ../plugin/includes/class-report.php.",
        {"min_surfaces": 1},
    )

    assert check.passed is False


@pytest.mark.parametrize(
    "unsafe",
    [
        "$current_user_can", "$obj->current_user_can()", "Fake::current_user_can()",
        "$wp", "@wp", "$obj->register_rest_route() permission_callback",
        "Fake::register_rest_route() permission_callback",
        "$obj -> current_user_can()", "$obj ?-> current_user_can()",
        "Fake :: current_user_can()", "@ current_user_can()",
        "$obj->child -> current_user_can()", "$objects[0] -> current_user_can()",
        "(new Fake()) -> current_user_can()", "get_service() -> current_user_can()",
        "$obj -> register_rest_route() permission_callback",
        "Fake :: register_rest_route() permission_callback",
        "@ register_rest_route() permission_callback",
        "$objects[0] -> register_rest_route() permission_callback",
    ],
)
def test_core_and_composed_surfaces_reject_non_global_contexts(unsafe):
    check = oracle.check_exact_surfaces(f"Inspect {unsafe}.", {"min_surfaces": 1})

    assert check.passed is False


@pytest.mark.parametrize(
    "unsafe",
    [
        "$wp_abilities_api_init", "Fake::wp_abilities_api_init", "Fake :: wp_abilities_api_init",
        "$promote_users", "$execute_callback", "$wp_ajax_save_report",
        "Fake::wp_ajax_save_report", "Fake :: wp_ajax_save_report", "@ wp_ajax_save_report",
        "$obj->child -> wp_abilities_api_init", "$objects[0] -> wp_ajax_save_report",
        "get_service() -> wp_abilities_api_init",
    ],
)
def test_typed_identifier_surfaces_reject_non_global_contexts(unsafe):
    check = oracle.check_exact_surfaces(f"Inspect {unsafe}.", {"min_surfaces": 1})

    assert check.passed is False


def test_quoted_global_callable_name_remains_exact_surface():
    check = oracle.check_exact_surfaces("Use 'current_user_can' as the callable.", {"min_surfaces": 1})

    assert check.passed is True


def test_safe_project_basenames_match_as_file_surfaces():
    check = oracle.check_exact_surfaces(
        "Use render.php, .wp-env.json, and current_user_can().",
        {"min_surfaces": 3},
    )

    assert check.passed is True
    assert "file_glob:render.php" in check.detail
    assert "file_glob:.wp-env.json" in check.detail


@pytest.mark.parametrize(
    "unsafe",
    ["../render.php", "/tmp/render.php", "../.wp-env.json", "render.php/evil", "dir\\render.php"],
)
def test_safe_project_basenames_reject_path_context(unsafe):
    check = oracle.check_exact_surfaces(f"Inspect {unsafe}.", {"min_surfaces": 1})

    assert check.passed is False


@pytest.mark.parametrize(
    ("category", "surface"),
    [("file_surfaces", "../outside.php"), ("wp_cli_commands", "security best practices")],
)
def test_output_catalog_rejects_unsafe_registry_entry(tmp_path, monkeypatch, category, surface):
    data = json.loads(oracle.REGISTRY_PATH.read_text(encoding="utf-8"))
    data["categories"][category].append(surface)
    path = tmp_path / "unsafe-registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(oracle, "REGISTRY_PATH", path)
    oracle._surface_catalog.cache_clear()

    try:
        with pytest.raises(ValueError, match=category):
            oracle.find_surface_matches("Use current_user_can().")
    finally:
        oracle._surface_catalog.cache_clear()


def test_output_catalog_rejects_blank_provenance(tmp_path, monkeypatch):
    data = json.loads(oracle.REGISTRY_PATH.read_text(encoding="utf-8"))
    data["provenance"]["reviewed_for"] = ""
    path = tmp_path / "blank-provenance.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(oracle, "REGISTRY_PATH", path)
    oracle._surface_catalog.cache_clear()
    try:
        with pytest.raises(ValueError, match="provenance"):
            oracle.find_surface_matches("Use current_user_can().")
    finally:
        oracle._surface_catalog.cache_clear()


def test_dot_notation_planner_alias_passes():
    result = oracle.validate_output("wordpress-planner.plugin", GOOD_PLANNER)

    assert result["pass"] is True
    assert result["skill"] == "wordpress-plugin-planner"
    assert result["requested_skill"] == "wordpress-planner.plugin"


def test_bad_planner_output_fails_contract_checks():
    result = oracle.validate_output("wordpress-plugin-planner", BAD_PLANNER)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert {"required_output_headings", "no_placeholders", "no_generic_wp_labels"} <= failed


def test_good_critic_output_passes():
    result = oracle.validate_output("wordpress-critic", GOOD_CRITIC)

    assert result["pass"] is True


def test_performance_verification_terms_are_contract_evidence():
    check = oracle.check_verification_specificity(
        "Measure before and after with Query Monitor, Core Web Vitals, "
        "browser performance trace, object-cache metrics, and "
        "`wp option list --autoload=on`."
    )

    assert check.passed is True
    assert "query monitor" in check.detail
    assert "wp option list" in check.detail


def test_migration_verification_terms_are_contract_evidence():
    check = oracle.check_verification_specificity(
        "Validate with `wp post list`, `wp media import`, "
        "`wp search-replace --dry-run`, a crawl comparison, "
        "launch rehearsal, and rollback test."
    )

    assert check.passed is True
    assert "wp post list" in check.detail
    assert "wp search-replace" in check.detail


def test_bad_critic_output_fails_verdict_and_headings():
    result = oracle.validate_output("wordpress-critic", BAD_CRITIC)
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert {"critic_verdict", "required_output_headings"} <= failed


def test_lowercase_placeholder_word_in_prose_is_not_marker():
    result = oracle.check_no_placeholders(
        "Replace placeholder values with the canonical plugin constants, but do not leave TODO markers."
    )

    assert result.passed is False

    clean = oracle.check_no_placeholders(
        "Replace placeholder values with the canonical plugin constants before release."
    )

    assert clean.passed is True


def test_generic_label_check_allows_numbered_rerun_test_references():
    allowed = oracle.check_no_generic_labels(
        "Rerun tests: import the redirect map, then run tests 4 and 5 again."
    )
    rejected = oracle.check_no_generic_labels("Use WordPress APIs and run tests.")

    assert allowed.passed is True
    assert rejected.passed is False


def test_security_critic_output_passes_without_sidecar_when_contract_is_met():
    result = oracle.validate_output("wordpress-security-critic", GOOD_SECURITY_CRITIC_WITH_GATE)

    assert result["pass"] is True
    assert "security_gate_consumption" not in {check["id"] for check in result["checks"]}


def test_security_gate_sidecar_requires_rule_and_suppression_consumption():
    result = oracle.validate_output(
        "wordpress-security-critic",
        GOOD_SECURITY_CRITIC_WITH_GATE,
        security_gate=SECURITY_GATE_REPORT,
    )

    assert result["pass"] is True
    assert any(check["id"] == "security_gate_consumption" and check["passed"] for check in result["checks"])

    weak_output = GOOD_SECURITY_CRITIC_WITH_GATE.replace(
        "WordPress.DB.PreparedSQL.InterpolatedNotPrepared",
        "the prepared SQL sniff",
    )
    weak_result = oracle.validate_output(
        "wordpress-security-critic",
        weak_output,
        security_gate=SECURITY_GATE_REPORT,
    )
    failed = {check["id"] for check in weak_result["checks"] if not check["passed"]}

    assert weak_result["pass"] is False
    assert "security_gate_consumption" in failed

    no_advisory = GOOD_SECURITY_CRITIC_WITH_GATE.replace(
        "Advisory gate-derived evidence includes\n`WordPress.DB.DirectDatabaseQuery.DirectQuery` at `acme-report/admin.php:40`.",
        "There is no advisory gate-derived evidence.",
    )
    no_advisory_result = oracle.validate_output(
        "wordpress-security-critic",
        no_advisory,
        security_gate=SECURITY_GATE_REPORT,
    )
    no_advisory_failed = {check["id"] for check in no_advisory_result["checks"] if not check["passed"]}

    assert no_advisory_result["pass"] is False
    assert "security_gate_consumption" in no_advisory_failed


def test_security_gate_sidecar_requires_file_bound_locations():
    loose_location = GOOD_SECURITY_CRITIC_WITH_GATE.replace(
        "`acme-report/admin.php:42`",
        "`acme-report/admin.php` near line 42",
    )

    result = oracle.validate_output(
        "wordpress-security-critic",
        loose_location,
        security_gate=SECURITY_GATE_REPORT,
    )
    failed = {check["id"] for check in result["checks"] if not check["passed"]}

    assert result["pass"] is False
    assert "security_gate_consumption" in failed


def test_cli_accepts_security_gate_sidecar(tmp_path, capsys):
    output = tmp_path / "candidate.md"
    gate = tmp_path / "security-gate.json"
    output.write_text(GOOD_SECURITY_CRITIC_WITH_GATE, encoding="utf-8")
    gate.write_text(json.dumps(SECURITY_GATE_REPORT), encoding="utf-8")

    rc = oracle.main(
        [
            "--skill",
            "wordpress-security-critic",
            "--output",
            str(output),
            "--security-gate",
            str(gate),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["pass"] is True
    assert captured.err == ""


def test_cli_missing_security_gate_fails_cleanly(tmp_path, capsys):
    output = tmp_path / "candidate.md"
    output.write_text(GOOD_SECURITY_CRITIC_WITH_GATE, encoding="utf-8")

    rc = oracle.main(
        [
            "--skill",
            "wordpress-security-critic",
            "--output",
            str(output),
            "--security-gate",
            str(tmp_path / "missing-security-gate.json"),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert rc == 1
    assert payload["pass"] is False
    assert "security gate file not found" in payload["error"]
