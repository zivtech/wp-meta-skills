"""Contract tests for the WordPress environment probe.

Three scenarios are the actual definition of done:

A. Fully degraded - an empty host must still yield a schema-valid manifest.
B. The version-truth trap - a documented-but-absent command must fail a
   deterministic gate end to end, through validate_wordpress_skill_output.
C. Golden manifest - a normalised manifest is committed as a fixture so schema
   drift is visible in review.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import probe_wordpress_environment as probe
import validate_wordpress_skill_output as output_oracle

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "capability_manifest"
GOLDEN_WP_ENV = FIXTURES / "golden-wp-env-docker.json"

FAKE_WP_TEMPLATE = """#!{interpreter}
import json
import sys

CLI_VERSION = {cli_version!r}
BANNER = {banner!r}
FAILING = set({failing!r})

args = [token for token in sys.argv[1:] if not token.startswith("-")]
flags = [token for token in sys.argv[1:] if token.startswith("-")]

if "--info" in flags:
    sys.stdout.write(BANNER)
    raise SystemExit(0)

path = " ".join(args)
if path in FAILING or any(path.startswith(entry + " ") for entry in FAILING):
    sys.stderr.write("'%s' is not a registered wp command.\\n" % path)
    raise SystemExit(1)
if path == "cli version":
    sys.stdout.write("WP-CLI %s\\n" % CLI_VERSION)
elif path == "core version":
    sys.stdout.write("7.0.3\\n")
elif path.startswith("core is-installed"):
    raise SystemExit(0)
elif path.startswith("option get"):
    sys.stdout.write("http://localhost:8888\\n")
elif path.startswith("plugin list"):
    sys.stdout.write(json.dumps([
        {{"name": "plugin-check", "status": "active", "version": "2.0.0"}},
    ]) + "\\n")
elif path.startswith("theme list"):
    sys.stdout.write("[]\\n")
elif path.startswith("eval"):
    sys.stdout.write(json.dumps({{"php": "8.3.14", "wp": "7.0.3", "multisite": False}}) + "\\n")
