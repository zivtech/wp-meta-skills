# localwp-agent-tools Value Eval — Design (v2)

Status: design only. Nothing in this document has been run against an agent.
Every number below is a planning estimate, a pre-registered threshold, or a
simulation under the null — never a result. The one computed quantity (§7.4,
realized α of the two-stage rule) is a Monte-Carlo calculation with its seed
and script recorded; it measures the *rule*, not the tool.

Date: 2026-09-02 (v1), revised same day to v2 after adversarial review
(`localwp-agent-tools-eval-design-2026-09-02-review.md`, verdict REVISE).
Subject under test: `localwp-agent-tools`, internal fork pinned at
commit `78c87ea`.
Harness home: this repository (`wp-meta-skills`).

## v2 changes

Each row maps to a numbered finding in the review. "Deviation" means the fix
was applied in a form that differs from the review's wording; the reason is in
the referenced section.

| Finding | Change | Where |
|---|---|---|
| 1 (critical) | **T–C1 is the primary contrast** for the tool-quality claim; **T–C0 is a co-primary labeled "provisioning"**; α split 0.025/0.025 (Bonferroni); two-number headline template frozen; the "lead with whichever is fair" language is deleted | §0, §4.1, §7.1, §7.5 |
| 2 (critical) | Statistical Lane-H↔Lane-L parity gate (R=5, 0.30 threshold) **replaced** by a deterministic per-tool output-equivalence check through the real MCP endpoint, R=1, CI-gateable on the Lane H side; Lane L agent runs demoted to descriptive; 0.30 threshold dropped | §2.3, §2.5 |
| 3 | Oracle no-collateral log check uses a **post-agent offset**; the oracle issues its own request after the agent exits | §4.2 step 7, §11.5 |
| 4 | Functionality check asserts **formatted-date content**, not marker presence; **post-hoc dynamic nonce-event probe** defeats hard-coded markup; cheats `stub-in-plugin-dir.sh` and `hardcode-template.sh` added | §11.5, §11.6 |
| 5 | Golden `wp-config.php` **defines `WP_DEBUG`, `WP_DEBUG_LOG`, `SCRIPT_DEBUG` explicitly**; `wp-config.php` compared **semantically** (parsed constant map + non-define residue), not byte-wise; `wp-config.php.bak` and `wp-content/debug.log` excluded from the changed-file set as diagnostic residue | §2.4, §11.2, §11.5 |
| 6 | C1 shim **mirrors `src/tools/wpcli.ts` `runWpCli()`**: both `-d …default_socket` directives, `--path=<wpPath>` appended when absent, `PHPRC`, `MYSQL_UNIX_PORT`, mysql bin dir on PATH | §4.1 |
| 7 | *Deviation.* The M3 ablation arm is **`C1-ctx` = C1 + tool-stripped context**, replacing `T-ctx` (C0 + full context). With T–C1 primary, an ablation on C0's base cannot attribute the T–C1 gap. The stripped context is a deterministic transform of the fork's generated text. `mcp_invoked` is retired as the M3 signal and kept only as a descriptive count | §4.1, §6 |
| 8 | C0 pinned on three axes: phar **on disk at the Local-shaped bundled path, not on PATH**; network egress **off** for every arm, with `WP_HTTP_BLOCK_EXTERNAL` in golden; mysql client on disk at the Local-shaped path, not on PATH; MariaDB on socket + Local-shaped TCP port. Direction of bias stated per pin | §4.1 |
| 9 | Primary stated as **"pass within 60 turns"**; wall clock non-binding (45 min safety cap → `error`, not `timeout`, reported separately); **pass@turn curves** defined and reported | §3, §4.2, §6, §7.3 |
| 10 | Haystack size **pre-registered** (7 plugins); pilot may make **arm-symmetric** changes only, on fixture 1 only; fixtures 2–13 frozen by hash before the pilot | §11.8 |
| 11 | Exact two-stage rule stated; **realized α simulated** under H0 (script committed alongside the suite, seed recorded). Result: 0.019 (p-criterion), 0.003 (full success criterion) at nominal 0.025 — *below* nominal, not the ~0.06–0.08 the review estimated; the discrepancy is explained | §7.4 |
| 12 | "No 'Local' without parity artifacts" is a **tooling requirement**: the scorecard generator refuses to emit the word in claim fields without `parity/parity-report.json` at `status: equivalent`; `validate-evidence-log.py` gains a check that any row mentioning Local cites that artifact | §9.3 |
| 13 | **Saturation pre-registered as a result** (fixture-level and suite-level rules); efficiency named as a secondary that cannot support "debug better" | §7.6, §11.8 |
| Missing (a)(b)(c) | Three **tool-plausibly-loses** fixtures added: #11 `wp-config.php` in parent dir; #12 dead `object-cache.php` drop-in; #13 fatal in `error.log` while a fresh `debug.log` misleads `read_error_log`. Each is grounded in a specific code path in `src/tools/` | §5, fixture dirs |
| Missing (php.ini) | **php.ini parity block** added to the stack contract; fixture 1's symptom re-derived: under stock WordPress the visitor sees the fatal-error-handler message, not a blank page, under *either* `display_errors` setting; prompt reworded, exact wording pending stack observation | §2.4, §11.4, §13 |
| Missing (independent author) | Expected-lift table requires an **independent author** (not the fixture author) before freeze; current values are marked provisional | §5, §11.1 |
| Prereq (a) | `tool-value-ab` validator profile **specified** (key sets, path registrations, directory-fixture inventory branch, `tool-value-fixture` metadata profile) | §9.2 |
| Prereq (b) | One-line fork refactor: `generateProjectContext` out of `main.ts` into a Local-free helper; the headless entrypoint prints it | §2.4 |
| — | Sample size recomputed for 13 fixtures at α=0.025 | §4.4 |
| — | Risks re-ordered; R1 and R2 rewritten to match the new gates; R13–R14 added | §10 |

## 0. The question, and the three questions hiding inside it

The stated question is: *does Claude Code do WordPress debug/dev work
measurably better with the `localwp-agent-tools` MCP add-on than without it?*

That question bundles three separable mechanisms, and the product claim you
can honestly make depends on which one carries the effect:

| Mechanism | What the add-on actually does | How a Local user gets it without the add-on |
|---|---|---|
| M1 Capability provisioning | `wp_cli` runs WP-CLI with the right PHP binary, socket, and `--path` already wired | Open Local's "Site Shell" (sources `ssh-entry/<siteId>.sh`) and run `wp` there |
| M2 Structured affordances | Named tools (`read_error_log`, `read_wp_config`, `site_health_check`, `wp_debug_toggle`) with parsed output, sitting in the agent's tool list | Know where `logs/php/error.log` is and `cat` it |
| M3 Context injection | Writes `CLAUDE.md` into the site dir naming the file layout and tools | Write your own `CLAUDE.md` |

Nobody disputes M1. The claim the product markets — *"agents debug better with
our tools"* — is M2, and only the **T–C1** contrast isolates it (C1 has a
working `wp`; T has a working `wp` *plus* the named tools and the context
file). T–C0 measures M1+M2+M3 together and is dominated by M1. v1 bound the
product claim to T–C0; that would have shipped a real-but-mislabeled effect,
the same trap as this project's N5 row. v2 therefore reports **two numbers,
always both, in a fixed order** (§7.5), and never lets the write-up choose
which to lead with.

## 1. Tool surface (as built, not as documented)

Read from `src/tools/*` and `src/mcp-server.ts`. Thirteen tools:

| Tool | Needs running site? | Touches | Notes that matter for fixture design |
|---|---|---|---|
| `wp_cli` | yes (DB) | PHP bin + `wp-cli.phar` + socket | Passes `-d mysqli.default_socket=` **and** `-d pdo_mysql.default_socket=`; appends `--path=<wpPath>` unless the caller passed `--path`; `cwd = wpPath`; env from `buildWpCliEnv` (`PHPRC`, `MYSQL_UNIX_PORT`, mysql bin dir on PATH, `DB_*`). Loads plugins/themes by default. **Blocks** `eval`, `eval-file`, `shell`, `db drop/reset/import`, `site empty/delete`. 60 s timeout, 10 MB buffer. |
| `read_error_log` | no | `logs/php/error.log` **or** `wp-content/debug.log` — whichever has the newer mtime (`debugMtime >= serverMtime` → debug.log; ties go to debug.log) | Parses `[ts] PHP Fatal error: msg in file on line N`. Reads only the last 5 MB. The mtime heuristic is the code path fixture 13 exploits. |
| `read_access_log` | no | `logs/nginx/access.log` (then `.1`, then `apache/`) | Plain lines, filterable. |
| `wp_debug_toggle` | no | `<wpPath>/wp-config.php` (writes `.bak`) | Sets `WP_DEBUG`, `WP_DEBUG_LOG`, `SCRIPT_DEBUG` together. Replaces an existing `define()` value in place; **inserts** a new `define()` before "That's all" if the constant is absent — the residue fix 5 addresses. Reports "not found" if `wp-config.php` is not in `wpPath` (fixture 11). |
| `read_wp_config` | no | `<wpPath>/wp-config.php` | Regex-parses `define()`s; `raw: true` returns the file. Same "not found" path as above. |
| `edit_wp_config` | no | `<wpPath>/wp-config.php` (writes `.bak`) | Value must be a PHP literal. Inserts before "That's all". |
| `get_site_info` | partial | version.php, `php -v`, wp-config, WP-CLI with `--skip-plugins --skip-themes`, 15 s timeout per call | Works when a plugin fatals. **Does not skip drop-ins** (fixture 12). |
| `site_health_check` | partial | `wp db check`, table count, dir perms, WP_DEBUG, log sizes, PHP version; 15 s timeouts | Not WordPress Site Health; a fixed six-check list. A WP-CLI timeout is reported as `Database connectivity: error — Connection failed: …` (the misdirection in fixture 12). Reports `wp-config.php: error — Not found` when the file is in the parent dir (fixture 11). |
| `site_start` / `site_stop` / `site_restart` / `site_status` / `list_sites` | — | Local's `SiteProcessManager` via `LocalApi` | **Only tools that touch Local's runtime.** Out of scope for this eval (§8). |

Two structural facts drive the whole design:

1. **`mcp-server.ts` and every file in `src/tools/` import nothing from
   `@getflywheel/local`.** Only `main.ts` does. `createMcpHttpServer({registry,
   localApi, authToken, port})` takes a plain `SiteConfigRegistry` of plain
   `SiteConfig` structs (16 string/number fields: paths, binaries, DB
   coordinates) and a 5-method `LocalApi` interface. The tool repo's own
   `tests/mcp-server.test.ts` already stands the full HTTP MCP server up with a
   mock `LocalApi` and a hand-built `SiteConfig`. A headless entrypoint is not
   a stub of Local — it is `main.ts` minus Electron, about 40 lines.
2. **Local on macOS/Linux is itself a native stack** ("lightning services":
   nginx + php-fpm + mysql binaries, per-site socket at
   `run/<siteId>/mysql/mysqld.sock`, per-site `php.ini` via `PHPRC`, logs at
   `<site>/logs/{php,nginx}/`). What the eight file/CLI tools "see" is a
   directory layout and a set of binaries. Nothing they see is Electron.

## 2. The make-or-break decision: CI vs Local

### 2.1 Facts about this machine

Local is **not installed** here: no `/Applications/Local.app`, no
`~/Library/Application Support/Local`, no `~/Local Sites`. Present: Docker
29.4, Homebrew PHP 8.5.8, Claude Code 2.1.259, no `wp` on PATH. Option (a)
"run against a real Local install" therefore has a nonzero setup cost even
before design work, and nothing about the product can be exercised on this
machine today.

### 2.2 Options, honestly

