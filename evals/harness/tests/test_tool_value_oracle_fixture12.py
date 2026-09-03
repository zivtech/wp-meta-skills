"""End-to-end tests for fixture `dead-object-cache-dropin-tool-hangs`:
seed -> pre-oracle fail, reference-fixes -> pass, cheats -> fail.

# SEAM(stack): TTFB is simulated (parsed from the drop-in's own backoff
array / a "FAIL-FAST" marker the alt reference-fix writes) rather than
measured against a live PHP process that actually sleeps — actually
sleeping 75 real seconds per test case would make this suite unusable. The
simulation is driven by the same file content the real seed/cheat/
reference-fix scripts mutate, so it is exercising the oracle's actual
threshold logic (elapsed_seconds < 10.0), not a canned answer.
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
    / "evals" / "suites" / "localwp-agent-tools-value" / "fixtures" / "dead-object-cache-dropin-tool-hangs"
)
GOLDEN_WP_CONFIG = FIXTURE_DIR / "golden" / "wp-config.php"
FAKE_WP_SCRIPT = Path(__file__).resolve().parent / "tool_value_fake_wp.py"
HOST = "acme.local"
GOLDEN_BLOGNAME = "Acme Community"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fixture12_oracle = _load_module("tool_value_fixture12_oracle", FIXTURE_DIR / "oracle.py")


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=10)


class FixtureTwelveBackend(live.LiveSiteBackend):
    def __init__(self, wp_root: Path):
        super().__init__(
            site_root=wp_root,
            base_url=f"http://{HOST}",
            error_log_path=wp_root.parent.parent / "logs" / "php" / "error.log",
            wp_cli_command=[sys.executable, str(FAKE_WP_SCRIPT), "--path", str(wp_root)],
        )

    def _simulated_ttfb(self) -> float:
        dropin = self.site_root / "wp-content" / "object-cache.php"
        if not dropin.is_file():
            return 0.1
        source = dropin.read_text()
        if "FAIL-FAST" in source:
            return 0.1
        match = __import__("re").search(r"array\(\s*([\d,\s]+)\)", source)
        if not match:
            return 0.1
        return float(sum(int(n) for n in match.group(1).split(",")))

    def http_get(self, path: str, *, max_redirects: int = 3, cookies=None, timeout: float = 10.0) -> lib.HttpResponse:
        ttfb = self._simulated_ttfb()
        if path == "/" or path == "/wp-login.php":
            body = f'<h1 class="site-title"><a href="#">{GOLDEN_BLOGNAME}</a></h1>' if path == "/" else "<form></form>"
            return lib.HttpResponse(200, {}, body, f"{self.base_url}{path}", elapsed_seconds=ttfb)
        if path.startswith("/probe-"):
            state = fake_wp.load_state(self.site_root)
            title = ""
            for post in state["posts"]:
                if path.strip("/") == post.get("slug"):
                    title = post["title"]
            return lib.HttpResponse(200, {}, title, f"{self.base_url}{path}", elapsed_seconds=ttfb)
        return lib.HttpResponse(404, {}, "not found", f"{self.base_url}{path}", elapsed_seconds=ttfb)

    def wp_cli(self, args: str, *, timeout_seconds: float | None = None) -> lib.WpCliResult:
        ttfb = self._simulated_ttfb()
        bound = timeout_seconds if timeout_seconds is not None else self.default_wp_cli_timeout
        if ttfb > bound:
            return lib.WpCliResult(-1, "", "simulated: drop-in backoff exceeds the wp-cli bound", timed_out=True)
        return super().wp_cli(args, timeout_seconds=timeout_seconds)


@pytest.fixture()
def site(tmp_path: Path) -> Path:
    site_dir = tmp_path / "acme-site"
    wp_root = site_dir / "app" / "public"
    wp_root.mkdir(parents=True)
    (wp_root / "wp-content").mkdir()
    shutil.copy(GOLDEN_WP_CONFIG, wp_root / "wp-config.php")
    (site_dir / "logs" / "php").mkdir(parents=True)
    (site_dir / "logs" / "php" / "error.log").write_text("")
    (site_dir / "conf" / "nginx").mkdir(parents=True)
    (site_dir / "conf" / "nginx" / "nginx.conf").write_text("fastcgi_read_timeout 60s;\n")
    # Golden ships a stray, unrelated cache directory (design's "moved from
    # our old host" narrative) so delete-unrelated-cache-dir.sh has
    # something real to delete.
    (wp_root / "wp-content" / "cache").mkdir()
    (wp_root / "wp-content" / "cache" / "stale.bin").write_text("leftover from the old host\n")
    fake_wp.save_state(wp_root, {
        "plugins": {"acme-seo": "active", "acme-forms": "active"},
        "next_post_id": 1000, "posts": [], "users": [], "next_user_id": 2,
        "options": {"home": f"http://{HOST}", "siteurl": f"http://{HOST}"},
    })
    return wp_root


def _golden_hashes(wp_root: Path) -> dict[str, str]:
    return lib.hash_tree(wp_root)


def _golden_conf_hashes(wp_root: Path) -> dict[str, str]:
    return lib.hash_tree(wp_root.parent.parent / "conf", exclude=())


def _run_oracle(wp_root: Path, golden_hashes: dict[str, str], golden_conf_hashes: dict[str, str]) -> dict[str, object]:
    backend = FixtureTwelveBackend(wp_root)
    return fixture12_oracle.run(
        backend,
        golden_hashes=golden_hashes,
        golden_conf_hashes=golden_conf_hashes,
        golden_wp_config=GOLDEN_WP_CONFIG.read_text(),
        golden_blogname=GOLDEN_BLOGNAME,
        post_agent_log_offset=0,
        golden_plugin_list=[{"name": "acme-seo", "status": "active"}, {"name": "acme-forms", "status": "active"}],
        nonce_bytes=b"\x01\x02\x03\x04\x05\x06",
    )


def test_golden_site_oracle_passes_before_any_fault(site: Path):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "pass", payload


def test_seed_makes_the_oracle_fail(site: Path):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0

    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["homepage_fast_and_200"] is False


REFERENCE_FIXES = (
    "reference-fix.sh",
    "reference-fix-alt-rename.sh",
    "reference-fix-alt-fail-fast.sh",
)


@pytest.mark.parametrize("script_name", REFERENCE_FIXES)
def test_reference_fix_makes_the_oracle_pass(site: Path, script_name: str):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    fix = _run_script(FIXTURE_DIR / script_name, str(site))
    assert fix.returncode == 0, fix.stderr

    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "pass", (script_name, payload)


def test_cheat_raise_nginx_timeout_fails_the_oracle(site: Path):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_conf_hashes = lib.hash_tree(site.parent.parent / "conf", exclude=())

    cheat = _run_script(FIXTURE_DIR / "cheats" / "raise-nginx-timeout.sh", str(site.parent.parent))
    assert cheat.returncode == 0, cheat.stderr
    assert lib.hash_tree(site.parent.parent / "conf", exclude=()) != pre_conf_hashes

    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["conf_tree_unchanged"] is False
    assert payload["checks"]["homepage_fast_and_200"] is False  # still slow either way


def test_cheat_shorten_backoff_fails_the_oracle(site: Path):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_cheat_hashes = lib.hash_tree(site)

    cheat = _run_script(FIXTURE_DIR / "cheats" / "shorten-backoff-to-59s.sh", str(site))
    assert cheat.returncode == 0, cheat.stderr
    assert lib.hash_tree(site) != pre_cheat_hashes

    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["homepage_fast_and_200"] is False  # 59s still >= 10s threshold


def test_cheat_deactivate_all_plugins_fails_the_oracle(site: Path):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_state = fake_wp.load_state(site)

    cheat = _run_script(
        FIXTURE_DIR / "cheats" / "deactivate-all-plugins.sh", str(site), sys.executable, str(FAKE_WP_SCRIPT),
    )
    assert cheat.returncode == 0, cheat.stderr
    assert fake_wp.load_state(site) != pre_state

    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "fail", payload
    assert payload["checks"]["plugin_list_matches_golden"] is False


def test_cheat_delete_unrelated_cache_dir_fails_the_oracle(site: Path):
    golden_hashes, golden_conf_hashes = _golden_hashes(site), _golden_conf_hashes(site)
    assert _run_script(FIXTURE_DIR / "seed.sh", str(site)).returncode == 0
    pre_cheat_hashes = lib.hash_tree(site)

    cheat = _run_script(FIXTURE_DIR / "cheats" / "delete-unrelated-cache-dir.sh", str(site))
    assert cheat.returncode == 0, cheat.stderr
    assert lib.hash_tree(site) != pre_cheat_hashes

    payload = _run_oracle(site, golden_hashes, golden_conf_hashes)
    assert payload["outcome"] == "fail", payload
    # symptom persists AND the deletion is itself unexpected collateral
    assert payload["checks"]["homepage_fast_and_200"] is False
    assert payload["checks"]["changed_files_subset_of_allowed"] is False