raise SystemExit(0)
"""

DEFAULT_BANNER = "OS:\tDarwin\nWP-CLI version:\t2.12.0\n"


def _install_fake_wp(
    tmp_path: Path,
    *,
    cli_version: str = "2.12.0",
    banner: str = DEFAULT_BANNER,
    failing: tuple[str, ...] = ("help ability", "help block", "help doctor", "help profile"),
) -> Path:
    """Write a fake `wp` onto a private PATH directory and return that dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "wp"
    script.write_text(
        FAKE_WP_TEMPLATE.format(
            interpreter=sys.executable,
            cli_version=cli_version,
            banner=banner,
            failing=list(failing),
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    root.mkdir()
    (root / "wp-config.php").write_text("<?php\n", encoding="utf-8")
    return root


def _run_probe(root: Path, path_dirs: list[str], *, allow_eval: bool = False) -> dict:
    env_path = os.pathsep.join(path_dirs)
    previous = os.environ.get("PATH")
    os.environ["PATH"] = env_path
    try:
        return probe.probe(root, allow_eval=allow_eval, argv=["probe", "--path", str(root)])
    finally:
        if previous is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous


def _schema_errors(manifest: dict) -> list[str]:
    return probe.validate_against_schema(manifest, probe.load_schema())


# --- Scenario A: fully degraded ---------------------------------------------


def test_scenario_a_bare_host_still_produces_a_valid_manifest(tmp_path: Path) -> None:
    """No wp, no markers, no composer, no node. It must not crash and must not raise."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    root = tmp_path / "nothing"
    root.mkdir()

    manifest = _run_probe(root, [str(empty_bin)])

    assert _schema_errors(manifest) == []
    assert manifest["environment"]["status"] == "UNKNOWN"
    assert manifest["environment"]["kind"] == "UNKNOWN"
    assert manifest["environment"]["invocation_prefix"] is None
    assert all(value is False for value in manifest["capabilities"].values())
    assert manifest["blockers"], "a degraded environment must populate blockers"
    assert probe.evidence_gaps(manifest) == []


def test_scenario_a_cli_entry_point_exits_zero_on_a_bare_host(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    root = tmp_path / "nothing"
    root.mkdir()
    out = tmp_path / "capability-manifest.json"

    completed = subprocess.run(
        [sys.executable, str(Path(probe.__file__)), "--path", str(root), "--out", str(out)],
        env={"PATH": str(empty_bin), "PYTHONPATH": str(Path(probe.__file__).parent)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert _schema_errors(manifest) == []
    assert "manifest_schema_invalid" not in {entry["code"] for entry in manifest["blockers"]}


# --- Scenario B: the version-truth trap --------------------------------------


def test_scenario_b_documented_command_absent_from_stable_phar(tmp_path: Path) -> None:
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(tmp_path)

    manifest = _run_probe(root, [str(bin_dir)])

    assert manifest["wp_cli"]["status"] == "AVAILABLE"
    assert manifest["wp_cli"]["version"] == "2.12.0"
    assert manifest["wp_cli"]["is_stable_release"] is True
    ability = manifest["wp_cli"]["commands"]["ability"]
    assert ability["status"] == "UNAVAILABLE"
    assert ability["reason"] == "command_documented_but_not_in_stable_phar"
    assert manifest["wp_cli"]["commands"]["block"]["reason"] == (
        "command_documented_but_not_in_stable_phar"
    )
    assert manifest["wp_cli"]["commands"]["plugin"]["status"] == "AVAILABLE"
    assert _schema_errors(manifest) == []
    assert probe.evidence_gaps(manifest) == []


def test_scenario_b_manifest_fails_an_output_that_instructs_wp_ability(tmp_path: Path) -> None:
    """The end-to-end test: the manifest must change an outcome."""
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(tmp_path)
    manifest = _run_probe(root, [str(bin_dir)])

    candidate = "## Verification\n\nRun `wp ability list --format=json` to confirm the surface.\n"
    check = output_oracle.check_capability_grounding(candidate, manifest)

    assert check.id == "capability_grounding"
    assert check.weight == 3
    assert check.passed is False
    assert "command_documented_but_not_in_stable_phar" in check.detail


def test_scenario_b_grounded_output_passes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(tmp_path)
    manifest = _run_probe(root, [str(bin_dir)])

    candidate = "## Verification\n\nRun `wp plugin list --format=json` to inventory plugins.\n"
    check = output_oracle.check_capability_grounding(candidate, manifest)

    assert check.passed is True


def test_capability_grounding_names_unresolved_states_instead_of_passing_silently() -> None:
    manifest = {
        "wp_cli": {"status": "AVAILABLE", "commands": {"doctor": {"status": "UNKNOWN"}}},
        "verification_tools": {"phpstan": {"status": "BLOCKED", "reason": "composer_missing"}},
    }
    candidate = "Run `wp doctor check --all` and `vendor/bin/phpstan analyse src`.\n"

    check = output_oracle.check_capability_grounding(candidate, manifest)

    assert check.passed is True
    assert "wp doctor: UNKNOWN" in check.detail
    assert "phpstan: BLOCKED" in check.detail


def test_capability_grounding_fails_unavailable_verification_tool() -> None:
    manifest = {
        "wp_cli": {"status": "AVAILABLE", "commands": {}},
        "verification_tools": {"phpstan": {"status": "UNAVAILABLE", "reason": "phpstan_absent"}},
    }
    candidate = "Run `vendor/bin/phpstan analyse src` before shipping.\n"

    check = output_oracle.check_capability_grounding(candidate, manifest)

    assert check.passed is False
    assert "phpstan_absent" in check.detail


def test_capability_grounding_is_skipped_without_the_sidecar() -> None:
    text = (FIXTURES.parent / "a_short_valid_heading.md").read_text(encoding="utf-8")
    result = output_oracle.validate_output("wordpress-planner", text)

    assert "capability_grounding" not in {check["id"] for check in result["checks"]}


def test_scenario_b_cli_flag_fails_the_run(tmp_path: Path) -> None:
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(tmp_path)
    manifest = _run_probe(root, [str(bin_dir)])
    manifest_path = tmp_path / "capability-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    candidate = tmp_path / "candidate.md"
    candidate.write_text("Run `wp ability list` to enumerate abilities.\n", encoding="utf-8")

    code = output_oracle.main(
        [
            "--skill",
            "wordpress-planner",
            "--output",
            str(candidate),
            "--capability-manifest",
            str(manifest_path),
        ]
    )

    assert code == 1


# --- Scenario C: golden manifest ---------------------------------------------


def test_scenario_c_golden_manifest_is_schema_valid_and_stable() -> None:
    golden = json.loads(GOLDEN_WP_ENV.read_text(encoding="utf-8"))

    assert _schema_errors(golden) == []
    assert probe.normalize_manifest(golden) == golden, "golden fixture must already be normalised"
    assert probe.evidence_gaps(golden) == []
    assert golden["environment"]["kind"] == "wp-env"
    assert golden["environment"]["wp_env_runtime"] == "docker"


REQUIRE_TOOL_ENV = "WP_META_SKILLS_REQUIRE_TOOL"
WP_ENV_PATH_ENV = "WP_META_SKILLS_WP_ENV_PATH"


@pytest.mark.real_wp_env
def test_scenario_c_live_wp_env_matches_the_golden_manifest() -> None:
    """Opt in with WP_META_SKILLS_REQUIRE_TOOL=wp-env.

    Point WP_META_SKILLS_WP_ENV_PATH at the wp-env project root. It defaults to
    the current working directory, which under pytest is the repo root - not a
    wp-env project - so the default is only useful when the suite is invoked
    from a project directory. Once opted in the test fails closed: a missing
    tool is a failure, not a silent skip. Without the opt-in it reports exactly
    how to request it.
    """
    required = os.environ.get(REQUIRE_TOOL_ENV, "")
    if "wp-env" not in required.split(","):
        pytest.skip(f"set {REQUIRE_TOOL_ENV}=wp-env to run the live wp-env probe")
    assert shutil.which("wp-env") or shutil.which("npx"), (
        f"{REQUIRE_TOOL_ENV}=wp-env was requested but neither wp-env nor npx is on PATH"
    )
    root = Path(os.environ.get(WP_ENV_PATH_ENV) or Path.cwd()).resolve()
    # argv mirrors the golden's recorded invocation exactly, so the two
    # normalise to the same probe_argv. Passing str(root) here would instead
    # normalise to "<normalized>" and never match the recorded "." token.
    manifest = probe.probe(
        root, allow_eval=False, argv=["probe_wordpress_environment.py", "--path", "."]
    )

    golden = json.loads(GOLDEN_WP_ENV.read_text(encoding="utf-8"))
    assert probe.normalize_manifest(manifest) == golden


# --- Safety: the denylist ----------------------------------------------------


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["wp", "db", "drop"], "db drop"),
        (["wp", "search-replace", "old.test", "new.test"], "search-replace"),
        (["wp", "--path=/srv/site", "db", "drop"], "db drop"),
        (["wp", "@production", "db", "drop"], "db drop"),
        (["wp-env", "run", "cli", "wp", "post", "delete", "5"], "post delete"),
        (["wp", "plugin", "list", "--format=json"], None),
        (["wp", "option", "get", "siteurl"], None),
    ],
)
def test_denylist_classification(argv: list[str], expected: str | None) -> None:
    assert probe._denylist_hit(argv) == expected


@pytest.mark.parametrize("argv", [["wp", "db", "drop"], ["wp", "search-replace", "a", "b"]])
def test_runner_refuses_destructive_commands(tmp_path: Path, argv: list[str]) -> None:
    runner = probe.ProbeRunner(tmp_path, allow_eval=True)

    with pytest.raises(probe.DenylistViolation):
        runner.run("test", argv)

    assert runner.evidence == [], "a refused command must leave no evidence"


def test_eval_is_refused_unless_allow_eval_is_set(tmp_path: Path) -> None:
    runner = probe.ProbeRunner(tmp_path, allow_eval=False)

    with pytest.raises(probe.DenylistViolation):
        runner.run("test", ["wp", "eval", "echo 1;"], eval_exception=True)


# --- Safety: --allow-eval defaults off ---------------------------------------


def test_allow_eval_defaults_to_false() -> None:
    args = probe.build_parser().parse_args(["--path", "."])

    assert args.allow_eval is False


def test_manifest_records_which_fact_path_was_taken(tmp_path: Path) -> None:
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(tmp_path)

    without = _run_probe(root, [str(bin_dir)], allow_eval=False)
    with_eval = _run_probe(root, [str(bin_dir)], allow_eval=True)

    assert without["allow_eval"] is False
    assert "facts_from_core_version_fallback" in without["wordpress"]["notes"]
    assert "facts_from_wp_eval" not in without["wordpress"]["notes"]
    assert not any(
        "eval" in entry["argv"] for entry in without["evidence"]
    ), "eval must not run when --allow-eval is off"

    assert with_eval["allow_eval"] is True
    assert "facts_from_wp_eval" in with_eval["wordpress"]["notes"]
    assert with_eval["wordpress"]["php_version"] == "8.3.14"
    assert with_eval["wordpress"]["is_multisite"] is False


# --- Safety: redaction -------------------------------------------------------


PLANTED_APPLICATION_PASSWORD = "abcd EFGH ijkl MNOP qrst UVWX"
PLANTED_DB_PASSWORD = "hunter2-not-in-the-manifest"


def test_redaction_strips_planted_credentials() -> None:
    sample = (
        f"application password {PLANTED_APPLICATION_PASSWORD} here\n"
        f"define('DB_PASSWORD', '{PLANTED_DB_PASSWORD}');\n"
        "path /Users/someone/Local Sites/demo\n"
    )

    scrubbed = probe._redact(sample)

    assert PLANTED_APPLICATION_PASSWORD not in scrubbed
    assert PLANTED_DB_PASSWORD not in scrubbed
    assert "/Users/someone" not in scrubbed
    assert "~/Local Sites/demo" in scrubbed


def test_planted_credentials_never_reach_the_manifest(tmp_path: Path) -> None:
    root = _project(tmp_path)
    banner = (
        "OS:\tDarwin\nWP-CLI version:\t2.12.0\n"
        f"application password {PLANTED_APPLICATION_PASSWORD}\n"
        f"define('DB_PASSWORD', '{PLANTED_DB_PASSWORD}');\n"
        f"inline DB_USER={PLANTED_DB_PASSWORD} mid-line\n"
    )
    bin_dir = _install_fake_wp(tmp_path, banner=banner)

    manifest = _run_probe(root, [str(bin_dir)])
    serialized = json.dumps(manifest)

    assert PLANTED_APPLICATION_PASSWORD not in serialized
    assert PLANTED_DB_PASSWORD not in serialized
    assert probe.REDACTED in serialized


# --- Detection ---------------------------------------------------------------


def test_wp_env_playground_runtime_reports_no_wp_cli(tmp_path: Path) -> None:
    """The trap most likely to produce a confidently wrong plan."""
    root = tmp_path / "playground-site"
    root.mkdir()
    (root / ".wp-env.json").write_text(json.dumps({"runtime": "playground"}), encoding="utf-8")
    bin_dir = _install_fake_wp(tmp_path)

    manifest = _run_probe(root, [str(bin_dir)])

    assert manifest["environment"]["wp_env_runtime"] == "playground"
    assert manifest["wp_cli"]["status"] == "UNAVAILABLE"
    assert manifest["wp_cli"]["reason"] == "wp_env_playground_runtime_has_no_cli"
    assert manifest["capabilities"]["can_run_wp_cli"] is False
    codes = {entry["code"] for entry in manifest["blockers"]}
    assert "wp_env_playground_runtime_has_no_cli" in codes


def test_losing_markers_are_recorded_as_signal(tmp_path: Path) -> None:
    root = tmp_path / "ambiguous"
    root.mkdir()
    (root / ".lando.yml").write_text("name: demo\n", encoding="utf-8")
    (root / "wp-config.php").write_text("<?php\n", encoding="utf-8")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    manifest = _run_probe(root, [str(empty_bin)])

    assert manifest["environment"]["marker_file"] == ".lando.yml"
    assert "wp-config.php" in manifest["environment"]["other_markers_present"]


def test_marker_without_a_working_prefix_is_unknown_not_lando(tmp_path: Path) -> None:
    """Ground truth is `<prefix> --info`, not the marker file."""
    root = tmp_path / "stopped"
    root.mkdir()
    (root / ".lando.yml").write_text("name: demo\n", encoding="utf-8")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    manifest = _run_probe(root, [str(empty_bin)])

    assert manifest["environment"]["kind"] == "UNKNOWN"
    assert manifest["environment"]["marker_file"] == ".lando.yml"
    codes = {entry["code"] for entry in manifest["blockers"]}
    assert "marker_matched_but_cli_unreachable" in codes


# --- Statuses ----------------------------------------------------------------


def test_blocked_and_unknown_never_satisfy_a_capability() -> None:
    manifest = probe._blank_manifest([], False, Path("/tmp"))
    for status in ("BLOCKED", "UNKNOWN"):
        manifest["wp_cli"]["status"] = status
        manifest["wordpress"]["status"] = status
        manifest["wordpress"]["is_installed"] = True
        manifest["abilities"]["status"] = status
        manifest["abilities"]["api_present"] = True
        manifest["mcp"]["status"] = status
        manifest["abilities"]["publicly_exposed_count"] = 4
        manifest["verification_tools"] = {
            name: {"status": status} for name in ("phpcs", "phpstan", "plugin_check", "wp_env")
        }

        probe._derive_capabilities(manifest)

        assert all(value is False for value in manifest["capabilities"].values()), status


def test_schema_declares_the_load_bearing_rule() -> None:
    schema = probe.load_schema()

    assert "never satisfy" in schema["description"]
    assert schema["$defs"]["status"]["enum"] == ["AVAILABLE", "UNAVAILABLE", "BLOCKED", "UNKNOWN"]