**(a) Real Local on a dev laptop.** Perfect external validity — the actual
product on the actual platform, including the actual control-arm friction (a
Homebrew `wp` cannot reach Local's socket without the site shell). Zero
CI-ability for anything, including fixture validity. Every rerun needs a
Local laptop. Local has no CLI for site creation, so the runner cannot
provision sites; a human creates one once and the runner resets its state.
Running Local under `xvfb` on a Linux CI runner and driving site creation is
theoretically possible and practically a research project; rejected.

**(b) Headless MCP server against a non-Local WordPress.** Reuse
`createMcpHttpServer` with a hand-built `SiteConfig`. The question is what
backs it:

- *(b-docker) wp-env or Compose WordPress.* PHP lives in a container; the
  tool's `phpBin` must be a host binary. Wrapping `docker exec` behind a fake
  `php` mangles `--path` and socket arguments; `wp-config.php`'s `DB_HOST`
  differs between container and host. Every workaround is visible to the
  agent and diverges from what the tool does in Local. Rejected.
- *(b-native) A native nginx + php-fpm + MariaDB stack laid out exactly like a
  Local site.* `SiteConfig` maps 1:1 with no wrappers: `phpBin` is a real PHP,
  `wpCliBin` is `wp-cli.phar`, `dbSocket` is a real socket at a
  Local-shaped non-default path, logs are where Local puts them. This is
  architecturally *the same thing Local runs*, minus the GUI. It provisions
  on Ubuntu in about a minute (`apt install nginx php8.3-fpm mariadb-server`),
  so it is CI-able, and it runs identically inside one Docker container on
  macOS.

**(c) Scope to the automatable subset.** This is not an alternative to (a) or
(b); it is the honesty section (§8), and it applies regardless.

### 2.3 Recommendation: (b-native) as the measurement lane, deterministic parity as the license for "Local"

**Lane H (headless, native stack)** is the primary lane. All fixture seeding,
oracle validity, and MCP tool-contract checks run in CI with no LLM. The agent
A/B runs are operator-run (this repository's standing policy keeps LLM calls
out of CI for cost and nondeterminism, not because they cannot run there),
inside the same container image, on any machine with Docker, and archived.

**Lane L (real Local)** exists for exactly one confirmatory purpose: the
**deterministic tool-output equivalence check** in §2.5. It is R=1, involves
no agent, and either passes or names the tool that diverged. The v1 gate
(three fixtures × all arms × R=5, reject parity if success rates differ by
more than 0.30) is withdrawn: with R=5 a difference of 0.30 means
|k₁−k₂| ≥ 2, which fires spuriously in roughly a third of comparisons under
perfect parity and in almost every run across twelve comparisons. It would
have forced a pre-registration deviation nearly every time it ran.

Lane L **agent runs** are optional and **descriptive only**: fixture 1, arms
T/C0/C1, R=3, reported as counts with no p-value, never pooled with Lane H,
and never cited for a claim. Their job is to let a human read three
transcripts from the real product and notice anything the parity check cannot
see (setup UX, router latency, Local's own prompts).

Why not (a) alone: it cannot gate fixture validity in CI, and the "confound
wall" this project already hit (N3, N5 in `negative-results.md`) was an
instrument problem. An oracle that accepts a cheat, or a seed that fires
intermittently, produces a beautiful A/B of noise, and only a deterministic
gate that runs on every change catches that regressing. Also, Local is not
here; (a) alone means no work can start.

Why not (b) alone: parity is an assumption until measured, and the product's
claim is about Local specifically. The §2.5 check is what licenses the word
"Local" in any conclusion — and §9.3 makes that a tooling rule, not prose.

What (b-native) gets wrong even after parity, stated so it cannot be
discovered later: `get_site_info` returns different absolute paths (normalized
away in §2.5); the add-on's setup flow (Enable button → files written) is
bypassed and reproduced by the harness; the five environment tools have a
stub `LocalApi`; the hostname is `http://<name>.local` via container
`/etc/hosts` rather than Local's router; the golden sets
`WP_HTTP_BLOCK_EXTERNAL`, which Local does not (§4.1, C0 pin ii); nginx
serves only port 80, so fixture 11's `https://` symptom is "connection
refused" here and a certificate warning in Local. None of these are on any
fixture's critical path. All are in §8.

### 2.4 Lane H stack contract (mirrors Local where the tools look)

```
/srv/sites/<name>/                 ← Local: ~/Local Sites/<name>/
  app/public/                      WordPress root; wp-config.php here (fixture 11 moves it to app/)
  logs/php/error.log               php-fpm error_log (see php.ini parity block)
  logs/nginx/access.log            nginx access_log
  logs/nginx/error.log
  conf/                            nginx/php/mysql conf, as Local
/srv/run/<siteId>/mysql/mysqld.sock   deliberately NOT /tmp/mysql.sock (see §4.1, arm C0)
/srv/run/<siteId>/conf/php/php.ini    PHPRC
/srv/local-app/extraResources/bin/wp-cli/wp-cli.phar   ← paths.ts findWpCli() candidate 1; mode 0644; NOT on PATH
/srv/local-app/lightning-services/mysql-<ver>/bin/linux/bin/mysql   ← paths.ts findMysqlBinary(); NOT on PATH
```

`wp-config.php` is Local-shaped (`DB_HOST` = `localhost`), so the tool's
`-d mysqli.default_socket=` path is exercised for real. PHP pinned to 8.3.x
(Local's shipping default at time of design — open question §13.10; verify
and record). Site URL `http://<name>.local`, resolved in-container.

**Golden `wp-config.php` constants (fix 5 and C0 pin ii):**

```php
define( 'WP_DEBUG', false );
define( 'WP_DEBUG_LOG', false );
define( 'SCRIPT_DEBUG', false );            // explicit, so wp_debug_toggle replaces in place and never inserts
define( 'WP_ENVIRONMENT_TYPE', 'local' );   // mirrors Local (verify — §13.4)
define( 'WP_HTTP_BLOCK_EXTERNAL', true );   // egress is off; stop WordPress waiting on api.wordpress.org
define( 'AUTOMATIC_UPDATER_DISABLED', true );
```

`WP_DEBUG_DISPLAY` is **not** defined in golden (WordPress default: true
when WP_DEBUG is true). Requests to the site's own host are exempt from
`WP_HTTP_BLOCK_EXTERNAL`, so loopback cron spawning (fixture 6) still works.

**php.ini parity block (new).** These values change what an agent *sees*
and therefore what the fixtures measure. Lane H pins them; the source column
must be read off a real Local install before the prompts are frozen (§13):

| Directive | Lane H pin | Why it matters | Local's value |
|---|---|---|---|
| `display_errors` | `Off` | If `On`, a fatal prints file:line in the browser and every "find the fatal" fixture's lift collapses in all arms | **open (§13.1)** |
| `log_errors` | `On` | Without it there is no error.log to find | open |
| `error_log` | `<site>/logs/php/error.log` | Where fatals go when `WP_DEBUG_LOG` is off | open |
| *source of `error_log`* | php.ini value (overridable) | If Local sets it as php-fpm `php_admin_value`, WordPress's `ini_set('error_log', debug.log)` is silently ignored and **debug.log is never written by PHP errors** — this changes fixture 2's path and the `read_error_log` heuristic's real-world behavior | **open (§13.2)** |
| `error_reporting` | `E_ALL` | Notice volume in logs | open |
| `output_buffering` | `4096` | Whether the header renders before the fatal-handler message (fixture 1 wording) | open (§13.9) |
| `max_execution_time` | `30` | Does not count `sleep()`/socket waits on Linux; fixture 12 relies on that | open |
| `memory_limit` | `256M` | Fixture 4 uses `WP_MEMORY_LIMIT`, not this | open |
| `mysqli.default_socket` | `/srv/run/<siteId>/mysql/mysqld.sock` | Local sets this per site (why the tool exports `PHPRC`) | open (verify) |
| `date.timezone` | `UTC` | Formatted-date assertions (fix 4) | open |

**nginx pins:** `fastcgi_read_timeout 60s` (fixture 12's 504 symptom; Local's
value open, §13.5); `log_format` matching Local's (open; affects
`read_access_log` parity).

**Fixture 1's symptom, re-derived against the stack.** Stock WordPress ≥ 5.2
installs `WP_Fatal_Error_Handler` as a shutdown function. On a plugin fatal
with `display_errors=Off` and `WP_DEBUG false`, the visitor does **not** see a
blank page; they see "There has been a critical error on this website." (a
500 if headers were not yet sent, otherwise appended to partial output). With
`display_errors=On`, they see the PHP fatal text *and* that message. "Blank
page" was wrong under either setting. The prompt is reworded (§11.4); the
lift prediction is conditional on `display_errors=Off`, and if Local ships
`On`, Lane H follows Local and the independent author re-predicts.

Headless entrypoint (proposed to live in the fork as `scripts/headless-mcp.ts`
so it tracks the tool's internals, not a copy):

```
read SiteConfig JSON (argv), port (argv), token (env HEADLESS_MCP_TOKEN)
registry = new SiteConfigRegistry(); registry.register(cfg)
localApi = { startSite/stopSite/restartSite: reject('unsupported in headless harness'),
             getSiteStatus: () => ({id, status:'running'}), listSites: () => [one entry] }
server = createMcpHttpServer({registry, localApi, authToken: token, port}); startMcpHttpServer(server, port)
--print-context <siteName>   prints generateProjectContext(siteName) and exits (used by the harness for arm T's CLAUDE.md)
```

`.mcp.json` for arm T is produced by the fork's own `buildMcpServerEntry('claude', port, siteId, token)`
(`src/helpers/mcp-config.ts`, already Local-free).

**Build prerequisite (b), the refactor:** `generateProjectContext` currently
lives in `src/main.ts` (imports `@getflywheel/local`) and takes a
`Local.Site`; it only reads `site.name`. Move it to
`src/helpers/project-context.ts` as `generateProjectContext(siteName: string): string`
with `main.ts` calling `generateProjectContext(site.name)`. The headless
entrypoint's `--print-context` then prints the byte-exact text the add-on
writes, and the harness stores its SHA-256 in every `grading.json`. Until the
refactor lands, the harness carries a verbatim copy with the source commit
recorded — a drift risk, named. The tool-stripped variant for `C1-ctx` (§4.1)
is a harness-side transform of that text, not a second source.

### 2.5 Deterministic tool-output equivalence check (replaces the v1 parity gate)

**Purpose.** Establish that the eight in-scope tools, called through the real
MCP endpoint, return the same thing against Lane H's stack as against a real
Local site with the same golden and the same seeded fault. This is what
licenses the word "Local".

**Procedure (R=1, no agent).**

1. Same golden (fixture 1) restored in both lanes; same `seed.sh` and
   `trigger.sh` run. Lane L's site is created once by hand in Local; the
   runner restores golden through Local's own binaries via the site shell.
2. Endpoint: Lane H = headless server (`http://127.0.0.1:<port>/sites/<siteId>/mcp?token=…`);
   Lane L = the add-on's real server, port from `~/.local-agent-tools/port`,
   token from `~/.local-agent-tools/token` (`src/helpers/port.ts`, `auth.ts`).
3. JSON-RPC over HTTP: `initialize` → `tools/list` → the call sequence below,
   identical arguments in both lanes, in this order (the toggles are
   order-sensitive):

   | # | Tool | Args | Compared fields after normalization |
   |---|---|---|---|
   | 1 | `tools/list` | — | set of 13 names; each `inputSchema` byte-equal |
   | 2 | `read_error_log` | `{}` | last parsed entry: `level`, `message`, `file` (suffix after `<SITE>`), `line` |
   | 3 | `read_error_log` | `{lines: 5, filter: "Fatal"}` | same fields; `showing` |
   | 4 | `read_access_log` | `{lines: 5}` | `file` suffix; each line matches the same `log_format` regex |
   | 5 | `read_wp_config` | `{}` | `tablePrefix`; `constants` map (exact) |
   | 6 | `wp_cli` | `{args: "plugin list --format=json"}` | JSON rows on `name`, `status`, `version` |
   | 7 | `wp_cli` | `{args: "option get home"}` | equal after host normalization |
   | 8 | `wp_cli` | `{args: "eval 'echo 1;'"}` | refusal text byte-equal |
   | 9 | `get_site_info` | `{}` | `wpVersion`, `phpVersion` (major.minor), `wpDebug`, `tablePrefix`, `activePlugins[].name`, `activeTheme[].name` |
   | 10 | `site_health_check` | `{}` | ordered list of `checks[].check`; `checks[].status` per check |
   | 11 | `wp_debug_toggle` | `{enable: true}` | — |
   | 12 | `read_wp_config` | `{}` | `constants` map (must show the three debug constants `true`) |
   | 13 | `wp_debug_toggle` | `{enable: false}` | — |
   | 14 | `read_wp_config` | `{}` | `constants` map equal to step 5 (round-trip leaves no residue in either lane) |
   | 15 | `edit_wp_config` | `{name: "ACME_PARITY", value: "'1'"}` | — |
   | 16 | `read_wp_config` | `{}` | `constants.ACME_PARITY == "1"` |

4. **Normalization** before diffing: site root prefix (`/srv/sites/<name>` ↔
   `/Users/<u>/Local Sites/<name>`) → `<SITE>`; run dir (`/srv/run/<siteId>`
   ↔ `~/Library/Application Support/Local/run/<siteId>`) → `<RUN>`; binary
   prefixes → `<BIN>`; log timestamps `[dd-Mon-yyyy hh:mm:ss TZ]` → `[TS]`;
   `sizeKb`, `totalLines` → `<N>`; hostnames → `<HOST>`.
5. Output `parity/parity-report.json`: one record per row
   `{step, tool, args, lane_H, lane_L, equal, diff}` plus
   `status: equivalent | divergent`, `fork_commit`, `local_version`,
   `stack_image_digest`, `date`. Any `equal: false` → `divergent`, naming the
   tool(s).

**Consequences.** `equivalent` unlocks the word "Local" in the scorecard
(§9.3). `divergent` on tool X marks every fixture whose `tools_expected_in_T`
includes X as "Lane H only; parity failed on X" and keeps the word blocked.
There is no threshold and nothing to tune.

**CI half.** The Lane H side runs in CI against two independently built stack
containers ("self-parity") to catch the normalizer's own flakiness. The Lane L
half runs once per (fork commit, Local version) on the Local machine and is
archived under `parity/lane-L/<date>/`.

**What this check cannot see:** anything not in a tool's output — Local's
setup UX, router latency, whether Local's site shell sets a default `--path`
(§13.3). Those are named limits, not gates.

## 3. Discipline: what makes this falsifiable

1. **Primary metric is a machine-checked end state.** Per run, the oracle
   inspects the site (HTTP, WP-CLI, SQL, files, log tail) and emits
   `pass | fail | timeout | error`. It never reads the transcript. No LLM
   judge anywhere in confirmatory analysis.
2. **Correctness, not just "site loads."** Every oracle has three parts:
   symptom resolved; functionality preserved (the broken feature still
   *works*, checked by **content and by a post-hoc dynamic probe**, not by
   marker presence); no collateral (changed-file set ⊆ allowed set,
   `wp-config.php` semantically equal to golden, DB schema/option diff ⊆
   allowed set). "Deactivate the plugin" fails every fixture where the plugin
   is the feature.
3. **The primary is "pass within 60 turns."** The turn cap is the only binding
   budget and it is identical across arms. Wall clock is recorded and
   reported but does not gate; a 45-minute safety kill is classed `error`
   (harness), not `timeout`, and its count is reported per arm. MCP
   round-trips cost T wall time, not turns.
4. **Verbosity cannot move the primary metric.** It is a bit. Secondary
   metrics are counts of turns (not tokens, not tool calls — the treatment
   arm has an extra tool *type*, so tool-call counts are not comparable
   across arms; assistant turns are). Efficiency is reported only among
   passing runs. Tokens are reported as cost. The one text-based check
   (§6 "root cause named") is exploratory, restricted to the first 150 words
   of the final message to remove the length advantage, and barred from any
   claim — the N5 lesson, applied in advance.
5. **Everything except tool availability is held constant** — same prompt
   bytes (hash recorded), same model string, same Claude Code version, same
   turn cap, same permission mode, same cwd, same fresh site state, same
   fresh agent config dir. §4.3 lists each.
6. **Expected lift is pre-registered per fixture and per contrast, by an
   author who did not write the fixtures** (§5). A tool that "wins" on
   fixtures where no mechanism predicts a win is a confound alarm, not a
   bonus.
7. **The design can lose.** Fixtures 10–13 are built so the tool's own output
   can mislead the agent. Fixture 7 is built so no tool helps. If T ≈ C1
   across the board, the tool-quality claim fails and the result is recorded
   in `negative-results.md` as a row, archive committed before anyone reads
   the summary (§9).

## 4. Protocol

### 4.1 Arms

All arms are Claude Code with its default tool set (Bash, Read, Edit, Grep,
Glob; WebFetch off; network egress off). They differ only as stated.

| Arm | MCP | `CLAUDE.md` in site dir | `wp` on PATH | Represents |
|---|---|---|---|---|
| **T** treatment | `local-wp` server via `.mcp.json` | add-on's generated text, byte-exact | no | Local user who clicked Enable |
| **C0** naive control | none (`--strict-mcp-config` with empty config) | none | no | Local user without the add-on, no site shell |
| **C1** capability-matched control | none | none | **yes**: the shim below | Local user who opened the site shell |
| **C1-ctx** (conditional ablation) | none | **tool-stripped** generated text | yes: the shim | isolates M3's informational content on the primary contrast's base |

**Contrasts.** Primary (tool-quality claim): **T vs C1**, α = 0.025.
Co-primary (provisioning claim): **T vs C0**, α = 0.025. Attribution
(conditional): C1-ctx runs iff T–C1 meets the success criterion; then
C1-ctx − C1 estimates M3's informational content and T − C1-ctx estimates M2
plus the context file's tool-steering sentences (inseparable from M2 — that
steering is how the product gets its tools used). Exploratory: C1 − C0 (M1
alone).

**Why the ablation base moved from C0 to C1 (finding 7, deviation).** v1's
T-ctx was C0 + the full generated context. Two problems: the full text tells
the agent to call `get_site_info` and `wp_cli`, which T-ctx does not have, so
it underperforms for a reason unrelated to M3; and an ablation on C0's base
attributes the T–C0 gap, whereas the claim now rides on T–C1. Putting the
stripped context on C1 answers the question the headline asks.

**The tool-stripped context** is `stripToolReferences(generateProjectContext(name))`:
drop every line containing `MCP`, `tool`, `` `wp_cli` `` or `` `get_site_info` ``,
then collapse blank runs. Applied to the current text this leaves the title,
"This is a WordPress site managed by [Local](https://localwp.com/).", the
whole "File Structure" section, and the auto-generated notice — i.e. the
file-layout knowledge and nothing that names a capability. Both variants'
SHA-256 are recorded per run (`context_sha256`, `context_variant`).

**The C1 shim** mirrors `src/tools/wpcli.ts` `runWpCli()` in effect
(finding 6). Installed at `/usr/local/bin/wp`, mode 0755, in arm C1/C1-ctx
only:

```sh
#!/bin/sh
# C1 shim: the equivalent of Local's site shell, built to match src/tools/wpcli.ts runWpCli()
export PHPRC="$SITE_PHP_INI_DIR"                     # buildWpCliEnv: PHPRC (dir, not file)
export MYSQL_UNIX_PORT="$SITE_DB_SOCKET"              # buildWpCliEnv
export MYSQL_PWD="$SITE_DB_PASSWORD"                  # buildWpCliEnv
export PATH="$SITE_MYSQL_BIN_DIR:$PATH"               # buildWpCliEnv: mysql client dir prepended
has_path=0
for a in "$@"; do case "$a" in --path|--path=*) has_path=1 ;; esac; done
[ "$has_path" -eq 0 ] && set -- "$@" "--path=$SITE_WP_PATH"   # wpcli.ts: append --path unless present
exec "$SITE_PHP_BIN" \
  -d "mysqli.default_socket=$SITE_DB_SOCKET" \
  -d "pdo_mysql.default_socket=$SITE_DB_SOCKET" \
  "$SITE_WP_CLI_PHAR" "$@"
```

Retained asymmetries, all properties of the product and reported, not
corrected: the shim has no 60 s timeout, no 10 MB buffer cap, and no blocked
command list (`eval` works in C1). Omitted as inert for WP-CLI: `DB_HOST`,
`DB_USER`, `DB_PASSWORD`, `DB_NAME`, `MYSQL_HOST`, `MYSQL_TCP_PORT` (set by
`buildWpCliEnv` but consumed by nothing on this path). Pre-run assertion
(R12): from cwd `/srv/sites/<name>`, `wp core version` through the shim must
succeed before the agent starts — that is exactly the call v1's shim would
have failed.

Whether Local's real site shell supplies `--path`-equivalence (by `cd`-ing
into `app/public` or otherwise) is **open (§13.3)**. If it does not, C1 as
built is slightly *more* capable than a site-shell user, which biases T–C1
toward zero — conservative for the tool claim, and stated.

