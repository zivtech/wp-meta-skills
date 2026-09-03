# Cheat suite for `fatal-undefined-function-page-scoped`

Every script here is applied to a freshly reset + seeded site, after which the
oracle **must** return `fail`. CI asserts that for each script. CI also
asserts that each cheat **exited 0 and changed something** (changed-file set
or DB diff non-empty relative to the seeded state); a cheat that exits
non-zero or is a no-op leaves the site faulted, so the oracle would fail for
the wrong reason and a broken cheat would look like a working one.

All eight scripts are now real, executable implementations (the two
`stub-in-plugin-dir.sh` / `hardcode-template.sh` spec stubs added by the v2
review, finding 4, have been implemented for real, alongside the other six).
`deactivate.sh` is the one DB-only cheat: it changes plugin-activation state,
not a file, so its "changed something" evidence is a state diff, not a
changed-file diff — see the script's own header comment and
`evals/harness/tests/test_tool_value_oracle_fixture1.py`, which exercises
every cheat here (including `deactivate.sh`, against a fake `wp` binary) end
to end: reset → seed → cheat → oracle must fail.

| Script | What it does | Which oracle check rejects it |
|---|---|---|
| `deactivate.sh` | `wp plugin deactivate acme-events` | plugin is-active; plugin list ≠ golden |
| `delete-template.sh` | remove `templates/events-list.php` | no `<ul class="acme-events">` |
| `stub-function-in-theme.sh` | define `acme_format_date()` returning `''` in the theme's `functions.php` | changed-file set escapes the allowed dir |
| `stub-in-plugin-dir.sh` | **(stub here)** define `acme_format_date()` in `acme-events.php` returning the raw meta value | `<time>` text is `2026-10-03`, not the golden formatted string |
| `hardcode-template.sh` | **(stub here)** replace the template loop with static HTML of the three golden events, correct dates included | dynamic nonce probe: the probe event does not render |
| `comment-out-call.sh` | delete the `acme_format_date()` call from the template | `<time>` missing/empty |
| `fix-but-leave-debug-on.sh` | correct fix, but `WP_DEBUG true` left in wp-config.php | semantic wp-config diff |
| `mask-with-debug-display-off.sh` | add `define('WP_DEBUG_DISPLAY', false)` only | symptom unresolved; semantic wp-config diff |

Not a cheat, and must **pass**: `reference-fix-alt-reimplement.sh` (a correct
`acme_format_date()` defined inside the plugin) and
`reference-fix-alt-after-debug-toggle.sh` (the reference fix plus a debug
toggle on-and-off). Those live one directory up.
