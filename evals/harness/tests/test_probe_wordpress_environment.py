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


# --- Safety: the read-only allowlist ------------------------------------------
# The old denylist failed open: thirteen of sixteen destructive commands passed
# it. Every case below that the denylist caught must still refuse, plus the
# thirteen that slipped through, plus a positive control per invocation the
# probe actually issues.

MUST_REFUSE = [
    # The cases the old denylist caught, kept as regression anchors.
    ["wp", "db", "drop"],
    ["wp", "search-replace", "old.test", "new.test"],
    ["wp", "--path=/srv/site", "db", "drop"],
    ["wp", "@production", "db", "drop"],
    ["wp-env", "run", "cli", "wp", "post", "delete", "5"],
    ["wp", "--url=http://x", "db", "drop"],
    ["wp", "eval-file", "x.php"],
    ["wp", "shell"],
    # The thirteen that passed the denylist.
    ["wp", "db", "cli"],
    ["wp", "db", "export"],
    ["wp", "site", "delete", "3"],
    ["wp", "plugin", "uninstall", "hello"],
    ["wp", "option", "update", "siteurl", "http://evil.test"],
    ["wp", "option", "delete", "transient"],
    ["wp", "config", "set", "WP_DEBUG", "true"],
    ["wp", "core", "multisite-convert"],
    ["wp", "user", "session", "destroy", "1"],
    ["wp", "cron", "event", "run", "--all"],
    ["wp", "media", "regenerate", "--yes"],
    ["wp", "rewrite", "structure", "/%postname%/"],
    ["wp-env", "run", "cli", "wp", "db", "export"],
    # Host commands the probe has no business running.
    ["rm", "-rf", "/srv/site"],
    ["composer", "install"],
    ["npx", "--yes", "@wordpress/env", "start"],
    ["phpcs", "--standard=WordPress", "."],
]

PROBE_ISSUED_INVOCATIONS = [
    ["php", "--version"],
    ["node", "--version"],
    ["composer", "--version"],
    ["phpcs", "--version"],
    ["phpcs", "-i"],
    ["/srv/site/vendor/bin/phpcs", "--version"],
    ["/srv/site/vendor/bin/phpstan", "--version"],
    ["phpstan", "--version"],
    ["npx", "--no-install", "@wordpress/env", "--version"],
    ["npx", "--no-install", "@wp-playground/cli", "--version"],
    ["wp", "--info"],
    ["wp", "--path=/srv/site", "--info"],
    ["wp-env", "run", "cli", "wp", "--info"],
    ["ddev", "wp", "--info"],
    ["lando", "wp", "cli", "version"],
    ["wp", "cli", "version"],
    ["wp", "help", "ability"],
    ["wp", "help", "block"],
    ["wp", "help", "doctor"],
    ["wp", "help", "dist-archive"],
    ["wp", "core", "version", "--extra"],
    ["wp", "core", "is-installed"],
    ["wp", "option", "get", "siteurl"],
    ["wp", "option", "get", "home"],
    ["wp", "plugin", "list", "--format=json", "--fields=name,status,version,update"],
    ["wp", "theme", "list", "--format=json", "--fields=name,status,version"],
    ["wp", "ability", "list", "--format=json"],
    ["wp", "plugin", "check", "--help"],
]


@pytest.mark.parametrize("argv", MUST_REFUSE, ids=[" ".join(argv) for argv in MUST_REFUSE])
def test_everything_off_the_allowlist_is_refused(argv: list[str]) -> None:
    assert probe._refusal(argv) is not None


@pytest.mark.parametrize(
    "argv", PROBE_ISSUED_INVOCATIONS, ids=[" ".join(argv) for argv in PROBE_ISSUED_INVOCATIONS]
)
def test_every_probe_issued_invocation_is_allowlisted(argv: list[str]) -> None:
    assert probe._refusal(argv) is None


@pytest.mark.parametrize("argv", [["wp", "db", "drop"], ["wp", "search-replace", "a", "b"]])
def test_runner_refuses_destructive_commands(tmp_path: Path, argv: list[str]) -> None:
    runner = probe.ProbeRunner(tmp_path, allow_eval=True)

    with pytest.raises(probe.CommandRefused):
        runner.run("test", argv)

    assert runner.evidence == [], "a refused command must leave no evidence"


