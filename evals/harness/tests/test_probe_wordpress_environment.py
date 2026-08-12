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
elif path == "config get MULTISITE":
    sys.stderr.write("Error: The constant or variable 'MULTISITE' is not defined.\\n")
    raise SystemExit(1)
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

DEFAULT_BANNER = "OS:\tDarwin\nPHP version:\t8.3.7\nWP-CLI version:\t2.12.0\n"


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


def _run_probe(
    root: Path,
    path_dirs: list[str],
    *,
    allow_eval: bool = False,
    allow_remote: bool = False,
    argv: list[str] | None = None,
) -> dict:
    env_path = os.pathsep.join(path_dirs)
    previous = os.environ.get("PATH")
    os.environ["PATH"] = env_path
    try:
        return probe.probe(
            root,
            allow_eval=allow_eval,
            allow_remote=allow_remote,
            argv=argv or ["probe", "--path", str(root)],
        )
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
    assert "assumed_3x" not in manifest["wp_cli"], "dead field: written false, never set true"
    ability = manifest["wp_cli"]["commands"]["ability"]
    assert ability["status"] == "UNAVAILABLE"
    assert ability["reason"] == "command_documented_but_not_in_stable_phar"
    assert manifest["wp_cli"]["commands"]["block"]["reason"] == (
        "command_documented_but_not_in_stable_phar"
    )
    assert manifest["wp_cli"]["commands"]["plugin"]["status"] == "AVAILABLE"
    assert manifest["wordpress"]["active_plugins"] == [
        {"name": "plugin-check", "version": "2.0.0", "activation_state": "active"}
    ], "WP-CLI's free-form status maps to activation_state, distinct from the status enum"
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


def test_capability_grounding_still_sees_fenced_commands() -> None:
    """Guard the argument this check receives inside ``validate_output``.

    Every other check reads the ``_strip_non_authoritative_markdown`` text so a
    quoted example cannot satisfy a contract. This check is the exception: it
    inspects code occurrences, and stripping blanks fenced blocks, so routing it
    through the stripped text turns an instructed-but-unavailable command into a
    silent pass. It must keep reading the raw output.
    """
    text = (FIXTURES.parent / "a_short_valid_heading.md").read_text(encoding="utf-8")
    text += "\nRun the import:\n\n```bash\nwp plugin install foo --activate\n```\n"
    manifest = {
        "wp_cli": {"status": "UNAVAILABLE", "reason": "wp_cli_absent", "commands": {}},
    }

    stripped = output_oracle._strip_non_authoritative_markdown(text)
    assert "wp plugin install" in text
    assert "wp plugin install" not in stripped

    result = output_oracle.validate_output(
        "wordpress-planner", text, capability_manifest=manifest
    )
    check = next(c for c in result["checks"] if c["id"] == "capability_grounding")

    assert check["passed"] is False
    assert "wp_cli_absent" in check["detail"]


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


def _live_wp_env_root(opt_in: str) -> Path:
    """Fail-closed opt-in shared by the live wp-env tests.

    WP_META_SKILLS_WP_ENV_PATH points at the wp-env project root. It defaults
    to the current working directory, which under pytest is the repo root -
    not a wp-env project - so the default is only useful when the suite is
    invoked from a project directory. Once opted in the tests fail closed: a
    missing tool is a failure, not a silent skip. Without the opt-in they
    report exactly how to request it.
    """
    required = os.environ.get(REQUIRE_TOOL_ENV, "")
    if opt_in not in required.split(","):
        pytest.skip(f"set {REQUIRE_TOOL_ENV}={opt_in} to run the live wp-env probe")
    assert shutil.which("wp-env") or shutil.which("npx"), (
        f"{REQUIRE_TOOL_ENV}={opt_in} was requested but neither wp-env nor npx is on PATH"
    )
    return Path(os.environ.get(WP_ENV_PATH_ENV) or Path.cwd()).resolve()


