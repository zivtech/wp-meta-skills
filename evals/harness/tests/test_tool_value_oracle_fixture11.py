"""End-to-end tests for fixture `wpconfig-in-parent-dir-tools-misreport`:
seed -> pre-oracle fail, reference-fixes -> pass, cheats -> fail.

# SEAM(stack): as in test_tool_value_oracle_fixture1.py, this simulates
HTTP/auth behavior in Python rather than talking to a live WordPress
instance. The simulation is driven by the same wp-config.php the real
seed/cheat/reference-fix scripts mutate, plus the fake wp-cli's user
records (login/password), so it is testing the oracle's actual decision
logic (redirect targets, cookie presence, wp-config resolution order) —
not a canned answer.
"""
from __future__ import annotations

import importlib.util
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
    / "evals" / "suites" / "localwp-agent-tools-value" / "fixtures" / "wpconfig-in-parent-dir-tools-misreport"
)
GOLDEN_WP_CONFIG = FIXTURE_DIR / "golden" / "wp-config.php"
FAKE_WP_SCRIPT = Path(__file__).resolve().parent / "tool_value_fake_wp.py"
HOST = "acme.local"


def _load_module(name: str, path: Path):
    # See test_tool_value_oracle_fixture1.py's _load_module: every
    # fixture's oracle.py is named "oracle.py", so a bare `import oracle`
    # would collide across fixtures within one pytest session.
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fixture11_oracle = _load_module("tool_value_fixture11_oracle", FIXTURE_DIR / "oracle.py")


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=10)


class FixtureElevenBackend(live.LiveSiteBackend):
    def __init__(self, wp_root: Path):
        super().__init__(
            site_root=wp_root,
            base_url=f"http://{HOST}",
            error_log_path=wp_root.parent / "logs" / "php" / "error.log",
            wp_cli_command=[sys.executable, str(FAKE_WP_SCRIPT), "--path", str(wp_root)],
        )

    def _force_ssl_admin(self) -> bool:
        config_path = self.resolve_wp_config()
        if config_path is None:
            return False
        constants = lib.parse_define_constants(config_path.read_text())
        return constants.get("FORCE_SSL_ADMIN", "false") not in ("false", "0", "")

    def http_get(self, path: str, *, max_redirects: int = 3, cookies=None, timeout: float = 10.0) -> lib.HttpResponse:
        broken = self._force_ssl_admin()
        cookies = cookies or {}
        authenticated = any(k.startswith("wordpress_logged_in_") for k in cookies)

        if path == "/":
            return lib.HttpResponse(200, {}, "<html><body>Acme Community</body></html>", f"{self.base_url}/")

        if path == "/wp-login.php":
            if broken:
                return lib.HttpResponse(302, {"Location": f"https://{HOST}/wp-login.php"}, "", f"{self.base_url}/wp-login.php")
            return lib.HttpResponse(200, {}, '<form name="loginform"></form>', f"{self.base_url}/wp-login.php")

        if path == "/wp-admin/":
            if authenticated and not broken:
                return lib.HttpResponse(200, {}, '<div id="adminmenu"></div>', f"{self.base_url}/wp-admin/")
            scheme = "https" if broken else "http"
            return lib.HttpResponse(302, {"Location": f"{scheme}://{HOST}/wp-login.php?redirect_to=%2Fwp-admin%2F"}, "", f"{self.base_url}/wp-admin/")

        return lib.HttpResponse(404, {}, "not found", f"{self.base_url}{path}")

    def http_post(self, path: str, *, form: dict[str, str], max_redirects: int = 0, cookies=None, timeout: float = 10.0) -> lib.HttpResponse:
        broken = self._force_ssl_admin()
        state = fake_wp.load_state(self.site_root)
        ok = any(u["login"] == form.get("log") and u["password"] == form.get("pwd") for u in state["users"])
        if not ok:
            return lib.HttpResponse(200, {}, '<div id="login_error">incorrect</div>', f"{self.base_url}{path}")
        scheme = "https" if broken else "http"
        redirect_to = form.get("redirect_to", f"http://{HOST}/wp-admin/")
        if broken:
            redirect_to = redirect_to.replace("http://", "https://")
        return lib.HttpResponse(
            302, {"Location": redirect_to, "Set-Cookie": "wordpress_logged_in_abc123=1; path=/"}, "", f"{self.base_url}{path}",
        )


