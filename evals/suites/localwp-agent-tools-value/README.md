# localwp-agent-tools value eval (scaffold, v2)

**Status as of this build pass:** the `tool-value-ab` validator profile
(design §9.2) is now registered in `scripts/validate-eval-suite-integrity.py`
and this suite passes it cleanly (`python3 scripts/validate-eval-suite-integrity.py
--strict-suites localwp-agent-tools-value`). All four built fixtures
(1/11/12/13) have real, executable `seed.sh` / `oracle.py` / `reference-fix*.sh`
/ `cheats/*.sh`, verified end-to-end (seed→fail, every reference-fix→pass,
every cheat→fail) by `evals/harness/tests/test_tool_value_oracle_fixture{1,11,12,13}.py`
against a fake WordPress-behavior backend — **not** a live Lane H stack, so
their `metadata.yaml` `status` deliberately stays `spec_only`, not `built`:
prompt hashes, golden digests, and the independent lift table are still
`PENDING` by design (out of scope for this pass; see "Not done here" below).
This repository is **still uncommitted** pending review; nothing here has
been executed against an agent, and no Lane H stack has run these fixtures
for real.

Runner (`evals/harness/run_localwp_tool_value_eval.py`), the oracle library
(`evals/harness/tool_value_oracle_lib.py`, `tool_value_live_backend.py`),
the parity check's deterministic half (`evals/harness/tool_value_parity.py`),
the `stack/` Dockerfile (built and smoke-tested locally: nginx + php8.3-fpm +
MariaDB start and interoperate), and `stack/strip_tool_references.py` are
all real and unit-tested. Every place that needs a live Lane H stack, the
fork's headless MCP server, or an actual agent invocation is marked
`# SEAM(stack):`, `# SEAM(headless-entrypoint):`, or `# SEAM(agent-invocation):`
in the source — grep for those to find every remaining seam.

**2026-09-03 update — fixture 1 proven end to end against the real Docker
stack (not just the fake backend).** `stack/Dockerfile`'s image
(`localwp-tool-value-stack:dev`) was run for real: nginx + php8.3-fpm +
MariaDB serving a real WordPress 6.8.2 install at the design's Local-shaped
paths, the fork's headless MCP server (branch `eval/headless-harness`,
built inside the same container) standing up the real 13-tool MCP surface,
and `fatal-undefined-function-page-scoped`'s `oracle.py` run as a real
subprocess (its documented env-var contract, `LiveSiteBackend`,
`wp_cli_command` a `docker exec`-wrapped `php ... wp-cli.phar`) — no fake
backend anywhere in this pass. Results, all against the live container:

| Step | Outcome |
|---|---|
| Oracle on the seeded (unfixed) site | `fail` (functionality + dynamic-probe checks correctly catch it even though the HTTP status alone does not — see finding below) |
| Oracle after `reference-fix.sh` | `pass`, including the dynamic nonce-event probe |
| Oracle after `cheats/deactivate.sh` (a real `wp plugin deactivate` against the live DB) | `fail` |
| **A real `claude -p` run** (model `sonnet`, real headless MCP server, real `.mcp.json`) | Found the fatal via `mcp__local-wp__read_error_log` + `get_site_info`, diagnosed the `is_admin()` guard, applied the identical fix `reference-fix.sh` makes (byte-identical to golden), verified its own fix. `end_turn`, $0.40, ~38.5s API time |
| Oracle on the real agent's resulting site state | `pass` |

