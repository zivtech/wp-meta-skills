#!/usr/bin/env python3
"""Oracle for fixture `dead-object-cache-dropin-tool-hangs`.

Contract: oracle.spec.yaml in this directory (design §5 row 12). Every
WP-CLI call in this oracle carries an explicit timeout: a still-faulted
site makes wp_cli hang for ~75s, so phase 1's own TTFB check fails long
before phase 2 is reached on a faulted site, and a fixed site answers in
under 2s — the 30s bound is generous headroom, not a tuned threshold.

Site layout assumed (design §2.4): `<site-dir>/app/public` (the WordPress
root, `backend.site_root`), `<site-dir>/conf/**`, `<site-dir>/logs/php/`.
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

ALLOWED_CHANGE_PATTERNS = ("wp-content/object-cache.php", "wp-content/object-cache.php.*")
DEBUG_CONSTANTS = ("WP_DEBUG", "WP_DEBUG_LOG", "SCRIPT_DEBUG")
WP_CLI_TIMEOUT = 30.0


def _site_dir(backend: lib.SiteBackend) -> Path:
    return backend.site_root.parent.parent


def run(
    backend: lib.SiteBackend,
    *,
    golden_hashes: dict[str, str],
    golden_conf_hashes: dict[str, str],
    golden_wp_config: str,
    golden_blogname: str,
    post_agent_log_offset: int,
    golden_plugin_list: list[dict[str, str]] | None = None,
    nonce_bytes: bytes | None = None,
) -> dict[str, object]:
    result = lib.OracleResult()
    nonce_bytes = nonce_bytes if nonce_bytes is not None else secrets.token_bytes(6)
    nonce = lib.nonce_hex(nonce_bytes)

    # --- Phase 1: symptom resolved (healthy ~0.1s; faulted ~75s or 504) -----------
    home_resp = backend.http_get("/", max_redirects=3)
    result.record(
        "homepage_fast_and_200",
        home_resp.status == 200 and home_resp.elapsed_seconds < 10.0,
        {"status": home_resp.status, "elapsed_seconds": home_resp.elapsed_seconds},
    )
    login_resp = backend.http_get("/wp-login.php", max_redirects=0)
    result.record(
        "login_page_fast_and_200",
        login_resp.status == 200 and login_resp.elapsed_seconds < 10.0,
        {"status": login_resp.status, "elapsed_seconds": login_resp.elapsed_seconds},
    )

    # --- Phase 2: functionality preserved ------------------------------------------
    result.record(
        "blogname_rendered",
        bool(re.search(rf'<h1 class="site-title">\s*<a[^>]*>{re.escape(golden_blogname)}</a>', home_resp.body)),
    )
    core_installed = backend.wp_cli("core is-installed", timeout_seconds=WP_CLI_TIMEOUT)
    result.record("core_is_installed", core_installed.returncode == 0 and not core_installed.timed_out)

    plugin_list_call = backend.wp_cli("plugin list --format=json", timeout_seconds=WP_CLI_TIMEOUT)
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
        result.record("plugin_list_call_succeeded", plugin_list_call.returncode == 0 and not plugin_list_call.timed_out)

    # --- Phase 3: no-collateral snapshot --------------------------------------------
    tail = backend.error_log_tail_after(post_agent_log_offset)
    result.record("no_fatal_after_post_agent_offset", not re.search(rb"(Fatal error|Parse error)", tail))

    # changes may be: object-cache.php removed, edited in place (still
    # present, different content — e.g. the fail-fast alt fix), or renamed
    # to a different name under wp-content/ (design §5 row 12). All three
    # are ⊆ ALLOWED_CHANGE_PATTERNS; distinguishing "edited-but-still-dead"
    # from "edited-and-fixed" is the job of phases 1/2/4 (TTFB, content),
    # not of the changed-file set.
    actual_hashes = backend.hash_site_tree()
    changed = lib.diff_trees(golden_hashes, actual_hashes)
    subset_ok, escaping = lib.changed_files_subset_of(changed, ALLOWED_CHANGE_PATTERNS)
    result.record("changed_files_subset_of_allowed", subset_ok, {"escaping": sorted(escaping)})

    conf_dir = _site_dir(backend) / "conf"
    actual_conf_hashes = lib.hash_tree(conf_dir, exclude=())
    result.record("conf_tree_unchanged", actual_conf_hashes == golden_conf_hashes)

    wp_config_bytes = backend.read_file("wp-config.php")
    wp_config_text = wp_config_bytes.decode("utf-8") if wp_config_bytes else ""
    diff = lib.semantic_wp_config_diff(wp_config_text, golden_wp_config, normalize_absent_as_false=DEBUG_CONSTANTS)
    result.record("wp_config_semantically_equal", diff.semantically_equal, {
        "unexpected_constant_diffs": list(diff.unexpected_constant_diffs), "residue_equal": diff.residue_equal,
    })

    # --- Phase 4: dynamic probe (fresh content must be served fast) ---------------
    probe_title = f"Probe {nonce}"
    probe_slug = f"probe-{nonce}"
    create = backend.wp_cli(
        f'post create --post_status=publish --post_title="{probe_title}" --post_name={probe_slug} --porcelain',
        timeout_seconds=WP_CLI_TIMEOUT,
    )
    probe_id = create.stdout.strip()
    probe_resp = backend.http_get(f"/{probe_slug}/")
    result.record(
        "dynamic_probe_fast_and_correct",
        probe_resp.status == 200 and probe_resp.elapsed_seconds < 10.0 and probe_title in probe_resp.body,
        {"status": probe_resp.status, "elapsed_seconds": probe_resp.elapsed_seconds},
    )

    # --- Phase 5: cleanup -----------------------------------------------------------
    if create.returncode == 0 and probe_id:
        cleanup = backend.wp_cli(f"post delete {probe_id} --force", timeout_seconds=WP_CLI_TIMEOUT)
        if cleanup.returncode != 0:
            result.warnings.append(f"cleanup failed to delete probe post {probe_id!r}")
    else:
        result.warnings.append("dynamic probe post was never created; nothing to clean up")

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
        golden_conf_hashes=lib.hash_tree(golden_dir / "conf", exclude=()),
        golden_wp_config=(golden_dir / "wp-config.php").read_text(),
        golden_blogname=os.environ.get("GOLDEN_BLOGNAME", "Acme Community"),
        post_agent_log_offset=int(os.environ["POST_AGENT_LOG_OFFSET"]),
        golden_plugin_list=golden_plugin_list,
    )
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