@pytest.fixture()
def site(tmp_path: Path) -> Path:
    """<tmp>/app/public is the WordPress root; <tmp>/app/wp-config.php is
    the parent-dir config this fixture is about."""
    app_dir = tmp_path / "app"
    wp_root = app_dir / "public"
    wp_root.mkdir(parents=True)
    shutil.copy(GOLDEN_WP_CONFIG, app_dir / "wp-config.php")
    (wp_root.parent / "logs" / "php").mkdir(parents=True, exist_ok=True)
    (wp_root.parent / "logs" / "php" / "error.log").write_text("")
    # This fixture has no acme-events-style haystack plugin; start the fake
    # wp-cli's DB-shaped state clean rather than inheriting fixture 1's
    # default plugin list.
    fake_wp.save_state(wp_root, {
        "plugins": {}, "next_post_id": 1000, "posts": [], "users": [], "next_user_id": 2,
        "options": {"home": f"http://{HOST}", "siteurl": f"http://{HOST}"},
    })
    return wp_root


def _run_oracle(wp_root: Path, golden_hashes: dict[str, str]) -> dict[str, object]:
    backend = FixtureElevenBackend(wp_root)
    return fixture11_oracle.run(
        backend,
        golden_hashes=golden_hashes,
        golden_wp_config=GOLDEN_WP_CONFIG.read_text(),
        post_agent_log_offset=0,
        host=HOST,
        golden_plugin_list=[],
        nonce_bytes=b"\x01\x02\x03\x04\x05\x06",
        probe_password="correcthorsebatterystaple1",  # no spaces: passed through wp_cli's shlex-split args string
    )


def _golden_hashes(wp_root: Path) -> dict[str, str]:
    return lib.hash_tree(wp_root.parent)


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
    assert payload["checks"]["wp_admin_redirect_is_http_not_https"] is False


REFERENCE_FIXES = (
    "reference-fix.sh",
    "reference-fix-alt-set-false.sh",
)


@pytest.mark.parametrize("script_name", REFERENCE_FIXES)
def test_reference_fix_makes_the_oracle_pass(site: Path, script_name: str):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    fix = _run_script(FIXTURE_DIR / script_name, str(site))
    assert fix.returncode == 0, fix.stderr

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", (script_name, payload)


def test_reference_fix_alt_wp_config_set_makes_the_oracle_pass(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    fix = _run_script(
        FIXTURE_DIR / "reference-fix-alt-wp-config-set.sh", str(site), sys.executable, str(FAKE_WP_SCRIPT),
    )
    assert fix.returncode == 0, fix.stderr

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "pass", payload


def test_cheat_create_shadow_config_fails_the_oracle(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    # Fix the real config first (an agent following the tool's false "not
    # found" report might still shadow it even after "fixing" nothing) —
    # exercising the cheat on top of the still-seeded state, matching the
    # CI validity gate's reset->seed->cheat order (design §8).
    pre_cheat_hashes = lib.hash_tree(site.parent)
    cheat = _run_script(FIXTURE_DIR / "cheats" / "create-shadow-config-in-public.sh", str(site))
    assert cheat.returncode == 0, cheat.stderr
    assert lib.hash_tree(site.parent) != pre_cheat_hashes

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["no_shadow_config_in_wordpress_root"] is False


def test_cheat_option_update_siteurl_https_fails_the_oracle(site: Path):
    golden_hashes = _golden_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_state = fake_wp.load_state(site)
    cheat = _run_script(
        FIXTURE_DIR / "cheats" / "option-update-siteurl-https.sh", str(site), sys.executable, str(FAKE_WP_SCRIPT),
    )
    assert cheat.returncode == 0, cheat.stderr
    post_state = fake_wp.load_state(site)
    assert post_state != pre_state

    payload = _run_oracle(site, golden_hashes)
    assert payload["outcome"] == "fail", payload
    # Still broken (FORCE_SSL_ADMIN untouched) AND now collateral on siteurl.
    assert payload["checks"]["home_and_siteurl_unchanged"] is False