Four real bugs were found and fixed doing this (all documented in-line where
fixed): `wp-config.php` and `.mcp.json`/`CLAUDE.md` were missing from
`tool_value_oracle_lib.DEFAULT_CHANGED_FILE_EXCLUSIONS`, so a legitimate
debug-toggle round trip or arm T's own setup file would have wrongly failed
the no-collateral check; and a real cheat-validity-gate test
(`test_cheat_makes_the_oracle_fail[mask-with-debug-display-off.sh]`) needed
`exclude=()` once wp-config.php stopped being hashed by default. A genuine,
previously-undocumented finding, not a bug: on this stack, a fatal deep
enough into page rendering (past `output_buffering`'s 4096-byte threshold)
gets HTTP 200 with silently truncated output, not the "critical error"
message `class WP_Fatal_Error_Handler::handle()` only prints when
`is_admin() || !headers_sent()` — the design's own §2.4 derivation predicted
the message would still appear, appended; it does not, for a non-admin
request once headers are sent. The oracle still correctly fails the seeded
state (via the functionality and dynamic-probe checks), but `symptom_resolved`'s
`expect_status: 200` check alone cannot distinguish faulted from fixed for
this exact fixture shape — worth a design revisit before fixtures 2–10 are
built the same way. Full architecture decision, the wiring recipe, and every
seam still marked is documented in `evals/harness/tool_value_live_backend.py`'s
module docstring and `build_docker_lane_h_backend()`.

**Still not done here (out of scope for this pass):** prompt hash freezing,
`prereg.md`, the independent expected-lift table, golden WP tarballs/DB
dumps (the golden snapshot here is a plain directory + wp-config.php, not
yet `public.tar.zst` + `db.sql`), the T–C0/C1/C1-ctx arm comparison (only
arm T was run — this pass proves the pipeline works, not the tool's value),
fixtures 2–10, and the Lane L (real Local) half of parity. These need a
real Local install and/or an independent author, per the design's own
gating.

The one computed artifact from the original design pass is
`statistical/simulate_two_stage_alpha.py`, a Monte-Carlo of the pre-registered
two-stage rule under the null (design §7.4); it measures the rule, not the tool.

What this suite will measure: oracle-gated task success (pass within 60 turns)
of Claude Code on seeded-fault WordPress sites, with the `localwp-agent-tools`
MCP add-on (arm T) versus a capability-matched control that has WP-CLI but no
named tools (arm C1, **primary contrast — the tool-quality claim**) and versus
a naive control (arm C0, **co-primary — the provisioning claim**). The headline
is two numbers, always both, in a fixed order (design §7.5). No LLM judge in
confirmatory analysis.

The word "Local" is unlocked only by a deterministic tool-output equivalence
check against a real Local install (design §2.5), enforced by the scorecard
generator and the evidence-log validator (design §9.3), not by prose.

Layout the design calls for (starred files exist now):

```
eval.yaml                         *  profile tool-value-ab; passes the validator
README.md                         *
prereg.md                            BLOCKED: independent lift table + a real Local install
statistical-design.md
statistical/simulate_two_stage_alpha.py  *  realized alpha of the two-stage rule (design §7.4)
arms/{T,C0,C1,C1-ctx}.yaml        *  mcp on/off, context variant, PATH shim on/off
stack/                            *  Dockerfile (built + smoke-tested), conf/{nginx.conf,php.ini,php-fpm-pool.conf,my.cnf},
                                      entrypoint.sh, site-layout.sh, build.sh, strip_tool_references.py
parity/                              parity-report.json (schema only; see evals/harness/tool_value_parity.py)
fixtures/<id>/
  metadata.yaml                   *  status: spec_only for all four (see "Status" above)
  prompt.md                       *  identical bytes for every arm
  oracle.spec.yaml                *  contract for oracle.py
  oracle.py                       *  all four; real, tested against a fake backend
  seed.sh reference-fix*.sh       *  all four; real, executable
  trigger.sh                      *  all four; real logic, SEAM(stack) for the live HTTP round-trip
  cheats/*.sh                     *  all four; real, executable, oracle-verified to fail
  golden/wp-config.php            *  fixture 1/11/12/13; the constants block only, not a full bootable config
  plugins/ or dropin/             *  fixture 1/13 (plugins/), fixture 12 (dropin/); real small GPL PHP source
```

evals/harness/ additions this pass: `tool_value_oracle_lib.py` (shared
deterministic logic — wp-config parsing/diffing, changed-file hashing,
the `SiteBackend` protocol), `tool_value_live_backend.py` (the real,
SEAM-marked backend), `tool_value_parity.py` (design §2.5's deterministic
half), `run_localwp_tool_value_eval.py` (the runner skeleton), and
`tests/test_tool_value_*.py` / `tests/test_run_localwp_tool_value_eval.py`
(113 tests, all passing, no live stack or agent required).

Fixtures present (built — real scripts, `status: spec_only` metadata):

| # | id | role |
|---|---|---|
| 1 | `fatal-undefined-function-page-scoped` | PoC / flagship; likely to saturate, which is a pre-registered result |
| 11 | `wpconfig-in-parent-dir-tools-misreport` | tool plausibly loses: config tools report a phantom missing file |
| 12 | `dead-object-cache-dropin-tool-hangs` | tool plausibly loses: `site_health_check` names the wrong subsystem |
| 13 | `fatal-in-error-log-fresh-debug-log-misleads` | tool plausibly loses: `read_error_log` picks the newer, wrong file |

Fixtures 2–10 are specified in the design document only.

Open questions that need a real Local install are in design §13; do not
resolve them by guessing.