@pytest.mark.real_wp_env
def test_scenario_c_live_wp_env_probe_invariants() -> None:
    """Opt in with WP_META_SKILLS_REQUIRE_TOOL=wp-env.

    CI's live-wp-env-probe job provisions a scratch wp-env project and runs
    this against it, so the golden fixture stops being decoration. Only
    environment-independent invariants belong here: exact golden equality
    bakes in the recording machine's host toolchain and is the separate
    opt-in below.
    """
    root = _live_wp_env_root("wp-env")

    manifest = probe.probe(root, allow_eval=False, argv=["probe", "--path", "."])

    assert _schema_errors(manifest) == []
    assert probe.evidence_gaps(manifest) == []
    assert manifest["environment"]["kind"] == "wp-env"
    assert manifest["environment"]["wp_env_runtime"] == "docker"
    assert manifest["wp_cli"]["status"] == "AVAILABLE"
    assert manifest["capabilities"]["can_run_wp_cli"] is True
    assert manifest["capabilities"]["can_run_plugin_check"] is True
    assert manifest["wordpress"]["is_installed"] is True
    assert manifest["wordpress"]["is_multisite"] is False
    php_rows = [
        entry for entry in manifest["evidence"] if entry["claim"] == "wordpress.php_version"
    ]
    assert php_rows, "php_version must be evidence-backed"
    assert manifest["wordpress"]["php_version"] in php_rows[0]["stdout_excerpt"], (
        "the reported PHP is the container's labeled wp --info answer"
    )
    assert any(entry["claim"] == "wp_cli.is_stable_release" for entry in manifest["evidence"])
    info_row = next(entry for entry in manifest["evidence"] if entry["claim"] == "wp_cli")
    assert "OS:\tLinux [REDACTED]" in info_row["stdout_excerpt"], (
        "kernel build strings are host-identifying and must not reach excerpts"
    )
    codes = {entry["code"] for entry in manifest["blockers"]}
    assert "manifest_self_check_failed" not in codes
    assert "manifest_schema_invalid" not in codes


@pytest.mark.real_wp_env
def test_scenario_c_live_wp_env_matches_the_golden_manifest() -> None:
    """Opt in with WP_META_SKILLS_REQUIRE_TOOL=wp-env-golden.

    Byte-equality with the committed golden bakes in the recording machine's
    host toolchain (host php/node/composer, the project's vendored
    phpcs/phpstan), so this stronger check is for the recording machine;
    CI runs the invariants test above instead.
    """
    root = _live_wp_env_root("wp-env-golden")
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
    assert "facts_from_wp_cli_read_probes" in without["wordpress"]["notes"]
    assert "facts_from_wp_eval" not in without["wordpress"]["notes"]
    assert not any(
        "eval" in entry["argv"] for entry in without["evidence"]
    ), "eval must not run when --allow-eval is off"
    assert without["wordpress"]["php_version"] == "8.3.7", (
        "without eval, PHP comes from the wp --info label — the container's "
        "interpreter — never from host php --version"
    )
    assert without["wordpress"]["is_multisite"] is False, (
        "`wp config get MULTISITE` exiting 1 with 'not defined' is a probed single-site answer"
    )

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


@pytest.mark.parametrize(
    "sample,gone,kept",
    [
        pytest.param(
            "siteurl is http://admin:hunter2@example.test/wp",
            "admin:hunter2",
            "http://[REDACTED]@example.test/wp",
            id="http-basic-auth",
        ),
        pytest.param(
            "dsn mysql://wp_user:wp_pass@db:3306/wp",
            "wp_user:wp_pass",
            "mysql://[REDACTED]@db:3306/wp",
            id="mysql-dsn",
        ),
        pytest.param(
            "ERROR 1045: mysql -u root -phunter2 failed",
            "-phunter2",
            "[REDACTED]",
            id="mysql-short-flag",
        ),
        pytest.param(
            "mariadb --user=root --password=hunter2",
            "hunter2",
            "--password=[REDACTED]",
            id="password-eq-flag",
        ),
        pytest.param(
            "| DB_PASSWORD | hunter2 | constant |",
            "hunter2",
            "DB_PASSWORD",
            id="wp-config-list-table-row",
        ),
        pytest.param(
            "path C:\\Users\\someone\\Local Sites\\demo",
            "someone",
            "path ~\\Local Sites\\demo",
            id="windows-home-path",
        ),
        pytest.param(
            "OS:\tLinux 7.0.11-orbstack-00360-gc9bc4d96ac70 #1 SMP aarch64",
            "orbstack",
            "OS:\tLinux [REDACTED]",
            id="kernel-build-string",
        ),
    ],
)
def test_redaction_covers_urls_cli_flags_tables_and_hosts(
    sample: str, gone: str, kept: str
) -> None:
    scrubbed = probe._redact(sample)

    assert gone not in scrubbed
    assert kept in scrubbed


