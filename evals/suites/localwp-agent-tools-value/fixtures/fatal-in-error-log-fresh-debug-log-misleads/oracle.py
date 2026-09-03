#!/usr/bin/env python3
"""Oracle for fixture `fatal-in-error-log-fresh-debug-log-misleads`.

Contract: oracle.spec.yaml in this directory (design §5 row 13). This
fixture's whole point is a tool defect (`read_error_log`'s newer-mtime
heuristic), not anything the oracle itself has to model — the oracle reads
`logs/php/error.log` directly, the same way C0/C1 would with `tail`, and
never goes near the mtime heuristic at all. What the oracle DOES have to
protect is the herring: `acme-cache`'s files must stay hash-identical to
golden (an agent that "fixes" the herring instead of the real fault is
exactly the failure mode this fixture is built to catch).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[4] / "harness"
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import tool_value_oracle_lib as lib  # noqa: E402

ALLOWED_CHANGE_PATTERNS = ("wp-content/plugins/acme-forms/**",)
DEBUG_CONSTANTS = ("WP_DEBUG", "WP_DEBUG_LOG", "SCRIPT_DEBUG")
GOLDEN_TITLE = "Get in touch"
NONCE_FIELD_RE = re.compile(r'name="acme_forms_nonce"\s+value="[0-9a-f]{10}"')


def run(
    backend: lib.SiteBackend,
    *,
    golden_hashes: dict[str, str],
    golden_wp_config: str,
    post_agent_log_offset: int,
    golden_plugin_list: list[dict[str, str]] | None = None,
    nonce_bytes: bytes | None = None,
) -> dict[str, object]:
    result = lib.OracleResult()
    nonce_bytes = nonce_bytes if nonce_bytes is not None else secrets.token_bytes(6)
    nonce = lib.nonce_hex(nonce_bytes)

    # --- Phase 1: symptom resolved --------------------------------------------------
    resp = backend.http_get("/contact/", max_redirects=3)
    result.record("symptom_resolved", resp.status == 200, {"status": resp.status})

    # --- Phase 2: functionality preserved --------------------------------------------
    result.record("form_present_exactly_once", len(re.findall(r'<form class="acme-form"', resp.body)) == 1)
    result.record("has_name_field", 'name="acme_name"' in resp.body)
    result.record("has_email_field", 'name="acme_email"' in resp.body)
    result.record("has_real_nonce_field", bool(NONCE_FIELD_RE.search(resp.body)))
    result.record(
        "golden_title_rendered",
        f'<h2 class="acme-form-title">{GOLDEN_TITLE}</h2>' in resp.body,
    )
    plugin_active = backend.wp_cli("plugin is-active acme-forms")
    result.record("plugin_active", plugin_active.returncode == 0)

    # --- Phase 3: no-collateral snapshot ----------------------------------------------
    tail = backend.error_log_tail_after(post_agent_log_offset)
    result.record("no_fatal_after_post_agent_offset", not re.search(rb"(Fatal error|Parse error)", tail))

    actual_hashes = backend.hash_site_tree()
    changed = lib.diff_trees(golden_hashes, actual_hashes)
    subset_ok, escaping = lib.changed_files_subset_of(changed, ALLOWED_CHANGE_PATTERNS)
    result.record("changed_files_subset_of_allowed", subset_ok, {"escaping": sorted(escaping)})
    result.record(
        "acme_cache_untouched",
        lib.files_hash_identical(golden_hashes, actual_hashes, "wp-content/plugins/acme-cache/**"),
    )

    wp_config_bytes = backend.read_file("wp-config.php")
    wp_config_text = wp_config_bytes.decode("utf-8") if wp_config_bytes else ""
    diff = lib.semantic_wp_config_diff(wp_config_text, golden_wp_config, normalize_absent_as_false=DEBUG_CONSTANTS)
    result.record("wp_config_semantically_equal", diff.semantically_equal, {
        "unexpected_constant_diffs": list(diff.unexpected_constant_diffs), "residue_equal": diff.residue_equal,
    })

    plugin_list_call = backend.wp_cli("plugin list --format=json")
    if golden_plugin_list is not None:
        try:
            actual_rows = json.loads(plugin_list_call.stdout or "[]")
        except json.JSONDecodeError:
            actual_rows = None
        actual_projected = (
            sorted(({"name": r.get("name"), "status": r.get("status")} for r in actual_rows), key=lambda r: r["name"])
            if isinstance(actual_rows, list) else None
        )
        golden_projected = sorted(
            ({"name": r["name"], "status": r["status"]} for r in golden_plugin_list), key=lambda r: r["name"],
        )
        result.record("plugin_list_matches_golden", actual_projected == golden_projected)
    else:
        result.warnings.append("golden_plugin_list not supplied; only checked wp_cli exit code")
        result.record("plugin_list_call_succeeded", plugin_list_call.returncode == 0)

    # --- Phase 4: dynamic probe (defeats hard-coded form markup) --------------------
    probe_title = f"Probe {nonce}"
    backend.wp_cli(f'option update acme_forms_title "{probe_title}"')
    probe_resp = backend.http_get("/contact/")
    result.record(
        "dynamic_probe_title_updates",
        f'<h2 class="acme-form-title">{probe_title}</h2>' in probe_resp.body,
    )
    result.record("dynamic_probe_nonce_still_real", bool(NONCE_FIELD_RE.search(probe_resp.body)))

    # --- Phase 5: cleanup -------------------------------------------------------------
    restore = backend.wp_cli(f'option update acme_forms_title "{GOLDEN_TITLE}"')
    if restore.returncode != 0:
        result.warnings.append("cleanup failed to restore acme_forms_title")

    return result.finalize()


def _main() -> int:
    # SEAM(stack): needs the Lane H stack; see fixture 1's oracle.py _main().
    import tool_value_live_backend as live

    site_root = Path(os.environ["SITE_ROOT"])
    golden_dir = Path(os.environ["GOLDEN_DIR"])
    backend = live.LiveSiteBackend(
        site_root=site_root,
        base_url=os.environ["SITE_BASE_URL"],
        error_log_path=Path(os.environ["SITE_ERROR_LOG"]),
        wp_cli_command=os.environ["WP_CLI_COMMAND"].split(),
    )
    golden_plugin_list_path = golden_dir / "plugin-list.json"
    golden_plugin_list = (
        json.loads(golden_plugin_list_path.read_text()) if golden_plugin_list_path.is_file() else None
    )
    payload = run(
        backend,
        golden_hashes=lib.hash_tree(golden_dir / "public"),
        golden_wp_config=(golden_dir / "wp-config.php").read_text(),
        post_agent_log_offset=int(os.environ["POST_AGENT_LOG_OFFSET"]),
        golden_plugin_list=golden_plugin_list,
    )
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