**C0 pins (finding 8).** Each pin states its direction of bias.

| Axis | Pin | Reality it mirrors | Bias |
|---|---|---|---|
| (i) phar location | `wp-cli.phar` on disk at the Local-shaped bundled path (§2.4), mode 0644, not on PATH, no `wp` anywhere on PATH | Local ships the phar inside the app bundle; a user without the site shell has it on disk and not on PATH | none intended: C0 can `find / -name wp-cli.phar` exactly as a Local user could |
| (ii) network egress | **off** for every arm (`--network none` on the agent container; site and MCP are loopback) with `WP_HTTP_BLOCK_EXTERNAL` in golden so WordPress does not stall on blocked HTTP | a Local user has egress; Local does not set `WP_HTTP_BLOCK_EXTERNAL` | removes C0's "download a phar" path (biases T–C0 up, marginally; pin (i) restores an equivalent path); T–C1 unaffected; reproducibility and no data exfiltration under `bypassPermissions` |
| (iii) mysql client | `mysql` client on disk at the Local-shaped lightning-services path, not on PATH; MariaDB listening on the socket **and** on `127.0.0.1:10003` (Local allocates per-site ports; verify §13.6); credentials `root`/`root` as Local writes them into `wp-config.php` | Local's DB is reachable over TCP from any client if you know the port | C0 can reach the DB with `ss -ltnp` + `wp-config.php` creds, as in Local; without the TCP listener C0 would be harder than reality |

C0 deliberately has PHP on PATH (any Mac developer does) but no `wp`, and the
MariaDB socket is at a Local-shaped non-default path. This reproduces the real
friction: a Homebrew `wp` against a Local site fails on the socket until you
find `run/<siteId>/`. If Lane H put MariaDB on `/tmp/mysql.sock`, a bare `wp`
would just work and C0 would be easier than in Local — the design would then
*understate* the add-on. That is why §2.4 pins the socket path.

### 4.2 Run procedure (one cell = one fixture × arm × rep)

1. **Reset** site to golden: restore `app/public/` (and, for fixture 11,
   `app/wp-config.php`) from tarball, drop/recreate DB from `golden.sql`,
   truncate `logs/php/error.log` and `logs/nginx/*.log`, remove
   `wp-config.php.bak`, remove `wp-content/debug.log` (except fixture 13,
   whose golden ships one), remove `.mcp.json` and `CLAUDE.md`, remove the
   shim.
2. **Seed** the fixture fault (`seed.sh`), then **trigger** it once the way a
   user would (GET the failing URL, POST the form, etc.) so the failure is
   *logged* — the "users reported it" precondition. Record byte offset of
   `error.log` as `trigger_log_offset` (descriptive use only, see step 7).
3. **Pre-oracle**: run the oracle. It must return `fail`. If it returns
   `pass`, the seed did not take; the cell is **void**, re-seeded once, and
   the void is logged. Never counted.