def test_application_password_redaction_requires_a_cue_or_a_bare_line() -> None:
    """Six four-letter words in ordinary prose must survive; the excerpt is
    what a reviewer diagnoses a failure from."""
    prose = "the unit test data here goes fine"
    assert probe._redact(prose) == prose

    cued = f"application password {PLANTED_APPLICATION_PASSWORD} here"
    assert PLANTED_APPLICATION_PASSWORD not in probe._redact(cued)

    porcelain = PLANTED_APPLICATION_PASSWORD
    assert probe._redact(porcelain) == probe.REDACTED


def test_short_p_flag_survives_on_non_mysql_lines() -> None:
    line = "ssh -p2222 deploy-host"
    assert probe._redact(line) == line


def test_stdout_of_a_secret_naming_argv_is_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`wp config get DB_PASSWORD` output is the bare value: no key on the
    line to anchor on, so the argv guard withholds the whole excerpt."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "wp"
    script.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write('hunter2\\n')\n", encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(probe, "_refusal", lambda *args, **kwargs: None)
    runner = probe.ProbeRunner(tmp_path, allow_eval=False)

    outcome = runner.run("wordpress.db_password", ["wp", "config", "get", "DB_PASSWORD"])

    assert outcome["stdout"].strip() == "hunter2", "raw stdout stays usable internally"
    assert runner.evidence[-1]["stdout_excerpt"] == probe.REDACTED


def test_manifest_argv_fields_are_redacted(tmp_path: Path) -> None:
    """probe_argv, invocation_prefix, and tool invocations must not leak the
    username; normalize_manifest scrubs them for golden comparison only, so
    the emitted manifest has to be clean on its own."""
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(tmp_path)

    manifest = _run_probe(root, [str(bin_dir)], argv=["probe", "--path", "/Users/someone/site"])

    assert manifest["probe_argv"] == ["probe", "--path", "~/site"]
    assert probe._redact_argv(["wp", "--path=/Users/someone/site"]) == ["wp", "--path=~/site"]
    assert probe._redact_argv(["/Users/someone/site/vendor/bin/phpcs", "--version"]) == [
        "~/site/vendor/bin/phpcs",
        "--version",
    ]


# --- The prober's own output contract ------------------------------------------

PROBER_SAMPLE_REPORT = """## Detected Environment

wp-env with the docker runtime, marker `.wp-env.json`, validated by
`wp-env run cli wp --info`. The probe oracle is
`evals/harness/probe_wordpress_environment.py`.

## Capability Summary

can_run_wp_cli true (`wp cli version` answered WP-CLI 2.12.0);
can_run_plugin_check true via `wp plugin check`; can_run_static_analysis true
(phpcs and phpstan both answered `--version`).

## Blockers

mcp_adapter_absent (MAJOR): no MCP adapter plugin observed, so MCP
reachability is outside scope of this run and stays unknown.

## Evidence

`wp plugin list --format=json` inventoried plugins; `wp core is-installed`
exited 0. Every fact traces to an evidence entry by claim path.

## Downstream Handoff

Pass `--capability-manifest capability-manifest.json` to
`validate_wordpress_skill_output.py` when validating wordpress-planner output.
"""


def test_prober_contract_is_registered() -> None:
    """The one skill without a contract oracle is where the last defect
    reached review; the prober's own output now has one."""
    assert "wordpress-environment-probe" in output_oracle.CONTRACT_CHOICES
    assert output_oracle.CONTRACTS["wordpress-environment-probe"]["role"] == "prober"


def test_prober_output_contract_passes_a_conforming_report() -> None:
    result = output_oracle.validate_output("wordpress-environment-probe", PROBER_SAMPLE_REPORT)

    assert result["role"] == "prober"
    assert result["pass"] is True, result["checks"]


