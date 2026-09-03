"""End-to-end tests for fixture `fatal-in-error-log-fresh-debug-log-misleads`:
seed -> pre-oracle fail, reference-fixes -> pass, cheats -> fail.

# SEAM(stack): as in the other fixture test files, HTTP rendering is
simulated by inspecting the same PHP source the real seed/cheat/
reference-fix scripts mutate (call-site method name, presence of an alias
method, a try/catch wrapper, or fully static markup), rather than by
executing PHP. This fixture's actual defect (the tool's newer-mtime log
heuristic) lives entirely in the fork's `findErrorLog()`, not in anything
the oracle inspects — the oracle only ever reads `logs/php/error.log`
directly, so there is nothing mtime-related to simulate here at all.
"""
from __future__ import annotations

import importlib.util
import re
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
    / "evals" / "suites" / "localwp-agent-tools-value" / "fixtures" / "fatal-in-error-log-fresh-debug-log-misleads"
)
GOLDEN_WP_CONFIG = FIXTURE_DIR / "golden" / "wp-config.php"
FAKE_WP_SCRIPT = Path(__file__).resolve().parent / "tool_value_fake_wp.py"
HOST = "acme.local"
GOLDEN_TITLE = "Get in touch"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fixture13_oracle = _load_module("tool_value_fixture13_oracle", FIXTURE_DIR / "oracle.py")

CLASS_RELPATH = "wp-content/plugins/acme-forms/includes/class-acme-forms.php"
TEMPLATE_RELPATH = "wp-content/plugins/acme-forms/templates/contact.php"


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=10)


class FixtureThirteenBackend(live.LiveSiteBackend):
    def __init__(self, wp_root: Path):
        super().__init__(
            site_root=wp_root,
            base_url=f"http://{HOST}",
            error_log_path=wp_root / "logs" / "php" / "error.log",
            wp_cli_command=[sys.executable, str(FAKE_WP_SCRIPT), "--path", str(wp_root)],
        )

    def http_get(self, path: str, *, max_redirects: int = 3, cookies=None, timeout: float = 10.0) -> lib.HttpResponse:
        if path != "/contact/":
            return lib.HttpResponse(404, {}, "not found", f"{self.base_url}{path}")
        return self._render_contact_page()

    def _render_contact_page(self) -> lib.HttpResponse:
        state = fake_wp.load_state(self.site_root)
        if state["plugins"].get("acme-forms") != "active":
            return lib.HttpResponse(200, {}, "<html><body>generic page</body></html>", f"{self.base_url}/contact/")

        template_file = self.site_root / TEMPLATE_RELPATH
        if not template_file.is_file():
            return lib.HttpResponse(200, {}, "<html><body>theme default</body></html>", f"{self.base_url}/contact/")
        template_source = template_file.read_text()

        if "CHEAT: static markup" in template_source:
            return lib.HttpResponse(200, {}, template_source_to_static_html(), f"{self.base_url}/contact/")

        class_file = self.site_root / CLASS_RELPATH
        class_source = class_file.read_text() if class_file.is_file() else ""

        rendered = self._effective_render(class_source, state)
        if rendered is None:
            return lib.HttpResponse(500, {}, "There has been a critical error on this website.", f"{self.base_url}/contact/")
        return lib.HttpResponse(200, {}, rendered, f"{self.base_url}/contact/")

    def _effective_render(self, class_source: str, state: dict) -> str | None:
        title = state.get("options", {}).get("acme_forms_title", GOLDEN_TITLE)
        nonce_value = "1234567890"
        form_html = (
            '<div class="acme-form">'
            f'<h2 class="acme-form-title">{title}</h2>'
            '<form class="acme-form" method="post">'
            '<input type="text" name="acme_name" />'
            '<input type="email" name="acme_email" />'
            f'<input type="hidden" name="acme_forms_nonce" value="{nonce_value}" />'
            '</form></div>'
        )

        if "catch ( \\Error $e )" in class_source or "catch (\\Error $e)" in class_source:
            return ""  # swallowed: renders nothing

        calls_correct_method = "return $instance->render_fields();" in class_source
        has_alias = "public function render_feilds() {" in class_source
        if calls_correct_method or has_alias:
            return form_html
        return None  # calls render_feilds(), no alias defined -> fatal


def template_source_to_static_html() -> str:
    return (
        '<div class="acme-form">'
        f'<h2 class="acme-form-title">{GOLDEN_TITLE}</h2>'
        '<form class="acme-form" method="post">'
        '<input type="text" name="acme_name" />'
        '<input type="email" name="acme_email" />'
        '<input type="hidden" name="acme_forms_nonce" value="deadbeef00" />'
        '</form></div>'
    )