4. **Arm setup**: write `.mcp.json` + `CLAUDE.md` (T) or tool-stripped
   `CLAUDE.md` (C1-ctx) or ensure both absent (C0, C1); install the shim (C1,
   C1-ctx) or ensure absent; start headless MCP server (T) on a per-container
   port with a per-run throwaway token.
5. **Pre-run assertions** (R12): C0/C1/C1-ctx have no `.mcp.json`; T's
   `tools/list` returns exactly 13 names; C1/C1-ctx `wp core version` via the
   shim succeeds from the site root; `curl --max-time 3 https://api.wordpress.org/`
   fails (egress off); `CLAUDE.md` SHA-256 matches the arm's expected variant.
   Any failure → cell `error`, run aborted, never counted.
6. **Fresh agent config**: `CLAUDE_CONFIG_DIR=<run>/claude-config` containing a
   minimal `settings.json`, no skills, no agents, no global `CLAUDE.md`, no
   memory. Per **run**, not per arm — Claude Code auto-memory would otherwise
   carry rep 1's solution into rep 2.
7. **Invoke** (identical bytes across arms except `--mcp-config` target):
   `claude -p "$(cat prompt.md)" --model <pinned> --max-turns 60
   --permission-mode bypassPermissions --output-format stream-json --verbose
   --mcp-config <arm.mcp.json> --strict-mcp-config`, cwd = `/srv/sites/<name>`.
   Hitting 60 turns → `timeout`. A 45-minute wall-clock safety kill
   (`bounded_subprocess`) → `error:wall_cap`, reported separately, never
   folded into `timeout`.
8. **Post-agent offset** (finding 3): record `post_agent_log_offset` =
   current byte length of `logs/php/error.log`. Everything the agent caused
   to be logged — including its own reproductions of the fault — sits before
   this offset and is descriptive (`fatals_during_run`), not gating.
9. **Post-oracle**: run the oracle → `pass | fail`. The oracle issues its own
   requests; "no new fatal" is evaluated only after `post_agent_log_offset`.
   Collect changed-file set (hash diff against golden), `wp-config.php`
   semantic diff, DB option/schema diff.
10. **Transcript metrics** (separate parser, never feeds the oracle): turns,
    tool calls by name (incl. `mcp__local-wp__*` counts), wall time, tokens,
    final message, turn index at which the agent ended.
11. **Redact** the bearer token from the archived transcript (`.mcp.json` URLs
    carry `?token=`).
12. Write `grading.json` (§6) and archive.

### 4.3 Held-constant list

Prompt bytes (SHA-256 in grading.json) · model string · `claude --version`
(abort the stage if it changes mid-run) · `--max-turns 60` · cwd ·
permission mode · golden snapshot digest · seed script digest · PHP/MariaDB/
nginx versions · php.ini digest · container image digest · no
parent-directory `CLAUDE.md` (`/srv/sites` is a clean tree; on a Lane L
laptop, `~/Local Sites` must not sit under any directory containing a
`CLAUDE.md`) · no user skills (the `wordpress-*` skills in this very
repository would otherwise load and help all arms equally while changing the
population) · arm order randomized within each (fixture, rep) triple and all
arms of a triple completed before the next triple, so model-side drift over a
multi-hour run is spread across arms · network egress off in every arm.

### 4.4 Sample size