def test_prober_output_contract_fails_a_missing_heading() -> None:
    truncated = PROBER_SAMPLE_REPORT.replace("## Downstream Handoff", "## Handoff")

    result = output_oracle.validate_output("wordpress-environment-probe", truncated)

    assert result["pass"] is False
    failed = {check["id"] for check in result["checks"] if not check["passed"]}
    assert "required_output_headings" in failed


# --- Version truth: probed, never asserted from constants ---------------------


def test_is_stable_release_is_probed_from_the_version_string(tmp_path: Path) -> None:
    """WP-CLI 2.13.0 is not unstable just because a frozen constant said 2.12.0."""
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(
        tmp_path, cli_version="2.13.0", banner="OS:\tDarwin\nWP-CLI version:\t2.13.0\n"
    )

    manifest = _run_probe(root, [str(bin_dir)])

    assert manifest["wp_cli"]["version"] == "2.13.0"
    assert manifest["wp_cli"]["is_stable_release"] is True


def test_a_prerelease_suffix_reports_not_stable(tmp_path: Path) -> None:
    root = _project(tmp_path)
    bin_dir = _install_fake_wp(
        tmp_path,
        cli_version="2.13.0-alpha-6d4736d",
        banner="OS:\tDarwin\nWP-CLI version:\t2.13.0-alpha-6d4736d\n",
    )

    manifest = _run_probe(root, [str(bin_dir)])

    assert manifest["wp_cli"]["version"] == "2.13.0"
    assert manifest["wp_cli"]["is_stable_release"] is False


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.0-beta.2", True),
        ("0.5.0", True),
        ("1.2.0", False),
        (None, None),
    ],
)
def test_mcp_adapter_prerelease_comes_from_the_version_string(
    tmp_path: Path, version: str | None, expected: bool | None
) -> None:
    """parse_version discards suffixes, so 1.0.0-beta.2 must not report stable;
    and a missing version is no data, never prerelease=false."""
    manifest = probe._blank_manifest([], False, tmp_path)
    manifest["wp_cli"]["status"] = "AVAILABLE"
    manifest["wordpress"]["status"] = "AVAILABLE"
    manifest["wordpress"]["active_plugins"] = [
        {"name": "mcp-adapter", "version": version, "activation_state": "active"}
    ]
    runner = probe.ProbeRunner(tmp_path, allow_eval=False)

    probe._probe_mcp(runner, manifest)

    assert manifest["mcp"]["adapter"]["present"] is True
    assert manifest["mcp"]["adapter"]["prerelease"] is expected


# --- Safety: subprocess hardening ---------------------------------------------


