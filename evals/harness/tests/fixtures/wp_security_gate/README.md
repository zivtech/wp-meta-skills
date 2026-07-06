# wp_security_gate fixtures

Clean-room fixtures for the WordPress security gate static profile
(`plans/005-security-gate-static-profile.md`,
`docs/wordpress/deep-dive-security-gate-triage-2026-07-02.md`). Each is a
minimal single-file WordPress plugin. **All original Zivtech clean-room writing**
— intentionally-vulnerable references (dvwp, joncave gist, vwp) were consulted as
oracles only and are NOT copied (repo reuse policy). No exploit payloads or PoCs;
these carry only the *code pattern* a defensive sniff must react to.

| Fixture | Intent | Expected gate result |
|---|---|---|
| `suppression-abuse/` | Interpolated `$wpdb` query hidden behind `// phpcs:ignore WordPress.DB.PreparedSQL`. The suppression differential (`--ignore-annotations`) must re-surface it. | **`fail`** — reappearing security-relevant suppression (hard-fail per decision #6) |
| `prepared-escaped/` | Superficially resembles the vulnerable case but the query is inline-`prepare()`d and output is `esc_html()`d. Guards against false-positive trust-poisoning. | **`pass`** — advisory `WordPress.DB.DirectDatabaseQuery.*` findings may be present, but no enforced finding |
| `broken-access-control/` | REST route with `'permission_callback' => '__return_true'` on a state-changing `POST`. Documents the deterministic blind spot: sniffs are silent; only the critic catches it. | **`pass`** at the gate (sniff-blind), critic-owned |
| `clean-control/` | Benign plugin: nonce + capability check, prepared query, escaped output. | **`pass`** — advisory direct-query/caching findings may be present, but no enforced finding |

When PHP tooling is absent the gate returns `blocked` for all of these (honest
evidence, never a pass) — the same fail-closed semantics as the API-lint gate.

The exact phpcs sub-codes and JSON that these fixtures produce were reconciled
against a real pinned phpcs+WPCS run during Step 4/5 of plan 005. Treat the
"Expected" column as the design contract to confirm against real tool output,
not a hand-waved assertion.
