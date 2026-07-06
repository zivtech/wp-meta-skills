# Deep Dive: Security Gate + Triage - 2026-07-02

Target 2 from `docs/wordpress-assist-research-plan-2026-07-02.md`. Status:
research brief, not an approved spec. Claims marked [fetched] vs
[snippet-only]; local repo facts read directly.

2026-07-06 implementation note: the static gate lane from this brief landed on
`main` via PR #2. The current follow-on branch implements Lane A consumption:
`wordpress-security-critic` must consume `security-gate.json`, review every
`suppressed_annotations[]` entry, and distinguish gate-derived evidence from
critic-derived exploitability judgment.

Thesis confirmed: the deterministic layer (WPCS security sniffs, Plugin
Check, PHPStan) has precise, enumerable holes — authorization/IDOR
correctness, escaping context-appropriateness, cross-function reachability —
and those holes are exactly what the existing `wordpress-security-critic`'s
exploitability gate argues. The build is a deterministic pre-pass that runs
the tools and hands findings JSON to the critic, so the critic spends its
budget on the holes instead of re-finding mechanical issues.

## 1. Deterministic layer inventory

**WPCS security sniffs** [fetched:
[WordPress/Sniffs/Security](https://github.com/WordPress/WordPress-Coding-Standards/tree/develop/WordPress/Sniffs/Security)]:
`WordPress.Security.EscapeOutput`, `NonceVerification`,
`ValidatedSanitizedInput`, `SafeRedirect`, `PluginMenuSlug`; DB:
`WordPress.DB.PreparedSQL`, `PreparedSQLPlaceholders`, `DirectDatabaseQuery`,
`RestrictedFunctions/Classes`, `SlowDBQuery`.

**Plugin Check** [fetched: [WordPress/plugin-check](https://github.com/WordPress/plugin-check)]:
`wp plugin check <plugin>` — security categories `late_escaping`,
`safe_redirect`, `direct_db_queries`; repo-policy checks
(`no_unfiltered_uploads`, `code_obfuscation`, `direct_file_access`,
`plugin_review_phpcs`). Mostly re-packages WPCS plus policy checks.

**PHPStan + phpstan-wordpress** [fetched:
[szepeviktor/phpstan-wordpress](https://github.com/szepeviktor/phpstan-wordpress)]:
type-level analysis, hook-callback typing; **no taint mode**. Maintainer
signals possible abandonment (sponsorship plea) — pin versions, treat as
optional.

**Psalm taint analysis** [fetched:
[psalm security docs](https://github.com/vimeo/psalm/blob/master/docs/security_analysis/index.md)]:
the only tool with multi-function source→sink flow (taint kinds `sql`,
`html`, `include`, `unserialize`, `ssrf`, `file`...). The
[humanmade/psalm-plugin-wordpress](https://github.com/humanmade/psalm-plugin-wordpress)
plugin [fetched] adds stubs but **no WordPress taint sources/sinks** —
custom taint config is a build-it-yourself cost.

**Semgrep WordPress rules** [fetched:
[semgrep-rules php/wordpress-plugins/security/audit](https://github.com/semgrep/semgrep-rules/tree/develop/php/wordpress-plugins/security/audit)]:
12 audit-tier rules (`wp-sql-injection-audit`, `wp-csrf-audit`,
`wp-authorisation-checks-audit`, `wp-ajax-no-auth-and-auth-hooks-audit`,
`wp-file-inclusion-audit`, `wp-ssrf-audit`, `wp-php-object-injection-audit`,
etc.) — intentionally high-recall/low-precision, designed to feed a reviewer:
exactly the gate→critic handoff shape.

### Coverage matrix (H=high-confidence, M=heuristic, T=taint-if-configured, —=blind)

| Vuln class | WPCS | Plugin Check | PHPStan+wp | Psalm taint | Semgrep audit | Hole → AI critic |
|---|---|---|---|---|---|---|
| XSS | H (mechanics only) | H | — | T | M | context-appropriateness, stored/second-order, DOM XSS |
| CSRF | H | via PHPCS | — | — | M | nonce present ≠ right action scope |
| SQLi | H | H | M | T | M | dynamic table/column names, suppressed sniffs, multi-hop flow |
| Broken access control / IDOR | **—** | **—** | — | — | M | **biggest hole**: is `current_user_can()` the *right* cap; object ownership |
| Auth bypass (REST `permission_callback` / `__return_true`) | — | — | — | — | M | semantic correctness of permission callbacks |
| LFI/RFI | — | — | — | T | M | reachability, sanitization adequacy |
| Unrestricted upload | — | M | — | T | M | MIME/extension validation adequacy |
| SSRF | — | — | — | T | M | allowlist reasoning |
| Object injection | — | — | — | T | M | gadget-chain plausibility |
| Priv-esc via REST/AJAX | — | — | — | — | M | trust-boundary reasoning across nopriv hooks |

## 2. Fleet triage (the CVE join)

Feed options:

| Source | Access | Cost/license | Exploitability metadata |
|---|---|---|---|
| Wordfence Intelligence | v2 feed no-auth (~117MB); v3 needs token | Free incl. commercial; MITRE attribution required | CVSS, version ranges |
| WPScan | REST per-slug | Free 25 calls/day **non-commercial only**; Enterprise for services | CVSS, PoC data |
| Patchstack API [fetched: patchstack/documentation] | `/product/{type}/{name}/{version}`, batch ≤50 | Custom paid | **Best**: `is_exploited`, `patch_priority`, `patched_in_ranges` |
| **WPVulnerability** | `https://www.wpvulnerability.com/api/plugins/{slug}` | **Free, no key, commercial-safe** | Aggregates CVE/Patchstack/WPScan/Wordfence |
| NVD | REST 2.0 | Free | Poor WP plugin CPE granularity |

**Recommendation: WPVulnerability as V1 default feed** (only no-key free
aggregator); Patchstack as the opt-in premium upgrade. MainWP's Vulnerability
Checker already joins inventory × feed [fetched:
herbie4/mainwp-check-plugins-vulnerability-extension]; **what nothing does**
is the is-this-site-actually-exploitable layer — reachability given site
config (feature disabled, endpoint firewalled, capability not granted, PHP
version gating the gadget). That reasoning is the critic's white space.

## 3. Suppression abuse (the AI-code angle)

"SQLi behind PHPCS annotations" works because `// phpcs:ignore
WordPress.DB.PreparedSQL` makes `phpcs` report clean — AI codegen readily
emits suppressions to "make the linter pass." Deterministic counters:

1. **Grep-and-flag**: any `phpcs:ignore`/`phpcs:disable`/`@phpstan-ignore`/
   baseline entry touching `WordPress.Security.*`/`WordPress.DB.Prepared*` or
   a sink (`$wpdb`, `echo`, `include`, `unserialize`) → mandatory-review
   finding.
2. **Differential run (strongest signal)**: run PHPCS normally and with
   `--ignore-annotations`; any violation appearing only in the second run is
   a suppressed security issue. Belongs in the gate as a hard fail.
3. Flag PHPStan `baseline.neon` entries in security-relevant files.

## 4. Repo fit

The current `wordpress-security-critic` SKILL (10-phase, exploitability hard
gate, fixed output headings validated by `validate_wordpress_skill_output.py`)
**already expects** PHPCS/WPCS sniff coverage as a verification surface — but
no tool produces that evidence today; the critic asserts it. Four fixtures
exist (`input-sql-output-handling-v1`, `rest-ajax-authorization-v1`,
`upload-filesystem-boundary-v1`, `smoke-wordpress-v1`) with metadata and
weighted rubrics. The certifier stack (`validate_wordpress_artifact.py`,
`certify_wordpress_executor_artifact.py`) already shells WPCS/Plugin Check
and reports `blocked` when tools are missing — the pattern to extend.

## 5. Gate design: `evals/harness/run_wordpress_security_gate.py`

Tool sequence (each skippable, `pass|fail|blocked|skip` per tool):

1. `phpcs --standard=WordPress-Extra --sniffs=WordPress.Security.*,WordPress.DB.* --report=json`
2. Suppression diff: rerun with `--ignore-annotations`, diff →
   `suppressed_annotations[]`
3. `wp plugin check <path> --format=json` (security categories)
4. `phpstan analyse --error-format=json` + baseline-entry flagging (optional)
5. `semgrep --config php/wordpress-plugins/security/audit --json` (optional
   high-recall feeder)

Output schema `wordpress-security-gate/v1`:

```json
{
  "schema": "wordpress-security-gate/v1",
  "target": "path/to/plugin", "profile": "static|runtime",
  "tools": [{"id": "phpcs-security", "status": "pass", "command": "..."}],
  "findings": [{"tool": "phpcs", "rule_id": "WordPress.DB.PreparedSQL",
                "file": "vulnerable.php", "line": 42, "severity": "error",
                "vuln_class": "sqli", "message": "...", "source_excerpt": "..."}],
  "suppressed_annotations": [{"file": "vulnerable.php", "line": 41,
                "annotation": "phpcs:ignore",
                "suppressed_rules": ["WordPress.DB.PreparedSQL"],
                "security_relevant": true,
                "reappears_without_annotations": true}],
  "summary": {"errors": 1, "warnings": 0, "suppressed_security": 1},
  "overall_status": "fail"
}
```

Split: **hard fail** = `WordPress.DB.Prepared*`/`EscapeOutput` errors, or any
security-relevant suppression that reappears without annotations. **Advisory**
= Semgrep audit hits, PHPStan warnings, Plugin Check policy notes — the
critic adjudicates. **Blocked** = tool absent (mirror existing semantics).

Critic consumption: gate JSON attached to invocation; critic (a) treats
hard-fail findings as given, spends budget on reachability/authorization;
(b) adjudicates each advisory into confirmed/false-positive with an
exploitability argument; (c) treats every suppression entry as mandatory
review; (d) adds an Evidence Provenance note distinguishing gate-derived vs
critic-derived findings.

## 6. Skill surface: two lanes, V1 = Lane A

- **Lane A (code review, V1)**: extend `wordpress-security-critic` with
  gate-evidence consumption + suppression review. The 2026-07-06 follow-on
  branch implements this as an explicit `Security Gate Evidence` and
  `Suppression Review` contract plus a focused fixture/rubric. No external
  feeds are involved.
- **Lane B (fleet triage, V2)**: new `wordpress-vulnerability-triage` skill +
  join script: inventory JSON × WPVulnerability feed → ranked patch/mitigate
  plan with per-CVE citations + reachability reasoning. Carries feed
  licensing, network nondeterminism, and cache-freshness burdens.

## 7. Fixture plan

1. **Suppression-abuse true positive** (synthetic, clean-room): interpolated
   `$wpdb` query behind `// phpcs:ignore WordPress.DB.PreparedSQL`. Gate diff
   must flag; critic must call SQLi CRITICAL and refuse the green-WPCS claim.
   (Reference oracle only, not copied: joncave's intentionally-vulnerable
   plugin gist, GPLv2+ — https://gist.github.com/joncave/5348689 [fetched].)
2. **False-positive bait**: `$wpdb->get_results($sql)` where `$sql` was
   `prepare()`d earlier and output escaped in a helper. Critic must
   adjudicate NOT exploitable — guards against trust-poisoning.
3. **Broken-access-control** (the deterministic blind spot): REST route with
   `'permission_callback' => '__return_true'` on a state-changing endpoint,
   or nonce-guarded AJAX lacking `current_user_can()`/ownership check (IDOR).
   Sniffs are silent; only the critic catches it — proves the AI layer earns
   its place.

Verified intentionally-vulnerable references for oracle use [fetched search]:
vavkamil/dvwp, ChoiSG/vwp, onhexgroup/Vulnerable-WordPress, joncave gist.
Ship original clean-room fixtures per repo reuse policy.

## 8. Effort, risks, questions

**Phases:** P1 gate static profile (PHPCS + suppression diff + schema). P2
wire gate JSON into critic contract + suppression-review step. P3 three
fixtures + rubric + output-contract clause update. P4 runtime profile
(Plugin Check + PHPStan + Semgrep). P5 (deferred) Lane B.

**Risks:** feed licensing (WPScan non-commercial cap, Patchstack paid —
default WPVulnerability); false-positive trust poisoning (keep audit-tier
advisory; fixture 2 guards); dual-use (frame as defensive review producing
reachability arguments and remediation, never PoCs/payloads; keep existing
hard gates and add explicit responsible-use framing in SKILL.md);
tool-availability (blocked-not-fail); phpstan-wordpress maintenance risk.

**Maintainer questions:**
1. Is Lane B in scope for this repo's deterministic ethos, or a separate
   networked tool? (Recommendation: V1 = Lane A only.)
2. Confirm WPVulnerability-first feed policy, paid feeds opt-in with
   maintainer keys + attribution handling (Wordfence MITRE requirement)?
3. Hard CI gate (blocks on sniff errors + suppression abuse) or
   advisory-only evidence attached to the critic?