def _install_fake_tool(tmp_path: Path, name: str, payload: bytes) -> Path:
    """Write a fake tool that emits raw bytes and return its PATH directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write({payload!r})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _install_fake_php(tmp_path: Path, payload: bytes) -> Path:
    return _install_fake_tool(tmp_path, "php", payload)


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


def test_wp_env_override_runtime_wins_over_base(tmp_path: Path) -> None:
    """Override precedence was inverted: docker-over-playground yielded
    playground and manufactured a false CRITICAL blocker."""
    root = tmp_path / "site"
    root.mkdir()
    (root / ".wp-env.json").write_text(json.dumps({"runtime": "playground"}), encoding="utf-8")
    (root / ".wp-env.override.json").write_text(
        json.dumps({"runtime": "docker"}), encoding="utf-8"
    )

    assert probe._wp_env_runtime(root) == "docker"


def test_wp_env_override_playground_still_wins(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / ".wp-env.json").write_text(json.dumps({"runtime": "docker"}), encoding="utf-8")
    (root / ".wp-env.override.json").write_text(
        json.dumps({"runtime": "playground"}), encoding="utf-8"
    )

    assert probe._wp_env_runtime(root) == "playground"


def test_wp_env_override_without_runtime_falls_through_to_base(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / ".wp-env.json").write_text(json.dumps({"runtime": "playground"}), encoding="utf-8")
    (root / ".wp-env.override.json").write_text(json.dumps({"port": 8901}), encoding="utf-8")

    assert probe._wp_env_runtime(root) == "playground"


def test_losing_wp_env_playground_config_does_not_block_a_winning_marker(tmp_path: Path) -> None:
    """A ddev environment with a stray playground wp-env config must record
    the runtime without manufacturing the playground CRITICAL blocker."""
    root = tmp_path / "site"
    root.mkdir()
    (root / ".ddev").mkdir()
    (root / ".ddev" / "config.yaml").write_text("name: demo\n", encoding="utf-8")
    (root / ".wp-env.json").write_text(json.dumps({"runtime": "playground"}), encoding="utf-8")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    manifest = _run_probe(root, [str(empty_bin)])

    assert manifest["environment"]["marker_file"] == ".ddev/config.yaml"
    assert manifest["environment"]["wp_env_runtime"] == "playground"
    assert manifest["wp_cli"]["reason"] != "wp_env_playground_runtime_has_no_cli"
    codes = {entry["code"] for entry in manifest["blockers"]}
    assert "wp_env_playground_runtime_has_no_cli" not in codes


def test_wp_env_tool_carries_the_playground_reason_when_not_winning(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / ".ddev").mkdir()
    (root / ".ddev" / "config.yaml").write_text("name: demo\n", encoding="utf-8")
    (root / ".wp-env.json").write_text(json.dumps({"runtime": "playground"}), encoding="utf-8")
    bin_dir = _install_fake_tool(tmp_path, "npx", b"11.12.0\n")

    manifest = _run_probe(root, [str(bin_dir)])

    wp_env_tool = manifest["verification_tools"]["wp_env"]
    assert wp_env_tool["status"] == "AVAILABLE"
    assert wp_env_tool["runtime"] == "playground"
    assert "wp_env_playground_runtime_has_no_cli" in wp_env_tool["notes"]


def test_studio_marker_is_labeled_with_the_file_that_matched(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / ".studio").mkdir()
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    manifest = _run_probe(root, [str(empty_bin)])

    assert manifest["environment"]["marker_file"] == ".studio"
    rows = [
        entry
        for entry in manifest["evidence"]
        if entry["argv"][:2] == ["<filesystem>", "exists"] and entry["argv"][2] == ".studio"
    ]
    assert rows and rows[0]["stdout_excerpt"] == "present"


def test_remote_alias_is_not_probed_without_allow_remote(tmp_path: Path) -> None:
    """A checked-in ssh alias must not make a fresh clone dial out."""
    root = tmp_path / "site"
    root.mkdir()
    (root / ".wp-cli.yml").write_text("@prod:\n  ssh: user@example.test\n", encoding="utf-8")
    bin_dir = _install_fake_wp(tmp_path)

    manifest = _run_probe(root, [str(bin_dir)])

    assert manifest["wp_cli"]["status"] == "BLOCKED"
    assert manifest["wp_cli"]["reason"] == "remote_probing_requires_allow_remote"
    assert manifest["environment"]["remote_alias"] == "@prod"
    assert manifest["capabilities"]["can_run_wp_cli"] is False
    codes = {entry["code"] for entry in manifest["blockers"]}
    assert "remote_probing_requires_allow_remote" in codes
    assert not any(
        "@prod" in entry["argv"] for entry in manifest["evidence"]
    ), "no command may carry the alias without the opt-in"


def test_allow_remote_opts_into_alias_probing(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / ".wp-cli.yml").write_text("@prod:\n  ssh: user@example.test\n", encoding="utf-8")
    bin_dir = _install_fake_wp(tmp_path)

    manifest = _run_probe(root, [str(bin_dir)], allow_remote=True)

    assert manifest["environment"]["kind"] == "remote-alias"
    assert manifest["wp_cli"]["status"] == "AVAILABLE"


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


def test_a_section_root_claim_does_not_bless_deep_fact_leaves(tmp_path: Path) -> None:
    """One `claim: "wp_cli"` entry used to cover every leaf beneath it,
    including fields that probe nothing."""
    manifest = probe._blank_manifest([], False, tmp_path)
    manifest["wp_cli"]["status"] = "AVAILABLE"
    manifest["wp_cli"]["version"] = "2.12.0"
    manifest["wp_cli"]["is_stable_release"] = True
    manifest["evidence"] = [
        {"claim": "wp_cli", "argv": ["wp", "--info"], "exit_code": 0},
        {"claim": "wp_cli.version", "argv": ["wp", "cli", "version"], "exit_code": 0},
    ]

    assert "wp_cli.is_stable_release" in probe.evidence_gaps(manifest)

    manifest["evidence"].append(
        {"claim": "wp_cli.is_stable_release", "argv": ["wp", "cli", "version"], "exit_code": 0}
    )
    assert "wp_cli.is_stable_release" not in probe.evidence_gaps(manifest)


@pytest.mark.parametrize(
    "stdout,expected",
    [
        (
            "The installed coding standards are MySource, PEAR, Zend and WordPress\n",
            ["MySource", "PEAR", "Zend", "WordPress"],
        ),
        ("The only installed coding standard is PEAR\n", ["PEAR"]),
        (
            "The installed coding standards are SquareBracket and WordPress\n",
            ["SquareBracket", "WordPress"],
        ),
        ("no standards here\n", []),
    ],
)
def test_phpcs_standards_parsing(stdout: str, expected: list[str]) -> None:
    """split(\"are\") broke on the single-standard phrasing and on names
    containing \"are\"."""
    assert probe._phpcs_standards(stdout) == expected


def test_is_installed_distinguishes_no_from_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path)
    failing = ("help ability", "help block", "help doctor", "help profile", "core is-installed")
    bin_dir = _install_fake_wp(tmp_path, failing=failing)

    manifest = _run_probe(root, [str(bin_dir)])
    assert manifest["wordpress"]["is_installed"] is False, "exit 1 is a probed no"

    real_execute = probe.ProbeRunner._execute

    def timing_out(self: probe.ProbeRunner, argv: list[str], timeout: float) -> dict:
        if argv and argv[-1] == "is-installed":
            return {"error": "timeout"}
        return real_execute(self, argv, timeout)

    monkeypatch.setattr(probe.ProbeRunner, "_execute", timing_out)
    bin_dir = _install_fake_wp(tmp_path)
    manifest = _run_probe(root, [str(bin_dir)])
    assert manifest["wordpress"]["is_installed"] is None, "a timeout is no answer, not a no"


