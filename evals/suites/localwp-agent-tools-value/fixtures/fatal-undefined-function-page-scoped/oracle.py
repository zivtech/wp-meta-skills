#!/usr/bin/env python3
"""Oracle for fixture `fatal-undefined-function-page-scoped`.

Contract: oracle.spec.yaml in this directory (design §11.5). Order is
load-bearing: static checks, then the collateral snapshot, then the dynamic
probe, then cleanup — the collateral snapshot is taken BEFORE the dynamic
probe so the probe's own DB churn is never counted as collateral (design
finding 4).

`run()` takes a `tool_value_oracle_lib.SiteBackend` and is exercised in
tests against a fake backend (evals/harness/tests/test_tool_value_oracle_fixture1.py)
with no PHP, MySQL, or nginx anywhere. `_main()` wires up the real
`LiveSiteBackend` from environment variables for an actual Lane H run —
every network/WP-CLI call it makes is a `# SEAM(stack):` site, inherited
from tool_value_live_backend.LiveSiteBackend.
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

GOLDEN_EVENTS = [
    {"title": "Harvest Market", "date": "2026-10-03", "formatted": "Saturday, October 3, 2026"},
    {"title": "Winter Lights Walk", "date": "2026-12-12", "formatted": "Saturday, December 12, 2026"},
    {"title": "Spring Repair Cafe", "date": "2027-04-17", "formatted": "Saturday, April 17, 2027"},
]

ALLOWED_CHANGE_PATTERNS = ("wp-content/plugins/acme-events/**",)
DEBUG_CONSTANTS = ("WP_DEBUG", "WP_DEBUG_LOG", "SCRIPT_DEBUG")


def _extract_events_ul(body: str) -> list[str]:
    """Returns the <li>...</li> blocks inside the single acme-events <ul>, or []."""
    uls = re.findall(r'<ul class="acme-events">([\s\S]*?)</ul>', body)
    if len(uls) != 1:
        return []
    return re.findall(r"<li[\s>][\s\S]*?</li>", uls[0])


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

    # --- Phase 1: symptom resolved ------------------------------------------------
    resp = backend.http_get("/events/", max_redirects=3)
    result.record("symptom_resolved", resp.status == 200, {"status": resp.status, "final_url": resp.final_url})

    # --- Phase 2: functionality preserved (content, not markers; finding 4) ------
    li_items = _extract_events_ul(resp.body)
    result.record("events_ul_present_exactly_once", bool(re.findall(r'<ul class="acme-events">', resp.body)) and
                  len(re.findall(r'<ul class="acme-events">', resp.body)) == 1)
    result.record("has_three_li", len(li_items) == 3, {"count": len(li_items)})

    content_ok = True
    content_evidence: dict[str, str | None] = {}
    for event in GOLDEN_EVENTS:
        item = next((li for li in li_items if event["title"] in li), None)
        if item is None:
            content_ok = False
            content_evidence[event["title"]] = None
            continue
        time_match = re.search(r'<time class="acme-date">\s*([^<]+?)\s*</time>', item)
        actual_text = time_match.group(1) if time_match else None
        content_evidence[event["title"]] = actual_text
        if actual_text != event["formatted"]:
            content_ok = False
    result.record("event_dates_match_golden_format", content_ok, content_evidence)

    plugin_active = backend.wp_cli("plugin is-active acme-events")
    result.record("plugin_active", plugin_active.returncode == 0, {"returncode": plugin_active.returncode})

    # --- Phase 3: no-collateral snapshot (BEFORE the dynamic probe) --------------
    tail = backend.error_log_tail_after(post_agent_log_offset)
    has_fatal_after = bool(re.search(rb"(Fatal error|Parse error)", tail))
    result.record("no_fatal_after_post_agent_offset", not has_fatal_after, {"tail_bytes": len(tail)})

    actual_hashes = backend.hash_site_tree()
    changed = lib.diff_trees(golden_hashes, actual_hashes)
    subset_ok, escaping = lib.changed_files_subset_of(changed, ALLOWED_CHANGE_PATTERNS)
    result.record("changed_files_subset_of_allowed", subset_ok, {"escaping": sorted(escaping)})

    wp_config_bytes = backend.read_file("wp-config.php")
    wp_config_text = wp_config_bytes.decode("utf-8") if wp_config_bytes else ""
    diff = lib.semantic_wp_config_diff(
        wp_config_text, golden_wp_config, normalize_absent_as_false=DEBUG_CONSTANTS,
    )
    result.record("wp_config_semantically_equal", diff.semantically_equal, {
        "unexpected_constant_diffs": list(diff.unexpected_constant_diffs),
        "residue_equal": diff.residue_equal,
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
        result.record("plugin_list_matches_golden", actual_projected == golden_projected, {
            "actual": actual_projected, "golden": golden_projected,
        })
    else:
        result.warnings.append("golden_plugin_list not supplied; only checked wp_cli exit code")
        result.record("plugin_list_call_succeeded", plugin_list_call.returncode == 0)

    # --- Phase 4: dynamic probe (AFTER the collateral snapshot; finding 4) ------
    probe_title = f"Probe {nonce}"
    create = backend.wp_cli(
        "post create --post_type=event --post_status=publish "
        f'--post_title="{probe_title}" '
        '--meta_input=\'{"acme_event_date":"2027-03-14"}\' --porcelain'
    )
    probe_id = create.stdout.strip()

    probe_resp = backend.http_get("/events/")
    probe_li_items = _extract_events_ul(probe_resp.body)
    probe_item = next((li for li in probe_li_items if probe_title in li), None)
    probe_time_ok = False
    if probe_item is not None:
        match = re.search(r'<time class="acme-date">\s*([^<]+?)\s*</time>', probe_item)
        probe_time_ok = bool(match) and match.group(1) == "Sunday, March 14, 2027"
    result.record("dynamic_probe_renders_new_event", probe_item is not None and probe_time_ok, {
        "probe_title": probe_title, "found": probe_item is not None, "time_ok": probe_time_ok,
    })
    result.record("dynamic_probe_li_count_is_four", len(probe_li_items) == 4, {"count": len(probe_li_items)})

    # --- Phase 5: cleanup (never changes the outcome) ---------------------------
    if create.returncode == 0 and probe_id:
        cleanup = backend.wp_cli(f"post delete {probe_id} --force")
        if cleanup.returncode != 0:
            result.warnings.append(f"cleanup failed to delete probe post {probe_id!r}: {cleanup.stderr}")
    else:
        result.warnings.append("dynamic probe post was never created; nothing to clean up")

    return result.finalize()


def _main() -> int:
    # SEAM(stack): building a real LiveSiteBackend and calling run() against
    # it needs the Lane H stack (nginx + php-fpm + MariaDB laid out per
    # design §2.4) and a golden snapshot on disk; neither exists in this
    # repository yet (tracked as this build's item 4). The environment
    # contract below is the one the runner (evals/harness/run_localwp_tool_value_eval.py)
    # is expected to satisfy once that stack exists.
    import tool_value_live_backend as live  # local import: only needed for a real run

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