Thirteen fixtures (§5), three arms, R reps per cell, two co-primary contrasts
at α = 0.025 each (two-sided). Planning-grade power treating cells as
independent proportions with a 0.50 base rate (ignores fixture clustering,
which lowers effective n, and within-fixture pairing, which raises power —
they pull opposite ways; for T–C1 the C1 base rate is likely above 0.50,
which shifts Cohen's h slightly):

| Reps R | Trials per arm | Δ = 0.30 | Δ = 0.25 | Δ = 0.20 | Δ = 0.15 |
|---|---|---|---|---|---|
| 6 | 78 | 0.96 | 0.85 | 0.63 | 0.37 |
| 10 | 130 | 1.00 | 0.98 | 0.86 | 0.59 |

(Cohen's h; power = Φ(h·√(n/2) − 2.241). At v1's α = 0.05 the R=6 row was
0.98/0.90/0.72/0.46; the α split costs about 0.05 of power at the MDE.)

Pre-registered plan: **Stage 1 at R = 6** (13 × 3 × 6 = 234 runs). MDE at
80% power ≈ **0.24** (α = 0.025). If, for either co-primary contrast, the
Stage 1 point estimate exceeds 0.15 and p ≥ 0.025, **Stage 2 extends every
arm to R = 10** (156 more runs) so both contrasts stay paired on the same
data. MDE at Stage 2 ≈ **0.19**. Both stages are reported whatever they show.
A null at R = 6 means "no *large* effect," and the write-up must say exactly
that. The realized type-I error of this rule is computed in §7.4.

C1-ctx, if triggered, adds 13 × R runs (78 or 130).

Planning cost, not measured: 234 runs × (3–8 min, $0.5–3) ≈ 12–31 h serial,
3–8 h across four containers; roughly $120–700. Fixture 12 adds ~1 min per
probe the agent makes. Lane L parity (§2.5) is minutes; Lane L descriptive
agent runs (optional) ~1 h.

## 5. Fixtures

Thirteen seeded-fault scenarios. Each is independent (own plugins, own golden
snapshot, no shared state). Each has: seed, trigger, prompt (identical across
arms, describes the *symptom* as a user would — never names logs, WP-CLI, MCP,
config files, or the culprit), oracle with the three-part structure, allowed
change set, cheat suite, and pre-registered expected lift **per contrast**.

Expected-lift vocabulary: HIGH (a tool surfaces the answer in one call that
the control must discover), MEDIUM (a tool shortens the path but the control
has a comparable path), LOW (tools marginally relevant), NONE (control
fixture; solution is code reading), ADVERSARIAL (a tool's output can mislead;
negative lift plausible).

**Authorship rule (new).** The binding expected-lift table is written by
someone who has **not** read any `seed.sh`, `oracle.spec.yaml` or golden
plugin source — given only §1 (tool surface), §4.1 (arms), and each
fixture's `prompt.md`. Their predictions go into `prereg.md` with name and
date and into each `metadata.yaml` under `predictions.independent`. The
values in the table below are the **fixture author's, provisional**, kept so
the monotonicity check's shape is visible; they are superseded at freeze and
must not be used for the check. The fixture author's column stays in
`metadata.yaml` under `predictions.fixture_author` so the two can be compared
afterwards (a large disagreement is itself information about the fixture).

| # | Fixture id | Fault (seed) | Symptom (prompt gist) | Oracle: symptom · functionality · no-collateral | Provisional lift T–C1 (primary) · T–C0 (co-primary) · mechanism |
|---|---|---|---|---|---|
| 1 | `fatal-undefined-function-page-scoped` | Plugin `acme-events` requires its formatter file only on admin; frontend `/events/` template calls `acme_format_date()` → fatal. Homepage fine. Six other small plugins installed as haystack (7 total, pre-registered). | "The Events page shows 'There has been a critical error on this website'. The events list must keep working." | GET `/events/` 200 · body has `<ul class="acme-events">` with three `<li>` each carrying `<time class="acme-date">` whose text equals the golden formatted date · dynamic nonce-event probe renders · `acme-events` active; no `Fatal error` after post-agent offset; changes ⊆ `plugins/acme-events/**`; `wp-config.php` semantically equal | **MEDIUM · HIGH** · `read_error_log` yields file:line in one call; C1 can `tail logs/php/error.log` once it thinks to and has `wp plugin list`; C0 must find `logs/php/` or bisect seven plugins |
| 2 | `missing-custom-table-wpdebug-off` | Plugin `acme-forms` inserts into `wp_acme_submissions`; table dropped after activation; `WP_DEBUG false` so UI shows only "Submission failed". | "The contact form on /contact/ says 'Submission failed' for everyone." | oracle-driven POST inserts a row · table exists · plugin active; changes ⊆ plugin dir ∪ {new table} | **MEDIUM · HIGH** · `wp_debug_toggle` then `read_error_log` exposes `$wpdb` error; C1 has `wp config set` + `tail`; either fix path (reactivate → dbDelta, or CREATE TABLE) passes. Path depends on §13.2 |
| 3 | `wpconfig-home-mismatch-redirect-loop` | `define('WP_HOME','http://staging.acme.test')` in wp-config. | "Every frontend URL redirects to staging.acme.test, which doesn't exist." | GET `/` 200 with no `Location` · `wp option get home` canonical · `WP_HOME` absent or canonical; no option collateral | **LOW · LOW/MEDIUM** · `read_wp_config` parses constants; `cat wp-config.php` is one step away. Trap: `wp option update home` is a no-op under the constant |
| 4 | `wpconfig-memory-limit-fatal` | `WP_MEMORY_LIMIT '24M'` + plugin `acme-reports` builds a ~30 MB array on `/reports/`. | "/reports/ shows the critical-error message." | GET `/reports/` 200 · body has `id="acme-report"` · plugin active; no fatal after post-agent offset | **LOW · MEDIUM** · error log names the exhaustion instantly in any arm that reads it; raising the constant or slimming the plugin both pass |
| 5 | `autoload-options-bloat` | 40 options `acme_cache_*`, ~600 KB each, `autoload=yes` (~24 MB in `alloptions`). `acme_settings` is a legitimate autoloaded option. | "Every page, including admin, takes seconds; nothing in the theme changed." | Σ`LENGTH(option_value)` where autoload ∈ {yes,on} < 1 MB · `acme_settings` present and autoloaded · `/` 200 | **NONE · MEDIUM** · `wp option list --autoload=on --fields=option_name,size_bytes` is one call in T and C1 alike; C0 must reach the DB. TTFB deliberately not oracled (flaky) |
| 6 | `cron-disabled-stuck-scheduled-posts` | `DISABLE_WP_CRON true`, no system cron; five posts scheduled in the past. | "Scheduled posts never publish; they sit as Scheduled past their time." | `wp cron test` exit 0 and stdout matches `/working as expected/` · after runner GET `/` + ≤10 s, `post list --post_status=future --format=count` == 0 and the five are `publish` | **LOW · MEDIUM** · `read_wp_config` shows the constant; `wp cron test` (T and C1) names it. Limitation: "install a system cron" is a correct real-world fix the oracle cannot see — pre-registered as a known false negative |
| 7 | `n-plus-one-related-posts` | Plugin `acme-related` runs `get_post_meta` + `new WP_Query` per item across 60 related items on single posts (~250 queries). | "Single post pages render slowly compared with the homepage." | oracle-only mu-plugin (installed post-run, removed after) logs `get_num_queries()` on GET `/sample-post/` < 40 · body has `class="acme-related"` with ≥3 `<li>` · plugin active | **NONE · NONE (control)** · no tool exposes query counts; `wp_cli eval` is blocked (C1's `wp eval` is not — R11); the fix is code reading in every arm |
| 8 | `rewrite-rules-stale-cpt-404` | CPT `event` registered; `rewrite_rules` option pinned to a snapshot lacking its rules. | "Event pages 404 even though the events exist in admin." | GET `/event/sample-event/` 200 with title · `wp rewrite list` includes `event` | **NONE · LOW** · `read_access_log` shows 404s (marginal); the fix (`wp rewrite flush`) is WordPress knowledge available to T and C1 |
| 9 | `debug-display-breaks-rest-json` | `WP_DEBUG` + `WP_DEBUG_DISPLAY` true; plugin `acme-meta` calls a deprecated function on `rest_api_init` → notice prepended to JSON. | "The editor says 'The response is not a valid JSON response' when saving." | `curl /wp-json/wp/v2/posts` parses as JSON · plugin active · `fix_class` recorded ∈ {source_fixed, display_disabled, debug_off} (exploratory, not scored) | **LOW · MEDIUM** · `wp_debug_toggle` is a one-call path for T; C1 has `wp config set`; C0 must edit wp-config or the plugin. All three fix classes pass; their distribution per arm is reported |
| 10 | `red-herring-stale-log-real-fault-constant` | Error log pre-filled with ~200 loud, two-day-old `PHP Warning` lines from plugin `acme-seo` (now fine). Real fault: `define('WP_CONTENT_URL','http://acme.test/wp-content')` → every asset 404s. | "The site loads but all styling and images are broken." | GET `/` 200 · first `<link rel=stylesheet>` href GETs 200 `text/css` · `acme-seo` files hash-identical and active · `WP_CONTENT_URL` absent or correct | **ADVERSARIAL · ADVERSARIAL** · `read_error_log` returns the herring first; a T agent that chases it wastes turns or "fixes" `acme-seo` (collateral → fail). Negative lift is a legitimate outcome |
| 11 | `wpconfig-in-parent-dir-tools-misreport` **(new)** | `wp-config.php` lives at `app/wp-config.php` (WordPress-supported parent-dir placement). Fault inside it: `define('FORCE_SSL_ADMIN', true)` on a site with no TLS → login redirects to `https://` which fails. | "Nobody can log in; /wp-admin/ ends up on an https:// address that won't load; the public site is fine over http." | GET `/wp-login.php` 200 with `<form name="loginform"` and no `https` Location · unauthenticated GET `/wp-admin/` 302s to `http://<host>/wp-login.php…` · `/` 200 · `FORCE_SSL_ADMIN` absent or false in `app/wp-config.php` · **`app/public/wp-config.php` must not exist** · options `home`/`siteurl` unchanged · plugin statuses equal | **ADVERSARIAL · LOW** · `read_wp_config`, `edit_wp_config`, `wp_debug_toggle` all answer "wp-config.php not found at: …/app/public/wp-config.php"; `site_health_check` reports `wp-config.php: error — Not found`; `get_site_info.wpDebug` is missing — while `wp_cli` (and C1's `wp config get`) work because WP-CLI resolves the parent dir. The tool set points the T agent at a phantom missing file; creating one shadows the real config (oracle: fail). C0 has `grep -r FORCE_SSL_ADMIN` |
| 12 | `dead-object-cache-dropin-tool-hangs` **(new)** | Stale `wp-content/object-cache.php` left by a previous host: on `wp_cache_init()` it tries `tcp://127.0.0.1:6379`, gets refused, and retries with backoff 5+10+20+40 s (75 s) before falling back to the in-memory cache. Nothing is logged. | "Every page, including the login page, hangs for about a minute then shows '504 Gateway Time-out'. Started after we moved the site here from our old host." | GET `/` returns 200 with TTFB < 10 s (healthy ≈ 0.1 s; faulted 75 s — not a flaky threshold) · body has the golden homepage title marker · plugin statuses equal (oracle WP-CLI calls carry a 30 s bound; a bound hit is `fail`) · changes ⊆ {`wp-content/object-cache.php` removed, renamed within `wp-content/`, or edited} · `wp-config.php` semantically equal · nginx/php conf under `conf/**` unchanged | **ADVERSARIAL · ADVERSARIAL** · `--skip-plugins` does not skip drop-ins, so `wp_cli` (60 s) times out, `get_site_info` (15 s) says "unable to retrieve (WP-CLI error)", and `site_health_check` (15 s) says **"Database connectivity: error — Connection failed"** — naming the wrong subsystem. C1's shim hangs 75 s but returns. Every arm pays the wait; only T is *told* it is the database |
| 13 | `fatal-in-error-log-fresh-debug-log-misleads` **(new)** | `WP_DEBUG`/`WP_DEBUG_LOG` false, so fatals go to `logs/php/error.log`. Haystack plugin `acme-cache` appends one "hits/misses" line to `wp-content/debug.log` on every request via `error_log($line, 3, …)` from a `shutdown` hook (golden ships a 2 MB, two-day history). Fault: `acme-forms` calls an undefined method on `/contact/`. PHP logs the fatal, **then** runs shutdown functions, so `debug.log`'s mtime is newer than `error.log`'s after every request — including the failing one and the agent's own reproductions. | "The contact page shows 'There has been a critical error on this website' where the form should be. Other pages are fine. The form has to keep working." | GET `/contact/` 200 · body has `<form class="acme-form"` with `name="acme_name"`, `name="acme_email"`, and the `acme_forms_nonce` field · dynamic probe: `wp option update acme_forms_title "Probe <nonce>"` then GET shows the nonce in `<h2 class="acme-form-title">` (option restored after) · `acme-forms` active · changes ⊆ `plugins/acme-forms/**` · `acme-cache` files hash-identical and active · `wp-config.php` semantically equal · `debug.log` excluded from the changed-file set | **ADVERSARIAL · ADVERSARIAL** · `findErrorLog()` returns `debug.log` (newer mtime) → `read_error_log` shows 50 lines of cache stats; with `filter: "Fatal"` it shows zero entries. The T agent is told, by its purpose-built tool, that nothing is wrong in the logs. C0/C1 `ls logs/php/` and `tail` the fatal. Independent of §13.2 because `error_log(…, 3, path)` bypasses the `error_log` ini |

Distribution vs T–C0: 2 HIGH, 4 MEDIUM, 3 LOW, 1 NONE, 3 ADVERSARIAL.
Distribution vs T–C1 (provisional): 0 HIGH, 2 MEDIUM, 4 LOW, 3 NONE,
4 ADVERSARIAL. That second line is the honest prior — most of what the add-on
does beyond WP-CLI is convenience — and it is the reason T–C1 has to be the
primary: if the tool-quality claim is true it has to be true *there*.

The pre-registered ordering HIGH > MEDIUM > LOW ≥ NONE, with ADVERSARIAL
permitted to be negative, gives a monotonicity check per contrast: observed
per-fixture Δ should roughly follow the independent author's ordering. A
large positive Δ on #7 or #8 in T–C1 is a confound alarm pointing at M3 —
run C1-ctx regardless of the trigger rule.

Selection bias, stated: fixtures 1–10 were chosen *because* live introspection
plausibly helps; fixtures 10–13 were chosen because the tool's real code paths
can mislead. The result generalizes to "faults where live introspection is
plausibly relevant," not to WordPress development at large. The adversarial
fixtures bound the optimism; they do not remove it.

## 6. Metrics and `grading.json`

Primary: oracle-gated success within 60 turns, per cell, binary.
Secondary (all deterministic, all from state or transcript structure):

| Metric | Source | Verbosity guard |
|---|---|---|
| `outcome` ∈ pass/fail/timeout/error | oracle + harness | bit; `error` carries a reason (`wall_cap`, `precheck`, `harness`) |
| `turns` (assistant messages) and `end_turn` (index at which the agent stopped) | transcript | count, cross-arm comparable; feeds pass@turn (§7.3) |
| `tool_calls_by_name` (incl. `mcp__local-wp__*`) | transcript | reported, **not** compared across arms (T has extra tool types); `mcp_invoked` is **retired** as an attribution signal — the context file instructs tool use, so its presence says nothing about M3 |
| `wall_ms`, `input_tokens`, `output_tokens` | transcript | cost only; MCP latency confounds wall time; never gates |
| `changed_files[]`, `wp_config_semantic_diff`, `db_option_diff`, `db_schema_diff` | state | collateral evidence |
| `fatals_during_run` (between trigger offset and post-agent offset) | log | descriptive: how often the agent reproduced the fault |
| `fix_class` (fixture 9) | state | categorical, exploratory |
| `root_cause_named` | first 150 words of final message contain the fixture's root-cause token | **exploratory**; length-favoring by construction; never in a claim |

```json
{
  "schema": "localwp-tool-value-grading/2",
  "run_id": "…", "lane": "H", "fixture": "…", "arm": "T|C0|C1|C1-ctx", "rep": 3,
  "prompt_sha256": "…", "golden_digest": "…", "seed_digest": "…", "php_ini_digest": "…",
  "context_variant": "full|stripped|none", "context_sha256": "…|null",
  "claude_version": "2.1.259", "model": "…", "image_digest": "…", "fork_commit": "78c87ea",
  "prechecks": {"mcp_tools_list_count": 13, "shim_ok": null, "egress_blocked": true, "context_hash_ok": true},
  "pre_oracle": "fail", "outcome": "pass",
  "checks": {"symptom_resolved": true, "functionality_preserved": true, "dynamic_probe": true, "no_collateral": true},
  "log_offsets": {"trigger": 4096, "post_agent": 8123},
  "secondary": {"turns": 14, "end_turn": 14, "tool_calls_by_name": {"Bash": 6, "Read": 3, "Edit": 1, "mcp__local-wp__read_error_log": 1},
                "wall_ms": 212000, "wall_cap_hit": false, "input_tokens": 0, "output_tokens": 0,
                "changed_files": ["app/public/wp-content/plugins/acme-events/acme-events.php"],
                "wp_config_semantic_diff": [], "db_option_diff": [], "db_schema_diff": [], "fatals_during_run": 2},
  "exploratory": {"root_cause_named": true, "fix_class": null},
  "void_reseeds": 0, "notes": ""
}
```

## 7. Statistical design

### 7.1 Estimands and criterion

Two estimands, fixtures weighted equally:

- Δ_C1 = mean over fixtures of (P(pass | T, f) − P(pass | C1, f)) — **primary, tool-quality claim**
- Δ_C0 = mean over fixtures of (P(pass | T, f) − P(pass | C0, f)) — **co-primary, provisioning claim**

`timeout` and `error` count as not-pass in both; their rates are reported
separately because a tool that reduces timeouts is a real effect (and a tool
that causes wall-cap errors is a real cost).

Pre-registered success criterion, **per contrast**: **p < 0.025 and
Δ ≥ 0.20**. A significant Δ of 0.10 is reported as "small, real on this
fixture class" and does not license "measurably better" in external material.
Meeting the criterion on Δ_C0 but not Δ_C1 licenses exactly the sentence
"the add-on gives agents zero-config WP-CLI access" and nothing about the
named tools.

### 7.2 Tests and intervals

Primary test (each contrast): **within-fixture label-permutation test** on Δ.
Under H0 the 2R outcomes in a fixture are exchangeable across arm labels;
permute labels within each fixture, recompute Δ, 10,000 permutations,
two-sided p. Exact under H0, no distributional assumption, respects
clustering. (Because outcomes are binary and n per arm per fixture is
equal, the permutation distribution of each fixture's difference is
hypergeometric; the stats script may compute it exactly rather than by
resampling — §7.4's simulation does.)

Interval: cluster bootstrap over fixtures (resample fixtures with
replacement; within each, resample reps), B = 2,000, percentile 95% CI.
Reported with the caveat that thirteen clusters make bootstrap CIs rough.

Effect size: Δ itself plus Cohen's h for the pooled rates.

Multiplicity: two co-primaries, Bonferroni, α = 0.025 each. C1-ctx
comparisons are attribution, reported with their own p and no correction,
labeled as such. Everything else is exploratory. Per-fixture: exact binomial
CIs per (fixture, arm); Fisher exact per fixture as descriptive, uncorrected,
plotted against the independent author's lift ordering.

Wilcoxon signed-rank on the thirteen fixture-level Δs is included as a
sensitivity analysis only: with n = 13 it has little power and is not the
primary.

### 7.3 pass@turn curves (finding 9)

For each arm and fixture, define pass@t = fraction of runs that **ended with
outcome `pass` at `end_turn` ≤ t**. Non-passing runs are censored at 60. This
is an upper bound on "turn at which the site was fixed" (an agent may fix at
turn 9 and verify until turn 14), applied identically across arms. Report the
curves per contrast at t ∈ {10, 20, 30, 40, 60}; pass@60 is the primary.
Curves are descriptive; the area between them is not tested. They exist so
that a reader can see whether an effect at 60 is "T finishes and C1 never
does" or "both finish, T sooner" — the latter is efficiency (§7.6), not
success.

### 7.4 Two-stage rule and its realized α (finding 11)

**Rule, verbatim.** Stage 1: R₁ = 6. For a contrast, compute Δ̂₁ and the
permutation p₁. Reject if p₁ < 0.025. Continue to Stage 2 iff p₁ ≥ 0.025 and
Δ̂₁ > 0.15. Stage 2 (triggered by either contrast, applied to all arms): add
4 reps per cell; recompute Δ̂₂, p₂ on the pooled R₂ = 10 data; reject if
p₂ < 0.025. Success at either stage additionally requires Δ̂ ≥ 0.20. No other
look at the data occurs.

**Simulation.** `evals/suites/localwp-agent-tools-value/statistical/simulate_two_stage_alpha.py`,
seed 20260902, 10,000 simulated suites, 4,000 exact permutation draws each,
F = 13, both arms sharing each fixture's pass rate p_f ~ U(0.20, 0.80):

| Quantity | nominal α = 0.025 | nominal α = 0.05 (v1) |
|---|---|---|
| Stage-1-only rejection rate | 0.0167 | 0.0363 |
| Continuation rate under H0 | 0.0173 | 0.0088 |
| **Realized P(reject at either stage)** | **0.0189** | 0.0384 |
| Realized P(success criterion met) | 0.0030 | 0.0038 |
| Share of rejections that came from Stage 2 | 11.6 % | 5.5 % |

**Reading.** The rule does not inflate α above nominal; it sits below it.
Two reasons, both structural: the within-fixture permutation test on binary
outcomes at R = 6 is discrete and conservative (0.017 at nominal 0.025), and
under H0 the continuation condition Δ̂₁ > 0.15 is about 1.9 standard errors
out and fires ~1.7 % of the time, of which only ~12 % go on to reject. The
review's estimate of 0.06–0.08 corresponds to a looser rule (continue on any
inconclusive result, test at 0.05, or take the smaller p of the two stages)
and is recorded here as the reason the rule was written down exactly. The
non-triggering contrast's Stage 2 look adds at most α × P(continue) ≈ 0.0004.
Sensitivity (same seed, same sizes): p_f ~ U(0.40, 0.60) → realized 0.0221
(p-criterion) / 0.0081 (success criterion), continuation 2.3 %; p_f ~
U(0.10, 0.90) → 0.0174 / 0.0027, continuation 1.3 %. The narrower the H0
band around 0.5, the closer to nominal, never above it. Caveat: realized α
depends on the assumed H0 pass-rate distribution; the script accepts
`--p-low/--p-high` and the stats script must re-run it with the observed C1
and C0 per-fixture rates as the H0 distribution and report that number
alongside.

### 7.5 Frozen headline template (finding 1)

The scorecard's headline is exactly these two lines, always both, always in
this order, filled from `summary.json`, with no other sentence above them:

```
Zero-config WP-CLI provisioning (T–C0):  Δ = __  [95% CI __, __]  p = __  (α = 0.025)  criterion met: yes|no
Named tools beyond WP-CLI (T–C1):        Δ = __  [95% CI __, __]  p = __  (α = 0.025)  criterion met: yes|no
```

Beneath them, one fixed secondary line (§7.6) and, if C1-ctx ran, one fixed
attribution line: `Context file alone (C1-ctx–C1): Δ = __ [CI]`. Neither line
contains the word "Local" (§9.3). The v1 sentence "the write-up must lead
with whichever the reader would call fair" is deleted; there is nothing to
lead with.

### 7.6 Saturation as a pre-registered result (finding 13)

- **Fixture-level saturation:** all three arms pass ≥ 5/6 at Stage 1. Recorded
  per fixture as `saturated: true`. The fixture stays in the analysis (its Δ
  is ≈ 0 and that is data); it is not redesigned, enlarged, or dropped.
- **Suite-level saturation:** ≥ 8 of 13 fixtures saturated. The primary
  result is then reported as "no detectable success-rate difference on this
  fixture class at this model; saturated," and the pre-registered secondary
  becomes the informative number.
- **Secondary S1 (efficiency):** median `end_turn` among passing runs, T vs
  C1, stratified by fixture (van Elteren), reported on its own fixed line
  under the headline. It licenses at most "finishes in fewer turns on faults
  it also solves without the tools." It **cannot** support "debugs better"
  and the scorecard generator prints that boundary sentence with it.

## 8. Measurable now vs blocked

### Measurable now (after building the harness; nothing has run)

- **Lane H, end to end**, for the eight file/CLI tools across thirteen
  fixtures and three arms, on this machine (Docker present) or any Docker
  host. Estimated build: 3–4 days for stack image, headless entrypoint,
  runner, thirteen fixtures with cheat suites, stats script, parity tool.
- **Fixture validity in CI** (Linux, no secrets, no LLM): for each fixture,
  provision → golden → seed → pre-oracle must `fail` → `reference-fix.sh`
  (and each `reference-fix-alt-*.sh`) → oracle must `pass` → for each
  `cheats/*.sh`: reset, seed, cheat → oracle must `fail`. A cheat that exits
  non-zero, or that leaves the site byte- and DB-identical to the seeded
  state, is a **gate error**, not a passing cheat — otherwise a no-op script
  "proves" the oracle rejects it. This is the gate that keeps the A/B from
  measuring noise.
- **MCP tool-contract smoke in CI**: headless server up; `initialize`;
  `tools/list` returns 13; `read_error_log` returns the seeded fatal with
  parsed `file` and `line`; `wp_cli "plugin list --skip-plugins --format=json"`
  returns JSON; `wp_cli "eval …"` is refused.
- **The Lane H half of the parity check** (§2.5) and its self-parity
  flakiness guard.
- **Realized α of the two-stage rule** (§7.4) — computed, committed with the
  suite, re-runnable in seconds.
- Secondary metrics, void/timeout/wall-cap rates, pass@turn curves, the
  monotonicity check, `fix_class` distributions, saturation flags.

### Blocked or not measurable by this design

- **The word "Local" in any conclusion**, until the Lane L half of §2.5 runs
  `equivalent`. Local is not installed here; the check needs a machine with
  Local (~1 h to install, create a site, build and install the add-on,
  restore golden). The scorecard generator enforces this (§9.3).
- **The ten open questions in §13.** Each is a fact about a real Local
  install that this document deliberately does not guess. Several gate the
  prompt freeze (§13.1, §13.2, §13.9) or a pin (§13.3, §13.5, §13.6).
- **The five environment tools** (`site_start/stop/restart/status`,
  `list_sites`). No debugging fixture needs them; Lane H stubs them. The eval
  says nothing about them.
- **The add-on's setup UX** (Enable → `.mcp.json`, `CLAUDE.md`, `.gitignore`
  written). Reproduced by the harness, not exercised.
- **Effects smaller than ≈0.24** at Stage 1, ≈0.19 at Stage 2, at α = 0.025.
  A null here is "no large effect."
- **Agent runs in CI.** Policy-blocked (cost, nondeterminism, this
  repository's standing practice), not technically blocked. Operator-run and
  archived, as the June proofs were.
- **Other agents** (Cursor, Windsurf, Copilot). Claude Code only.
- **Real-world fault distribution, delivery outcomes, developer time saved.**
  Fixtures are seeded; the population is §5's.
- **Fixture 6's "install a system cron" fix** — correct in life, invisible to
  the oracle; a pre-registered false negative.
- **Fixture 12 in Local if Local's `fastcgi_read_timeout` exceeds 75 s** — the
  symptom becomes "slow, then loads" rather than 504; the fault and fix are
  unchanged but the prompt wording would be wrong for Local. §13.5.
- **Whether a T loss is a tool *concept* failure or a tool *version* defect**
  (e.g. `findErrorLog`'s mtime heuristic, fixture 13). The design attributes
  both to the product, which is correct for the product question; transcript
  audit (§9) separates them descriptively.
- **Upstream 10up `main` vs this fork.** Auth is transparent to tool
  behavior; the eval runs the fork and says so.
- **M2 separated from the context file's tool-steering sentences.** T − C1-ctx
  measures them together; they are the same product surface and the design
  does not pretend otherwise.

## 9. Integration with the wp-meta-skills harness

### 9.1 Where things live

```
evals/suites/localwp-agent-tools-value/
  eval.yaml                     profile: tool-value-ab   ← NEW profile; §9.2
  README.md
  prereg.md                     the pre-registration (arms, criterion, independent lift table, stages, headline template)
  statistical-design.md
  statistical/simulate_two_stage_alpha.py   §7.4; committed with the suite
  arms/{T,C0,C1,C1-ctx}.yaml    mcp on/off, context variant, PATH shim on/off
  stack/                        Dockerfile (ubuntu + nginx + php8.3-fpm + mariadb + wp-cli.phar + claude CLI),
                                nginx.conf, php-fpm.conf, php.ini (parity block), my.cnf, site-layout.sh,
                                context.CLAUDE.md.tmpl (verbatim copy until prereq (b) lands), strip-tool-references.py
  parity/                       parity_check.py, parity-report.json (H self-parity in CI; lane-L/<date>/ archived)
  fixtures/<id>/
    metadata.yaml               expected_lift per contrast, predictions (independent + fixture_author), allowed_changes, tools_expected
    prompt.md                   identical bytes for all arms
    oracle.spec.yaml            the oracle's contract (spec); oracle.py implements it
    seed.sh  trigger.sh  golden/ (tar + sql, or a build script that produces them)
    oracle.py                   emits {outcome, checks, evidence}
    reference-fix.sh  reference-fix-alt-*.sh   prove the oracle can pass, by every legitimate route
    cheats/*.sh                 prove the oracle rejects: deactivate, delete feature, mask symptom, stub, hard-code, …
evals/harness/run_localwp_tool_value_eval.py   runner (reset → seed → pre-oracle → arm → prechecks → agent → post-offset → oracle → grade)
evals/harness/tool_value_stats.py              permutation test, cluster bootstrap, pass@turn, monotonicity, saturation, α re-simulation, scorecard.md (with the §9.3 gate)
evals/results/<run-id>/                        gitignored raw: runs/<fixture>/<arm>/<rep>/{transcript.jsonl(redacted), grading.json, oracle.log, site-diff.txt}
evidence/localwp-agent-tools-value/<run-id>/   committed: summary.json, scorecard.md, grading/*.json, transcripts.tar.gz, capability-manifest.json, parity/
docs/wordpress/negative-results.md             one row, whichever way it goes
```

Reuse from the existing harness: `bounded_subprocess.py` (agent and oracle
timeouts), `workspace_lease.py` (atomic run-dir lease, refuses an existing run
id — same fail-closed habit as the repair loop), `probe_wordpress_environment.py`
(capability manifest of the Lane H stack attached to every run, honoring the
runbook's "a transport is not an evidence source"), result-dir and scorecard
conventions, `validate-evidence-log.py` gating on the negative-results row.

### 9.2 Build prerequisite (a): the `tool-value-ab` validator profile

`scripts/validate-eval-suite-integrity.py` admits exactly four `eval.yaml`
profiles by **exact top-level key set** (`EVAL_PROFILE_KEYS`), validates
`fixtures` as a flat directory of regular files paired with `*.metadata.yaml`
and `rubrics/*.rubric.yaml` by stem, and returns early when a suite has no
rubric directory. This suite has directory-shaped fixtures and no rubrics, so
adding a key set is not enough. The profile needs:

1. **Key set.** `EVAL_PROFILE_KEYS["tool-value-ab"] = _fields("skill subject arms fixtures oracle lanes statistical_design")`.
   `skill` is kept (the identity check keys on it): `{name, type, description}`
   with `name == suite`, `type == "tool-value-ab"`.
2. **Section registration** so `_validate_eval_tree` accepts the shapes:
   add `subject`, `arms`, `oracle`, `lanes` to `EVAL_MAPPING_SECTIONS`;
   add `arms.contrasts`, `arms.contrasts.primary`, `arms.contrasts.co_primary`,
   `arms.contrasts.attribution`, `lanes.H`, `lanes.L`, `lanes.L.parity`,
   `statistical_design.stages`, `statistical_design.success_criterion` to
   `EVAL_MAPPING_PATHS`; add `subject.tools_in_scope`, `subject.tools_out_of_scope`,
   `arms.list`, `lanes.H.ci_gates`, `lanes.L.parity.tools` to
   `EVAL_STRING_LIST_PATHS`; add `alpha`, `delta_gte`, `p_lt`, `continue_if_delta_gt`,
   `stage_1_reps`, `stage_2_reps`, `planned_count`, `built_count`,
   `max_turns`, `wall_clock_safety_cap_minutes`, `reps` to `EVAL_NUMERIC_FIELDS`;
   add `llm_judge`, `wall_clock_binding` to `EVAL_BOOLEAN_FIELDS`.
3. **Fixtures section** keeps the frozen shape `{directory, count, pattern,
   metadata_suffix}` so `_validate_fixture_config` is untouched, with
   `pattern: "*"` and `metadata_suffix: ".yaml"` — but for this profile
   `check_suite` takes a **directory-inventory branch**: fixtures are the
   immediate subdirectories of `fixtures.directory`; `count` is their number;
   each must contain `prompt.md`, `metadata.yaml`, `oracle.spec.yaml`; if its
   `metadata.yaml` has `status: built` it must also contain `seed.sh`,
   `trigger.sh`, `oracle.py`, `reference-fix.sh`, and ≥ 1 regular file under
   `cheats/`; `status: spec_only` fixtures are counted in `count` but the
   profile also requires `fixtures`-adjacent `statistical_design.built_count`
   to equal the number of `built` fixtures, so a suite cannot claim more
   measurable fixtures than it has. No rubric directory is required; the
   early return on `rubric_directory is None` is bypassed for this profile.
4. **Metadata profile** `METADATA_PROFILE_KEYS["tool-value-fixture"]` =
   exact key set `name suite status expected_lift mechanism tools_expected_in_T golden seed trigger prompt symptom_wording haystack allowed_changes cheats_must_fail reference_fixes_must_pass predictions`.
   `name` must equal the fixture directory name (reusing the existing
   `schema_metadata_name` check). `validate_metadata`'s expectation-list rule
   (`EXPECTATION_FIELDS`) must accept `cheats_must_fail` and
   `reference_fixes_must_pass` as its substantive lists for this profile.
5. **Placeholders.** `PLACEHOLDER_MARKERS` does not include `PENDING`; this
   profile adds `PENDING` to the marker list **for `status: built` fixtures
   only**, so spec-level files may carry `PENDING_FREEZE_BEFORE_FIRST_RUN`
   and a built fixture may not.
6. **Prompt hygiene check (R7):** for this profile, each `prompt.md` is
   scanned for the forbidden tokens listed in `eval.yaml` `oracle.prompt_forbidden_tokens`
   (case-insensitive word match) and any hit is a structural issue.

The scaffold written alongside this document is shaped to pass that profile
once it exists and **fails the current validator loudly**; it is untracked on
purpose. Run against the current validator (2026-09-02) it reports exactly
nine issues for this suite: `schema_eval_profile` ("eval document must match
exactly one named profile") plus eight `schema_eval_value` issues —
`oracle.llm_judge`, `oracle.wall_clock_binding` (booleans),
`oracle.max_turns`, `oracle.wall_clock_safety_cap_minutes`,
`statistical_design.planned_count`, `statistical_design.built_count`
(numerics), `statistical_design.stages`, `statistical_design.success_criterion`
(mappings) — each of which is one registration in item 2 above. `subject`,
`arms` and `lanes` produce no issues today only because the validator does
not look inside unregistered sections; item 2 registers them so it will.

### 9.3 Finding 12: "no 'Local' without parity" as tooling

Two enforcement points, neither of which is prose:

- **`tool_value_stats.py` (scorecard generator).** `summary.json` carries a
  structured `claims[]` list (headline lines, secondary line, attribution
  line, conclusion paragraph). Before writing `scorecard.md`, the generator
  scans every `claims[].text`, the `## Headline` and `## Conclusion` sections
  for the token `\bLocal\b` (allowlist: the literal `localwp-agent-tools`).
  If any hit exists and `parity/parity-report.json` is absent, or present
  with `status != "equivalent"`, or its `fork_commit` differs from the run's,
  the generator **exits non-zero without writing the scorecard**. There is no
  override flag. Descriptive Lane L agent-run sections are exempt only when
  they sit under a heading that begins `## Lane L (descriptive` and contain
  no `Δ`, `p =`, or `CI`.
- **`scripts/validate-evidence-log.py`.** New check `_check_local_claim_backing`:
  for any `negative-results.md` row whose analysis path is under
  `evidence/localwp-agent-tools-value/` **or** whose claim cell matches
  `\bLocal\b`, the row must cite a `parity/parity-report.json` path that
  exists in the repository and parses with `status: equivalent`; otherwise
  the row is an issue. This runs in the existing CI job (`validate.yml`).

CI: one new job `localwp-tool-value-fixture-validity` on `ubuntu-latest`,
`permissions: {}`, no secrets, running the §8 validity gate, the MCP smoke,
and the Lane H self-parity for every fixture. Budget ~12 min. It never
invokes an LLM.

Archive rule (from this project's own evidence-asymmetry lesson): the runner
tars and commits the evidence bundle **before** `tool_value_stats.py` prints
the summary. Nulls get archived with the same fidelity as wins.

Transcript audit (descriptive only): after scoring, a random 10% of `pass`
cells and every `fail` cell in arm T are read by a human, tagged
`tool_helped | tool_neutral | tool_misled | tool_defect`, and the tags are
reported as counts. They do not change any score. Fixtures 11–13 are expected
to populate `tool_misled` and `tool_defect`; if they do not, that is also
reported.

## 10. Risks a reviewer should attack

Ordered by how much of the conclusion each one can take down.

- **R1 Parity is now a deterministic check, and it can still be wrong.** §2.5
  compares tool outputs, not agent behavior. Two lanes can return identical
  tool outputs while Local's setup UX, router, or shell environment change
  what an agent actually does. Until the Lane L half runs `equivalent`, no
  claim sentence may contain "Local," and §9.3 enforces it; after it runs,
  the claim is still "on a Local-shaped stack whose tool outputs match
  Local's," and the scorecard says so.
- **R2 Two headlines invite cherry-picking by the reader.** The author cannot
  choose which to lead with (§7.5), but a reader can quote one line. The
  scorecard prints both lines as a single block and the evidence-log row
  must carry both Δs.
- **R3 Fixture selection bias.** Acknowledged in §5. The population claim is
  narrow. Fixtures 7 and 10–13 bound it; they do not remove it. The
  independent author's lift table is the check on the fixture author's
  optimism, and a large disagreement between the two columns is reported.
- **R4 M3 inside T.** The context file's tool-steering sentences are
  inseparable from M2 in T − C1-ctx. The design reports them together as
  "the product surface" and does not claim otherwise. C1-ctx − C1 isolates
  only the informational part of M3.
- **R5 Power.** Thirteen fixtures, α = 0.025, MDE ≈ 0.24 at Stage 1.
  Clustering by fixture lowers effective n below §4.4's table. A null is
  "no large effect."
- **R6 Unanticipated cheats.** The oracle's no-collateral check catches file
  and DB tampering it knows to look for; the dynamic probe catches static
  markup. An agent may still satisfy every check while breaking something
  unchecked. The cheat suite grows with every audit finding; the CI gate
  reruns it.
- **R7 Prompt leakage.** A prompt containing "log", "config", "WP-CLI",
  "plugin", or the culprit's name turns the eval into instruction-following.
  The validator scans prompts for the forbidden token list (§9.2 item 6);
  prompts are frozen by hash before the first run. The quoted WordPress
  message "There has been a critical error on this website" is allowed: it
  is what a real user pastes.
- **R8 Drift across a multi-hour run.** Model or CLI version changes
  mid-stage; mitigated by interleaving and an abort-on-version-change guard,
  but a silent server-side model change is undetectable.
- **R9 `bypassPermissions` on a Bash-capable agent.** Contained in Lane H by
  the container and egress-off. In Lane L (descriptive runs only) it runs on
  a real laptop with Local; use a dedicated macOS user account or accept the
  exposure explicitly.
- **R10 Tool defects read as "no lift."** `read_error_log` prefers whichever
  of `error.log` / `debug.log` is newer; fixture 13 targets exactly that.
  That is a product defect the eval will correctly penalize — and a reviewer
  should know the primary metric cannot distinguish "the idea has no value"
  from "this build has a bug." The transcript audit tags exist for that.
- **R11 Blocked `wp eval` in T.** C1 can `wp eval`; T cannot via MCP and has
  no working `wp` in Bash. On fixtures where `eval` is the natural probe
  (#7), T is handicapped by design of the product. Report; do not correct.
- **R12 Lane H's own harness bugs.** The runner is new code. The CI validity
  gate protects the oracles; the pre-run assertions in §4.2 step 5 protect
  the arm setup. Both are required, and a precheck failure is `error`, never
  a counted cell.
- **R13 Symptom wording is stack-contingent.** Fixtures 1, 4, 11, 12, 13
  describe what a visitor sees, and that depends on `display_errors`,
  `output_buffering`, `fastcgi_read_timeout`, and whether TLS is served
  (§13). If Lane H's pins differ from Local's, the prompts describe a
  symptom a Local user would not report. The prompts are frozen only after
  §13.1/13.5/13.8/13.9 are answered.
- **R14 The `error_log` ini source changes what `read_error_log` sees in real
  life.** If Local sets `error_log` as a php-fpm `php_admin_value`,
  WordPress cannot redirect errors to `debug.log`, and the tool's
  newer-file heuristic behaves differently in Local than in a stack where
  `ini_set` works. Fixture 13 is built to be independent of this; fixture 2
  is not. §13.2 gates fixture 2's expected mechanism.

## 11. Proof-of-concept: fixture 1, fully specified

Implement this one first. It exercises `read_error_log` and `wp_cli`, has the
cleanest oracle, and is the tool's flagship use case. It is also the fixture
most likely to saturate (§7.6), which is fine: a saturated flagship is a
result.

### 11.1 Identity

- id: `fatal-undefined-function-page-scoped`
- expected lift (fixture author, **provisional**): T–C1 MEDIUM (primary);
  T–C0 HIGH (co-primary). Independent prediction: pending, required before
  freeze.
- tools expected in T: `read_error_log` (≥1), `wp_cli` (0–3), `get_site_info` (0–1)
- haystack: **7 plugins, pre-registered.** The pilot may not change this
  number (§11.8).

### 11.2 Golden site

Stock WordPress (pinned version, record), one post, one page `events` using a
page template shipped by the plugin, permalinks `/%postname%/`, timezone UTC,
`wp-config.php` with the §2.4 constant block (`WP_DEBUG`, `WP_DEBUG_LOG`,
`SCRIPT_DEBUG` all explicitly `false`, so `wp_debug_toggle` replaces in place
and a toggle round-trip leaves the file byte-identical apart from the `.bak`).
Seven plugins active, all Zivtech-authored tiny fixtures, GPL: `acme-events`
(the culprit), `acme-seo`, `acme-forms`, `acme-related`, `acme-reports`,
`acme-meta`, `acme-cache`. Each other plugin adds one harmless hook so the
haystack is real. `acme-events` registers CPT `event` with three sample
events and a shortcode/template that lists them inside
`<ul class="acme-events">…<li>…</li></ul>`, each `<li>` carrying
`<time class="acme-date">` whose text is `acme_format_date()` of the event's
`acme_event_date` meta, format `l, F j, Y`:

| Event | `acme_event_date` | Rendered `<time>` text |
|---|---|---|
| Harvest Market | 2026-10-03 | Saturday, October 3, 2026 |
| Winter Lights Walk | 2026-12-12 | Saturday, December 12, 2026 |
| Spring Repair Cafe | 2027-04-17 | Saturday, April 17, 2027 |

Snapshot: `golden/public.tar.zst` + `golden/db.sql`; digests recorded in
`metadata.yaml`.

### 11.3 Seed

`seed.sh`:

1. In `wp-content/plugins/acme-events/acme-events.php`, the golden version
   does `require_once __DIR__ . '/includes/formatting.php';` unconditionally.
   The seed replaces it with
   `if ( is_admin() ) { require_once __DIR__ . '/includes/formatting.php'; }`.
   The template `templates/events-list.php` calls `acme_format_date()` on each
   event → `PHP Fatal error: Uncaught Error: Call to undefined function
   acme_format_date() in …/templates/events-list.php on line 17`.
2. Nothing else changes. Homepage, admin, and the other six plugins are fine.

`trigger.sh`: `curl -s -o /dev/null http://<name>.local/events/` once, then
assert `logs/php/error.log` gained ≥1 line matching
`Fatal error.*acme_format_date`. Record `error.log` byte length as
`trigger_log_offset`.

### 11.4 Prompt (identical bytes in every arm; SHA-256 frozen in `metadata.yaml`)

```
Visitors are reporting that the Events page on this site (/events/) is
broken: instead of the events it shows a message saying there has been a
critical error on this website. The rest of the site seems fine. Please find
the root cause and fix it. The events listing needs to keep working — do not
just remove or disable the feature. When you're done, tell me what was wrong
and what you changed.
```

No mention of logs, plugins, PHP, WP-CLI, config, or tools. The quoted
message is WordPress's own user-facing text (§2.4). **Freeze condition:**
before the hash is recorded, render the faulted page on the Lane H stack and
confirm this is what a visitor sees (status code and whether the header
renders above the message depend on `output_buffering`, §13.9); adjust the
wording to the observation, not the other way round.

### 11.5 Oracle (`oracle.py`, exit code irrelevant; emits JSON) — the contract is `oracle.spec.yaml`

Order matters: static checks, then collateral snapshot, then the dynamic
probe, then cleanup. The oracle reads site state only; WP-CLI is invoked via
the lane's `SiteBackend`, never via the MCP server.

Symptom resolved:
- `GET /events/` → HTTP 200 (follow ≤3 redirects, final must be same host).

Functionality preserved (content, not markers — finding 4):
- Body contains `<ul class="acme-events">` with exactly three `<li>` inside it
  (regex, not HTML parse — the fixture owns the markup).
- Each of the three golden event titles appears once, and each `<li>`
  contains `<time class="acme-date">` whose text **equals** that event's
  golden formatted date string (table in §11.2). A stub that returns `''` or
  the raw `2026-10-03` fails here.
- `wp plugin is-active acme-events` → exit 0.

No collateral:
- `logs/php/error.log` has no line matching `/(Fatal error|Parse error)/`
  **after `post_agent_log_offset`** (finding 3). The oracle's own GETs are the
  only requests after that offset; fatals the agent caused while reproducing
  the bug sit before it and are counted descriptively as `fatals_during_run`.
- Changed-file set (SHA-256 vs golden, over `app/public/**` excluding
  `wp-content/uploads/**`, `*.bak`, `wp-content/debug.log`) ⊆
  `wp-content/plugins/acme-events/**`. `wp-config.php` is excluded from the
  byte comparison and checked semantically instead:
- **`wp-config.php` semantic equality (finding 5):** parse `define()`s with
  the same regex `src/tools/config.ts parseDefineConstants` uses; normalize
  `WP_DEBUG`, `WP_DEBUG_LOG`, `SCRIPT_DEBUG` so *absent ≡ false*; the
  constant map must equal golden's, **and** the file with all `define(…);`
  statements removed and whitespace collapsed must equal golden's residue
  (no code added, `$table_prefix` untouched). A T agent that toggled debug on
  to diagnose and off again passes; one that left `WP_DEBUG true` fails
  (deliberate correctness bar, stated in `metadata.yaml`).
- DB: `wp plugin list --format=json` equals golden on (name, status).
  Options diff restricted to `{cron, _transient_*, _site_transient_*}`.

Dynamic probe (after the collateral snapshot — finding 4):
- `wp post create --post_type=event --post_status=publish --post_title="Probe <nonce>" --meta_input='{"acme_event_date":"2027-03-14"}'`
  (nonce = 12 hex chars from `os.urandom`), then `GET /events/`: the body
  must contain `Probe <nonce>` inside an `<li>` whose `<time class="acme-date">`
  text is `Sunday, March 14, 2027`. Then `wp post delete <id> --force`. A
  template hard-coded with the three golden events fails here; a plugin that
  actually renders from the database passes. The probe's own option/row
  churn is excluded from the collateral diff because the snapshot precedes it.

`outcome = pass` iff all of the above; each check recorded individually.

### 11.6 Reference fixes and cheat suite (CI validity gate)

`reference-fix.sh`: restore the unconditional `require_once`. Oracle must
`pass`.

Alternative fixes that must also `pass` (add as `reference-fix-alt-*.sh`):
- `-template-require`: `require_once` `formatting.php` from the template;
- `-guard`: `if ( ! function_exists( 'acme_format_date' ) ) require …`;
- `-reimplement`: define a correct `acme_format_date()` (same `l, F j, Y`
  output) in the plugin's main file — a legitimate fix, not a cheat, and the
  reason the stub cheat below returns the wrong string rather than a right one;
- `-after-debug-toggle`: the reference fix **plus** `wp_debug_toggle` on then
  off (or `wp config set` equivalents) — proves the semantic comparison
  admits the tool's designed diagnostic path.

`cheats/` — each must make the oracle `fail`, and CI asserts it:
- `deactivate.sh`: `wp plugin deactivate acme-events` → is-active fails.
- `delete-template.sh`: remove the template so the page renders the theme
  default → 200 but no `<ul class="acme-events">`.
- `stub-function-in-theme.sh`: define `acme_format_date()` as `return '';` in
  the theme's `functions.php` → changed-file set escapes the allowed dir.
- `stub-in-plugin-dir.sh` **(new, finding 4)**: define `acme_format_date()`
  in `acme-events.php` returning the raw meta value → changed-file set is
  allowed, `<time>` present, but its text is `2026-10-03`, not the golden
  formatted string → content check fails.
- `hardcode-template.sh` **(new, finding 4)**: replace the template loop with
  static HTML of the three golden events including the correct formatted
  dates → every static check passes → the nonce probe fails.
- `comment-out-call.sh`: remove the `acme_format_date()` call from the
  template → `<time>` missing or empty → content check fails.
- `fix-but-leave-debug-on.sh`: correct fix, `WP_DEBUG true` left in place →
  semantic `wp-config.php` diff → collateral fail.
- `mask-with-debug-display-off.sh`: add `define('WP_DEBUG_DISPLAY', false)` →
  config-only change, symptom unchanged; proves a semantic diff on a
  constant outside the normalized set is still collateral.

### 11.7 Files to create for the PoC

```
evals/suites/localwp-agent-tools-value/fixtures/fatal-undefined-function-page-scoped/
  metadata.yaml   prompt.md   oracle.spec.yaml   seed.sh   trigger.sh   oracle.py
  reference-fix.sh   reference-fix-alt-{template-require,guard,reimplement,after-debug-toggle}.sh
  cheats/{deactivate,delete-template,stub-function-in-theme,stub-in-plugin-dir,hardcode-template,
          comment-out-call,fix-but-leave-debug-on,mask-with-debug-display-off}.sh
  golden/build-golden.sh        (produces public.tar.zst + db.sql on the Lane H stack)
  plugins/acme-*/               (seven tiny GPL plugins, source of truth for golden)
```

Definition of done for the PoC (no agent involved yet): the CI validity job
is green for this fixture on `ubuntu-latest` (every reference fix passes,
every cheat fails), the MCP smoke shows `read_error_log` returning the seeded
entry with `file` ending in `templates/events-list.php` and `line` = 17, the
Lane H self-parity is `equivalent`, and the prompt wording has been checked
against the rendered symptom (§11.4).

### 11.8 Pilot (findings 10 and 13)

Then, and only then: 3 arms × 5 reps of **fixture 1 only** in Lane H.
Before the pilot starts, every other fixture's `prompt.md`, `seed.sh`,
`oracle.spec.yaml` and golden digest are frozen by hash in `prereg.md`; the
pilot may not touch fixtures 2–13.

What the pilot may change on fixture 1 — **arm-symmetric only**: an oracle
bug (a check that fails a legitimate fix or passes a cheat); a seed that does
not fire (void rate > 0); prompt wording that misdescribes the symptom for
*every* arm (§11.4). What it may **not** change: haystack size (7,
pre-registered), the fault's location or difficulty, anything whose effect on
the arms is directional. "Bigger haystack" hurts C0 and is irrelevant to T;
it is exactly the tuning this rule forbids.

What the pilot reports: void rate (target ≈ 0); pass counts per arm;
saturation. If T, C1 and C0 all pass ≥ 4/5, fixture 1 is recorded as
**saturated at pilot** and enters the main run unchanged — the discriminating
fixtures are the ones built for it (11–13), not a harder version of this
one. If C0 passes 0/5, that is not evidence of a strawman by itself (the
friction is real); it is checked against the transcripts for harness faults
(shim missing, egress, prechecks) before being accepted.

## 12. What this document is not

It is not a result. It is not a harness. It is not a claim that the add-on
helps. It is a pre-registration that can be run, and — because of fixtures 7
and 10–13, the C1 primary, the C1-ctx ablation, the deterministic parity
gate, the frozen two-line headline, and the archive-before-read rule — one
that can come back and say the add-on's named tools do not measurably help
beyond WP-CLI provisioning, in which case that is what `negative-results.md`
will say, in a row that cites both Δs.

## 13. Open questions that require a real Local install

None of these is resolved by guessing. Each names what depends on it. All are
answered by reading files on a machine with Local and one running site, and
recorded in `stack/local-observations.md` with the Local version.

1. **`display_errors` in Local's per-site php.ini**
   (`run/<siteId>/conf/php/php.ini`, rendered from `<site>/conf/php/php.ini.hbs`).
   Decides whether fatals print file:line in the browser. Gates fixtures 1,
   4, 13's lift predictions and the prompt freeze. Lane H pins `Off` until
   answered and follows Local afterwards.
2. **Source of the `error_log` directive**: php.ini value, php-fpm pool
   `php_value`, or `php_admin_value`. Decides whether WordPress's
   `ini_set('error_log', …/debug.log)` takes effect in Local at all, i.e.
   whether `debug.log` is ever written by PHP errors. Gates fixture 2's
   expected mechanism and how R10 manifests in real life. Fixture 13 is
   independent of it by construction.
3. **Site-shell cwd and `--path`**: whether `ssh-entry/<siteId>.sh` `cd`s into
   `app/public`, sets `WP_CLI_CONFIG_PATH`, or otherwise gives `wp` a default
   path. Decides whether the C1 shim's `--path` mirroring over- or
   under-states a site-shell user (§4.1).
4. **Constants Local writes into a fresh `wp-config.php`**: which of
   `WP_DEBUG`, `WP_DEBUG_LOG`, `WP_DEBUG_DISPLAY`, `SCRIPT_DEBUG`,
   `WP_ENVIRONMENT_TYPE` are present and with what values. Gates the golden
   constant block (§2.4) and the parity round-trip (§2.5 steps 11–14).
5. **nginx `fastcgi_read_timeout` and `log_format`** in `<site>/conf/nginx/`.
   Gates fixture 12's symptom wording and `read_access_log` parity.
6. **MySQL/MariaDB TCP port allocation** for a site (whether a port is always
   bound alongside the socket; the default range). Gates C0 pin (iii).
7. **Bundled WP-CLI path on macOS** —
   `/Applications/Local.app/Contents/Resources/extraResources/bin/wp-cli/wp-cli.phar`
   per `paths.ts`; confirm it exists and its mode. Gates C0 pin (i).
8. **Whether Local's router serves 443 for the site** (with its self-signed
   cert) — gates fixture 11's symptom wording (certificate warning vs
   connection refused).
9. **`output_buffering`** — gates whether the theme header renders above the
   fatal-handler message (fixture 1, 4, 13 wording).
10. **Local's current default PHP version** and whether the per-site php.ini
    sets `mysqli.default_socket`. Gates the stack pin and the C0 socket
    friction story.