def test_print_and_out_are_both_honoured(tmp_path: Path) -> None:
    """--print used to silently discard --out: exit 0, nothing printed,
    nothing written."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    root = tmp_path / "nothing"
    root.mkdir()
    out = tmp_path / "manifest.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(probe.__file__)),
            "--path",
            str(root),
            "--out",
            str(out),
            "--print",
        ],
        env={"PATH": str(empty_bin), "PYTHONPATH": str(Path(probe.__file__).parent)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    printed = json.loads(completed.stdout)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert printed == written


def test_schema_declares_the_load_bearing_rule() -> None:
    schema = probe.load_schema()

    assert "never satisfy" in schema["description"]
    assert schema["$defs"]["status"]["enum"] == ["AVAILABLE", "UNAVAILABLE", "BLOCKED", "UNKNOWN"]
    assert isinstance(schema.get("allOf"), list) and len(schema["allOf"]) >= 4, (
        "the rule is machine-checked via if/then, not description-only"
    )


def test_schema_machine_checks_the_load_bearing_rule(tmp_path: Path) -> None:
    """capabilities.can_run_wp_cli=true with wp_cli.status UNKNOWN must fail
    validation, not just violate a description nobody executes."""
    manifest = probe._blank_manifest([], False, tmp_path)
    assert _schema_errors(manifest) == []

    manifest["capabilities"]["can_run_wp_cli"] = True

    errors = _schema_errors(manifest)
    assert any("wp_cli" in error and "AVAILABLE" in error for error in errors), errors


@pytest.mark.parametrize(
    "section,key",
    [
        ("wp_cli_commands", "ability list"),
        ("verification_tools", "plugin check"),
    ],
)
def test_key_drift_fails_schema_validation(tmp_path: Path, section: str, key: str) -> None:
    """A drifted key like 'ability list' used to validate cleanly, silently
    converting every real gate failure into a warning."""
    manifest = probe._blank_manifest([], False, tmp_path)
    if section == "wp_cli_commands":
        manifest["wp_cli"]["commands"][key] = {"status": "AVAILABLE"}
    else:
        manifest["verification_tools"][key] = {"status": "AVAILABLE"}

    assert any("propertyName" in error for error in _schema_errors(manifest))


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
