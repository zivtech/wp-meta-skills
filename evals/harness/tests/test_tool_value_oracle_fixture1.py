"""End-to-end tests for fixture `fatal-undefined-function-page-scoped`:
seed -> pre-oracle fail, each reference-fix -> pass, each cheat -> fail
(design §8's CI validity gate, run here against a fake WordPress instead of
a live Lane H stack).

# SEAM(stack): nothing here talks to real PHP, MySQL, or nginx.
`FixtureOneBackend` (below) subclasses the production `LiveSiteBackend` so
its filesystem methods (hash_site_tree, read_file, error_log_tail_after)
and its `wp_cli` method (shelled out to `tool_value_fake_wp.py`, a small
wp-cli stand-in — see that module's docstring) are exercised for real; only
`http_get`/`http_post` are overridden with a hand-written renderer that
inspects the plugin PHP source the same seed/cheat/reference-fix scripts
mutate, to decide what a live PHP process would have rendered. This is
exactly the seam the design's own §8 CI-validity gate needs a stack for; the
renderer's job is to let that gate's *shape* (reset, seed, cheat, oracle
must fail; reference-fix, oracle must pass) run without one.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import tool_value_live_backend as live  # noqa: E402
import tool_value_oracle_lib as lib  # noqa: E402
import tool_value_fake_wp as fake_wp  # noqa: E402

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "evals" / "suites" / "localwp-agent-tools-value" / "fixtures" / "fatal-undefined-function-page-scoped"
)
GOLDEN_PLUGIN_SRC = FIXTURE_DIR / "plugins" / "acme-events"
GOLDEN_WP_CONFIG = FIXTURE_DIR / "golden" / "wp-config.php"
FAKE_WP_SCRIPT = Path(__file__).resolve().parent / "tool_value_fake_wp.py"


def _load_module(name: str, path: Path):
    # Every fixture's oracle.py is a plain file named "oracle.py"; a bare
    # `import oracle` after a sys.path.insert would collide across fixtures
    # within one pytest session (whichever loads first wins the
    # sys.modules["oracle"] slot). Load each under a fixture-qualified name
    # instead.
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fixture1_oracle = _load_module("tool_value_fixture1_oracle", FIXTURE_DIR / "oracle.py")

PLUGIN_RELPATH = "wp-content/plugins/acme-events/acme-events.php"
TEMPLATE_RELPATH = "wp-content/plugins/acme-events/templates/events-list.php"


def _golden_format(date_str: str) -> str:
    date = datetime.date.fromisoformat(date_str)
    return f"{date.strftime('%A, %B')} {date.day}, {date.year}"


def test_golden_format_matches_the_oracles_table():
    for event in fixture1_oracle.GOLDEN_EVENTS:
        assert _golden_format(event["date"]) == event["formatted"]


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args], capture_output=True, text=True, timeout=10,
    )


class FixtureOneBackend(live.LiveSiteBackend):
    """Real filesystem + wp_cli (via the fake wp-cli), simulated HTTP."""

    def __init__(self, site_root: Path, *, theme_dir: str = "wp-content/themes/faketheme"):
        super().__init__(
            site_root=site_root,
            base_url="http://acme.local",
            error_log_path=site_root / "logs" / "php" / "error.log",
            wp_cli_command=[sys.executable, str(FAKE_WP_SCRIPT), "--path", str(site_root)],
        )
        self.theme_dir = theme_dir

    def http_get(self, path: str, *, max_redirects: int = 3, cookies=None, timeout: float = 10.0) -> lib.HttpResponse:
        if path != "/events/":
            return lib.HttpResponse(404, {}, "not found", f"{self.base_url}{path}")
        return self._render_events_page()

    def _resolve_formatter(self, plugin_source: str, template_source: str):
        """Returns a callable(date_str) -> str, or None if acme_format_date
        would be undefined (the fatal). Models the load-order the real
        seed/reference-fix/cheat scripts create (see the module docstring)."""
        require_unconditional = (
            "require_once __DIR__ . '/includes/formatting.php';" in plugin_source
            and "if ( is_admin() ) {\n\trequire_once __DIR__ . '/includes/formatting.php';" not in plugin_source
        )
        guarded_by_function_exists = "if ( ! function_exists( 'acme_format_date' ) ) {\n\trequire_once __DIR__" in plugin_source
        template_requires_formatting = "includes/formatting.php" in template_source

        if require_unconditional or guarded_by_function_exists or template_requires_formatting:
            return _golden_format

        # Appended definitions in acme-events.php (stub-in-plugin-dir cheat,
        # reference-fix-alt-reimplement, fix-but-leave-debug-on which is the
        # unconditional-require case above and never reaches here).
        if "function acme_format_date( $date ) {" in plugin_source:
            if "return (string) $date;" in plugin_source:
                return lambda raw: raw
            if "strtotime" in plugin_source:
                return _golden_format

        theme_functions = self.site_root / self.theme_dir / "functions.php"
        if theme_functions.is_file() and "function acme_format_date( $date ) {" in theme_functions.read_text():
            return lambda raw: raw

        return None

    def _render_events_page(self) -> lib.HttpResponse:
        state = fake_wp.load_state(self.site_root)
        if state["plugins"].get("acme-events") != "active":
            return lib.HttpResponse(200, {}, "<html><body>Acme Community</body></html>", f"{self.base_url}/events/")

        plugin_file = self.site_root / PLUGIN_RELPATH
        if not plugin_file.is_file():
            return lib.HttpResponse(500, {}, "There has been a critical error on this website.", f"{self.base_url}/events/")
        plugin_source = plugin_file.read_text()

        template_file = self.site_root / TEMPLATE_RELPATH
        if not template_file.is_file():
            return lib.HttpResponse(200, {}, "<html><body>theme default, no acme-events ul</body></html>", f"{self.base_url}/events/")
        template_source = template_file.read_text()

        if "acme_format_date" not in template_source and "<time class=\"acme-date\">" in template_source and "$acme_event_date" not in template_source:
            # hardcode-template.sh: fully static, no formatter call, no probe visibility.
            li = "".join(
                f'<li><a href="#">{e["title"]}</a> <time class="acme-date">{e["formatted"]}</time></li>'
                for e in fixture1_oracle.GOLDEN_EVENTS
            )
            return lib.HttpResponse(200, {}, f'<ul class="acme-events">{li}</ul>', f"{self.base_url}/events/")

        formatter = self._resolve_formatter(plugin_source, template_source)
        if formatter is None:
            return lib.HttpResponse(500, {}, "There has been a critical error on this website.", f"{self.base_url}/events/")

        events = list(fixture1_oracle.GOLDEN_EVENTS) + [
            {"title": p["title"], "date": p["meta"].get("acme_event_date", "")}
            for p in state["posts"] if p["post_type"] == "event" and p["post_status"] == "publish"
        ]

        formatter_called = "<time class=\"acme-date\"></time>" not in template_source or "$acme_event_date" in template_source
        if not formatter_called:
            li = "".join(
                f'<li><a href="#">{e["title"]}</a> <time class="acme-date"></time></li>' for e in events
            )
        else:
            li = "".join(
                f'<li><a href="#">{e["title"]}</a> <time class="acme-date">{formatter(e["date"])}</time></li>'
                for e in events
            )
        return lib.HttpResponse(200, {}, f'<ul class="acme-events">{li}</ul>', f"{self.base_url}/events/")


@pytest.fixture()
def site(tmp_path: Path) -> Path:
    root = tmp_path / "app_public"
    (root / "wp-content" / "plugins").mkdir(parents=True)
    shutil.copytree(GOLDEN_PLUGIN_SRC, root / "wp-content" / "plugins" / "acme-events")
    shutil.copy(GOLDEN_WP_CONFIG, root / "wp-config.php")
    (root / "logs" / "php").mkdir(parents=True)
    (root / "logs" / "php" / "error.log").write_text("")
    return root


def _golden_hashes(site_root: Path) -> dict[str, str]:
    """Hashes of the just-provisioned (unseeded) site, used as "golden" for
    changed-file comparisons in these tests."""
    return lib.hash_tree(site_root)


def _run_oracle(site_root: Path, golden_hashes: dict[str, str]) -> dict[str, object]:
    backend = FixtureOneBackend(site_root)
    return fixture1_oracle.run(
        backend,
        golden_hashes=golden_hashes,
        golden_wp_config=GOLDEN_WP_CONFIG.read_text(),
        post_agent_log_offset=0,
        golden_plugin_list=[{"name": "acme-events", "status": "active"}],
        nonce_bytes=b"\x01\x02\x03\x04\x05\x06",
    )


def test_golden_site_oracle_passes_before_any_fault(site: Path):
    golden_hashes = _golden_hashes(site)
    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", payload


def test_seed_makes_the_oracle_fail(site: Path):
    golden_hashes = _golden_hashes(site)
    seed = _run_script(FIXTURE_DIR / "seed.sh", str(site))
    assert seed.returncode == 0, seed.stderr

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["symptom_resolved"] is False


def test_reference_fix_makes_the_oracle_pass(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    fix = _run_script(FIXTURE_DIR / "reference-fix.sh", str(site))
    assert fix.returncode == 0, fix.stderr

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", payload


REFERENCE_FIX_ALTS = (
    "reference-fix-alt-template-require.sh",
    "reference-fix-alt-guard.sh",
    "reference-fix-alt-reimplement.sh",
    "reference-fix-alt-after-debug-toggle.sh",
)


@pytest.mark.parametrize("script_name", REFERENCE_FIX_ALTS)
def test_reference_fix_alt_makes_the_oracle_pass(site: Path, script_name: str):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    fix = _run_script(FIXTURE_DIR / script_name, str(site))
    assert fix.returncode == 0, fix.stderr

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", (script_name, payload)


FILE_ONLY_CHEATS = (
    "delete-template.sh",
    "comment-out-call.sh",
    "fix-but-leave-debug-on.sh",
    "mask-with-debug-display-off.sh",
    "stub-in-plugin-dir.sh",
    "hardcode-template.sh",
)


@pytest.mark.parametrize("cheat_name", FILE_ONLY_CHEATS)
def test_cheat_makes_the_oracle_fail(site: Path, cheat_name: str):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    # exclude=() here deliberately: this is the test suite's own
    # cheat-validity gate ("did the cheat mutate anything at all"), not the
    # oracle's no-collateral check. wp-config.php is excluded from the
    # oracle's default hash_tree (it gets its own semantic comparison, per
    # tool_value_oracle_lib's DEFAULT_CHANGED_FILE_EXCLUSIONS), but
    # mask-with-debug-display-off.sh only touches wp-config.php, so this
    # gate must look at it directly or it would wrongly see "no change".
    pre_cheat_hashes = lib.hash_tree(site, exclude=())

    cheat = _run_script(FIXTURE_DIR / "cheats" / cheat_name, str(site))
    assert cheat.returncode == 0, (cheat_name, cheat.stderr)

    # CI-validity-gate rule (design §8): the cheat must have changed
    # something relative to the seeded state, or a no-op cheat would "prove"
    # the oracle rejects it for the wrong reason.
    post_cheat_hashes = lib.hash_tree(site, exclude=())
    assert post_cheat_hashes != pre_cheat_hashes, f"{cheat_name} left the site byte-identical to the seeded state"

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", (cheat_name, payload)


def test_stub_function_in_theme_cheat_escapes_the_allowed_dir(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_cheat_hashes = lib.hash_tree(site)

    cheat = _run_script(
        FIXTURE_DIR / "cheats" / "stub-function-in-theme.sh", str(site), "wp-content/themes/faketheme",
    )
    assert cheat.returncode == 0, cheat.stderr
    assert lib.hash_tree(site) != pre_cheat_hashes

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", payload
    # Specifically caught by the collateral check, not the render (the
    # theme stub makes the page render correctly, per real PHP semantics —
    # only the changed-file set gives the cheat away).
    assert payload["checks"]["changed_files_subset_of_allowed"] is False


def test_deactivate_cheat_fails_the_oracle_via_db_state(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    # deactivate.sh needs a live plugin-activation state; the DB-only cheat
    # documented in cheats/deactivate.sh's own header. Point it at the fake
    # wp-cli so "exited 0 and changed something" is checkable as a state
    # diff instead of a changed-file diff (design §8's rule, DB variant).
    pre_state = fake_wp.load_state(site)

    cheat = _run_script(
        FIXTURE_DIR / "cheats" / "deactivate.sh", str(site), sys.executable, str(FAKE_WP_SCRIPT),
    )
    assert cheat.returncode == 0, cheat.stderr
    post_state = fake_wp.load_state(site)
    assert post_state != pre_state, "deactivate.sh did not change plugin-activation state"
    assert post_state["plugins"]["acme-events"] == "inactive"

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["plugin_active"] is False


def test_dynamic_probe_defeats_hardcode_template_cheat_specifically(site: Path):
    """Narrower assertion pinning *why* hardcode-template.sh fails: phases
    1-3 all pass, and only the dynamic probe (phase 4) catches it — this is
    the scenario the probe was built for (design finding 4)."""
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    assert _run_script(FIXTURE_DIR / "cheats" / "hardcode-template.sh", str(site)).returncode == 0

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail"
    assert payload["checks"]["symptom_resolved"] is True
    assert payload["checks"]["has_three_li"] is True
    assert payload["checks"]["event_dates_match_golden_format"] is True
    assert payload["checks"]["dynamic_probe_renders_new_event"] is False


def test_dynamic_probe_defeats_stub_in_plugin_dir_via_content_not_dynamic_probe(site: Path):
    """stub-in-plugin-dir.sh is caught earlier, at phase 2's content check —
    pin that too, so the two "formerly spec stub" cheats are shown failing
    for their documented, *different* reasons (design finding 4)."""
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    assert _run_script(FIXTURE_DIR / "cheats" / "stub-in-plugin-dir.sh", str(site)).returncode == 0

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail"
    assert payload["checks"]["symptom_resolved"] is True
    assert payload["checks"]["event_dates_match_golden_format"] is False
    evidence = payload["evidence"]["event_dates_match_golden_format"]
    assert evidence["Harvest Market"] == "2026-10-03"  # raw meta value, not the golden formatted string
