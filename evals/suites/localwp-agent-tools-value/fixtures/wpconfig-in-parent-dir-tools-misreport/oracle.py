#!/usr/bin/env python3
"""Oracle for fixture `wpconfig-in-parent-dir-tools-misreport`.

Contract: oracle.spec.yaml in this directory (design §5 row 11). The
changed-file universe for this fixture is `app/**` (i.e. `app/public/**`
PLUS `app/wp-config.php`, which sits one level above the WordPress root) —
unlike fixture 1, the file the fault lives in is outside the WordPress root
entirely, which is the whole point of this fixture.

`run()` takes a `tool_value_oracle_lib.SiteBackend` whose `site_root` is the
WordPress root (app/public); the real wp-config.php is located via
`backend.resolve_wp_config()`, which walks up one directory the way real
WP-CLI does — deliberately not the MCP tool's own
`path.join(wpPath, 'wp-config.php')`-only lookup, which is exactly the trap
this fixture is built to test (design §1, §5 row 11).
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

ALLOWED_CHANGE_PATTERNS = ("wp-config.php",)
DEBUG_CONSTANTS = ("WP_DEBUG", "WP_DEBUG_LOG", "SCRIPT_DEBUG")
DIFF_ALLOWLIST = ("FORCE_SSL_ADMIN",)


def run(
    backend: lib.SiteBackend,
    *,
    golden_hashes: dict[str, str],
    golden_wp_config: str,
    post_agent_log_offset: int,
    host: str,
    golden_plugin_list: list[dict[str, str]] | None = None,
    nonce_bytes: bytes | None = None,
    probe_password: str | None = None,
) -> dict[str, object]:
    result = lib.OracleResult()
    nonce_bytes = nonce_bytes if nonce_bytes is not None else secrets.token_bytes(6)
    nonce = lib.nonce_hex(nonce_bytes)
    probe_password = probe_password or secrets.token_hex(8)

    # --- Phase 1: symptom resolved ------------------------------------------------
    login_resp = backend.http_get("/wp-login.php", max_redirects=0)
    result.record("login_page_reachable_over_http", login_resp.status == 200, {"status": login_resp.status})
    result.record("login_form_present", bool(re.search(r'<form[^>]+name="loginform"', login_resp.body)))

    admin_resp = backend.http_get("/wp-admin/", max_redirects=0)
    location = admin_resp.headers.get("Location", "")
    result.record("wp_admin_redirects_302", admin_resp.status == 302, {"status": admin_resp.status})
    result.record(
        "wp_admin_redirect_is_http_not_https",
        bool(re.match(rf"^http://{re.escape(host)}/wp-login\.php", location)),
        {"location": location},
    )

    home_resp = backend.http_get("/", max_redirects=3)
    result.record("homepage_reachable", home_resp.status == 200, {"status": home_resp.status})

    # --- Phase 2: functionality preserved ------------------------------------------
    config_path = backend.resolve_wp_config()
    config_source = config_path.read_text() if config_path else ""
    constants = lib.parse_define_constants(config_source)
    force_ssl = constants.get("FORCE_SSL_ADMIN", "false")
    result.record("force_ssl_admin_absent_or_false", force_ssl in ("false", "0", ""), {"value": force_ssl})

    config_path_call = backend.wp_cli("config path")
    result.record(
        "wp_cli_config_path_resolves_parent_dir",
        config_path_call.stdout.strip().endswith("/app/wp-config.php") or config_path_call.stdout.strip().endswith("wp-config.php"),
        {"stdout": config_path_call.stdout.strip()},
    )

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

    # --- Phase 3: no-collateral snapshot -------------------------------------------
    shadow_config_exists = backend.file_exists("wp-config.php")
    result.record("no_shadow_config_in_wordpress_root", not shadow_config_exists)

    tail = backend.error_log_tail_after(post_agent_log_offset)
    result.record("no_fatal_after_post_agent_offset", not re.search(rb"(Fatal error|Parse error)", tail))

    actual_hashes = lib.hash_tree(backend.site_root.parent)
    changed = lib.diff_trees(golden_hashes, actual_hashes)
    subset_ok, escaping = lib.changed_files_subset_of(changed, ALLOWED_CHANGE_PATTERNS)
    result.record("changed_files_subset_of_allowed", subset_ok, {"escaping": sorted(escaping)})

    diff = lib.semantic_wp_config_diff(
        config_source, golden_wp_config,
        normalize_absent_as_false=DEBUG_CONSTANTS, diff_allowlist=DIFF_ALLOWLIST,
    )
    result.record("wp_config_semantically_equal", diff.semantically_equal, {
        "unexpected_constant_diffs": list(diff.unexpected_constant_diffs), "residue_equal": diff.residue_equal,
    })

    home_option = backend.wp_cli("option get home")
    siteurl_option = backend.wp_cli("option get siteurl")
    result.record(
        "home_and_siteurl_unchanged",
        home_option.stdout.strip().startswith("http://") and siteurl_option.stdout.strip().startswith("http://"),
        {"home": home_option.stdout.strip(), "siteurl": siteurl_option.stdout.strip()},
    )

    # --- Phase 4: dynamic probe (sign in over http again) --------------------------
    login_name = f"probe_{nonce}"
    create = backend.wp_cli(
        f'user create {login_name} probe_{nonce}@example.invalid '
        f'--role=administrator --user_pass={probe_password} --porcelain'
    )
    probe_uid = create.stdout.strip()

    login_post = backend.http_post(
        "/wp-login.php", max_redirects=0,
        form={"log": login_name, "pwd": probe_password, "wp-submit": "Log In", "redirect_to": f"http://{host}/wp-admin/"},
    )
    post_location = login_post.headers.get("Location", "")
    result.record("login_post_redirects_to_http_wp_admin", bool(re.match(rf"^http://{re.escape(host)}/wp-admin/", post_location)), {"location": post_location})
    set_cookie = login_post.headers.get("Set-Cookie", "")
    result.record("login_sets_wordpress_logged_in_cookie", "wordpress_logged_in_" in set_cookie)

    admin_get = backend.http_get("/wp-admin/", max_redirects=0, cookies={"wordpress_logged_in_probe": "1"})
    result.record("wp_admin_loads_when_authenticated", admin_get.status == 200 and 'id="adminmenu"' in admin_get.body)

    # --- Phase 5: cleanup ------------------------------------------------------------
    if create.returncode == 0 and probe_uid:
        cleanup = backend.wp_cli(f"user delete {probe_uid} --yes")
        if cleanup.returncode != 0:
            result.warnings.append(f"cleanup failed to delete probe user {probe_uid!r}")
    else:
        result.warnings.append("probe user was never created; nothing to clean up")

    return result.finalize()


def _main() -> int:
    # SEAM(stack): needs the Lane H stack; see fixture 1's oracle.py _main()
    # for the identical environment contract this shares.
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
        golden_hashes=lib.hash_tree(golden_dir),
        golden_wp_config=(golden_dir / "wp-config.php").read_text(),
        post_agent_log_offset=int(os.environ["POST_AGENT_LOG_OFFSET"]),
        host=os.environ["SITE_HOST"],
        golden_plugin_list=golden_plugin_list,
    )
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