@pytest.fixture()
def site(tmp_path: Path) -> Path:
    wp_root = tmp_path / "app_public"
    (wp_root / "wp-content" / "plugins").mkdir(parents=True)
    shutil.copytree(
        FIXTURE_DIR / "plugins" / "acme-forms", wp_root / "wp-content" / "plugins" / "acme-forms",
    )
    shutil.copytree(
        FIXTURE_DIR / "plugins" / "acme-cache", wp_root / "wp-content" / "plugins" / "acme-cache",
    )
    shutil.copy(GOLDEN_WP_CONFIG, wp_root / "wp-config.php")
    (wp_root / "logs" / "php").mkdir(parents=True)
    (wp_root / "logs" / "php" / "error.log").write_text("")
    # Golden ships a pre-existing debug.log — acme-cache's two-day history
    # of "hits/misses" lines (design §5 row 13). A stub is enough here; the
    # oracle excludes debug.log from the changed-file diff either way.
    (wp_root / "wp-content" / "debug.log").write_text("[stub] acme-cache: 0 hits / 0 misses (/)\n")
    fake_wp.save_state(wp_root, {
        "plugins": {"acme-forms": "active", "acme-cache": "active"},
        "next_post_id": 1000, "posts": [], "users": [], "next_user_id": 2,
        "options": {"acme_forms_title": GOLDEN_TITLE, "home": f"http://{HOST}", "siteurl": f"http://{HOST}"},
    })
    return wp_root


def _golden_hashes(wp_root: Path) -> dict[str, str]:
    return lib.hash_tree(wp_root)


def _run_oracle(wp_root: Path, golden_hashes: dict[str, str]) -> dict[str, object]:
    backend = FixtureThirteenBackend(wp_root)
    return fixture13_oracle.run(
        backend,
        golden_hashes=golden_hashes,
        golden_wp_config=GOLDEN_WP_CONFIG.read_text(),
        post_agent_log_offset=0,
        golden_plugin_list=[{"name": "acme-forms", "status": "active"}, {"name": "acme-cache", "status": "active"}],
        nonce_bytes=b"\x01\x02\x03\x04\x05\x06",
    )


def test_golden_site_oracle_passes_before_any_fault(site: Path):
    golden_hashes = _golden_hashes(site)
    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", payload


def test_seed_makes_the_oracle_fail(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["symptom_resolved"] is False


REFERENCE_FIXES = ("reference-fix.sh", "reference-fix-alt-alias-method.sh")


@pytest.mark.parametrize("script_name", REFERENCE_FIXES)
def test_reference_fix_makes_the_oracle_pass(site: Path, script_name: str):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    fix = _run_script(FIXTURE_DIR / script_name, str(site))
    assert fix.returncode == 0, fix.stderr

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", (script_name, payload)


FILE_ONLY_CHEATS = (
    "silence-acme-cache-logging.sh",
    "delete-debug-log.sh",
    "hardcode-form-markup.sh",
    "catch-and-swallow.sh",
)


@pytest.mark.parametrize("cheat_name", FILE_ONLY_CHEATS)
def test_cheat_makes_the_oracle_fail(site: Path, cheat_name: str):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    # debug.log is deliberately excluded from hash_tree's diff (design's
    # own changed_file_exclusions — it churns on every request by design),
    # so delete-debug-log.sh's "changed something" evidence has to be
    # checked directly rather than through the standard hash diff.
    debug_log = site / "wp-content" / "debug.log"
    pre_cheat_hashes = lib.hash_tree(site)
    pre_cheat_debug_log_exists = debug_log.is_file()

    cheat = _run_script(FIXTURE_DIR / "cheats" / cheat_name, str(site))
    assert cheat.returncode == 0, (cheat_name, cheat.stderr)
    changed = lib.hash_tree(site) != pre_cheat_hashes or debug_log.is_file() != pre_cheat_debug_log_exists
    assert changed, f"{cheat_name} left the site byte-identical to the seeded state"

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", (cheat_name, payload)


@pytest.mark.parametrize("cheat_name,plugin", [
    ("deactivate-acme-forms.sh", "acme-forms"),
    ("deactivate-acme-cache.sh", "acme-cache"),
])
def test_deactivate_cheat_fails_the_oracle_via_db_state(site: Path, cheat_name: str, plugin: str):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_state = fake_wp.load_state(site)

    cheat = _run_script(FIXTURE_DIR / "cheats" / cheat_name, str(site), sys.executable, str(FAKE_WP_SCRIPT))
    assert cheat.returncode == 0, cheat.stderr
    post_state = fake_wp.load_state(site)
    assert post_state != pre_state
    assert post_state["plugins"][plugin] == "inactive"

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", (cheat_name, payload)


def test_hardcode_form_markup_defeats_only_the_dynamic_probe(site: Path):
    """Pins *why* hardcode-form-markup.sh fails: static checks pass, only
    the title-update probe catches it (design finding 4)."""
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    assert _run_script(FIXTURE_DIR / "cheats" / "hardcode-form-markup.sh", str(site)).returncode == 0

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail"
    assert payload["checks"]["symptom_resolved"] is True
    assert payload["checks"]["has_real_nonce_field"] is True
    assert payload["checks"]["golden_title_rendered"] is True
    assert payload["checks"]["dynamic_probe_title_updates"] is False