def test_eval_is_refused_unless_allow_eval_is_set(tmp_path: Path) -> None:
    runner = probe.ProbeRunner(tmp_path, allow_eval=False)

    with pytest.raises(probe.CommandRefused):
        runner.run("test", ["wp", "eval", "echo 1;"], eval_exception=True)


def test_eval_stays_gated_behind_both_flags() -> None:
    argv = ["wp", "eval", "echo 1;"]

    assert probe._refusal(argv, allow_eval=True, eval_exception=True) is None
    assert probe._refusal(argv, allow_eval=True, eval_exception=False) is not None
    assert probe._refusal(argv, allow_eval=False, eval_exception=True) is not None


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


# --- Safety: subprocess hardening ---------------------------------------------


def _install_fake_php(tmp_path: Path, payload: bytes) -> Path:
    """Write a fake `php` that emits raw bytes and return its PATH directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "php"
    script.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write({payload!r})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def test_non_utf8_tool_output_does_not_crash_the_probe(tmp_path: Path) -> None:
    """A localized PHP notice in Latin-1 must degrade to U+FFFD, not kill the run.

    UnicodeDecodeError subclasses ValueError, which none of the runner's
    handlers catch; before errors="replace" this violated the never-crash
    contract and left no manifest at all.
    """
    bin_dir = _install_fake_php(tmp_path, b"PHP 8.3.0 caf\xe9\n")
    root = tmp_path / "site"
    root.mkdir()

    manifest = _run_probe(root, [str(bin_dir)])

    assert _schema_errors(manifest) == []
    assert manifest["environment"]["host"]["php"] == "8.3.0"
    excerpts = [entry["stdout_excerpt"] for entry in manifest["evidence"] if entry["claim"] == "environment.host.php"]
    assert any("caf�" in (excerpt or "") for excerpt in excerpts)


def test_subprocess_call_site_is_defused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """stdin closed, decoding never raises, and a POSIX timeout can kill the group."""
    captured: dict = {}
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):  # noqa: ANN002, ANN003
        captured.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(probe.subprocess, "Popen", recording_popen)
    bin_dir = _install_fake_php(tmp_path, b"PHP 8.3.0\n")
    monkeypatch.setenv("PATH", str(bin_dir))
    runner = probe.ProbeRunner(tmp_path, allow_eval=False)

    outcome = runner.run("test", ["php", "--version"])

    assert outcome["ok"] is True
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["errors"] == "replace"
    assert captured["start_new_session"] is (os.name == "posix")


def test_global_budget_exhaustion_is_recorded_instead_of_run(tmp_path: Path) -> None:
    runner = probe.ProbeRunner(tmp_path, allow_eval=False, budget_seconds=0)

    outcome = runner.run("test", ["php", "--version"])

    assert outcome["error"] == "global_budget_exhausted"
    assert outcome["exit_code"] is None
    assert runner.evidence[-1]["stderr_excerpt"] == "global_budget_exhausted"


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


# ---------------------------------------------------------------------------
# Capability grounding: polarity, extraction surface, and invocation prefix.
#
# The gate has to be wrong in neither direction. Missing a real instruction
# ships a broken plan; failing a correct "this is unavailable" note punishes the
# negative-space reporting that check_negative_space rewards, and the prober's
# own SKILL.md requires naming every blocked reason the manifest carries.
# ---------------------------------------------------------------------------

_ABILITY_UNAVAILABLE = {
    "environment": {"invocation_prefix": ["wp"]},
    "wp_cli": {
        "status": "AVAILABLE",
        "commands": {
            "ability": {
                "status": "UNAVAILABLE",
                "reason": "command_documented_but_not_in_stable_phar",
            },
            "plugin": {"status": "AVAILABLE"},
        },
    },
    "verification_tools": {},
}


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(
            "`wp ability list` is UNAVAILABLE with reason "
            "`command_documented_but_not_in_stable_phar`.",
            id="inline-report-of-unavailability",
        ),
        pytest.param("Do not run `wp ability list`.", id="explicit-prohibition"),
        pytest.param(
            "## Blockers\n\n| command | status |\n| --- | --- |\n"
            "| `wp ability list` | UNAVAILABLE |\n",
            id="blockers-table",
        ),
        pytest.param(
            "## Negative Space\n\nThe `wp ability list` surface is absent on 2.12.0.\n",
            id="negative-space-section",
        ),
        pytest.param(
            "## Capability Summary\n\n`wp ability` is not probed on this host.\n",
            id="capability-summary-section",
        ),
    ],
)
def test_naming_an_unavailable_command_to_report_it_is_not_an_instruction(candidate: str) -> None:
    check = output_oracle.check_capability_grounding(candidate, _ABILITY_UNAVAILABLE)

    assert check.passed is True, check.detail


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param("```sh\nwp ability list\n```", id="backtick-fence"),
        pytest.param("~~~sh\nwp ability list\n~~~", id="tilde-fence"),
        pytest.param("Run this:\n\n    wp ability list\n", id="indented-block"),
        pytest.param("```sh\n/usr/local/bin/wp ability list\n```", id="absolute-path"),
        pytest.param("```sh\nWP ability list\n```", id="uppercase"),
        pytest.param("Run `wp ability list` to enumerate abilities.", id="inline-imperative"),
        pytest.param("```sh\n$ wp ability list\n```", id="shell-prompt"),
        pytest.param("```\nwp  ability  list\n```", id="untagged-fence-double-space"),
    ],
)
def test_instructing_an_unavailable_command_fails_on_every_markup_form(candidate: str) -> None:
    check = output_oracle.check_capability_grounding(candidate, _ABILITY_UNAVAILABLE)

    assert check.passed is False, candidate
    assert "command_documented_but_not_in_stable_phar" in check.detail


def test_a_shell_tagged_fence_is_an_instruction_even_inside_a_blockers_section() -> None:
    """A tagged fence is unambiguous, so section exemption must not cover it."""
    candidate = "## Blockers\n\n```sh\nwp ability list\n```\n"

    check = output_oracle.check_capability_grounding(candidate, _ABILITY_UNAVAILABLE)

    assert check.passed is False
    assert "command_documented_but_not_in_stable_phar" in check.detail


def test_bundled_commands_do_not_warn_when_the_cli_is_available() -> None:
    """`wp option get` needs no package, so "not probed" carries no risk."""
    check = output_oracle.check_capability_grounding(
        "```sh\nwp option get siteurl\n```", _ABILITY_UNAVAILABLE
    )

    assert check.passed is True
    assert "not probed" not in check.detail


def test_commands_needing_their_own_package_are_named_as_unprobed() -> None:
    check = output_oracle.check_capability_grounding(
        "```sh\nwp dist-archive .\n```", _ABILITY_UNAVAILABLE
    )

    assert check.passed is True
    assert "wp dist-archive: not probed" in check.detail


_WP_ENV_PREFIX = {
    "environment": {"invocation_prefix": ["wp-env", "run", "cli", "wp"]},
    "wp_cli": {"status": "AVAILABLE", "commands": {"plugin": {"status": "AVAILABLE"}}},
    "verification_tools": {},
}


def test_bare_wp_fails_when_the_environment_needs_a_prefix() -> None:
    """The manifest knows bare `wp` does not reach WP-CLI; the gate must use it."""
    check = output_oracle.check_capability_grounding(
        "```sh\nwp plugin list\n```", _WP_ENV_PREFIX
    )

    assert check.passed is False
    assert "bare_wp_does_not_reach_wp_cli" in check.detail


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param("```sh\nwp-env run cli wp plugin list\n```", id="full-prefix"),
        pytest.param("```sh\nwp --path=/srv/www plugin list\n```", id="path-escape"),
        pytest.param("```sh\nwp @staging plugin list\n```", id="alias-escape"),
    ],
)
def test_a_routed_invocation_satisfies_the_prefix_rule(candidate: str) -> None:
    check = output_oracle.check_capability_grounding(candidate, _WP_ENV_PREFIX)

    assert check.passed is True, check.detail


def test_the_wordpress_standard_is_attributed_to_wpcs_not_phpcs() -> None:
    """PHPCS present with WPCS missing is the ordinary partial-install case."""
    manifest = {
        "environment": {"invocation_prefix": ["wp"]},
        "wp_cli": {"status": "AVAILABLE", "commands": {}},
        "verification_tools": {
            "phpcs": {"status": "AVAILABLE"},
            "wpcs": {"status": "UNAVAILABLE", "reason": "wordpress_standard_not_installed"},
        },
    }

    check = output_oracle.check_capability_grounding(
        "```sh\nvendor/bin/phpcs --standard=WordPress .\n```", manifest
    )

    assert check.passed is False
    assert "wordpress_standard_not_installed" in check.detail
