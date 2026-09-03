# Local install observations (design §13)

Status: **not started.** No machine with Local (~/Local Sites, Local.app,
or ~/Library/Application Support/Local) was available while building this
harness (design §2.1). Every row below is `OPEN` — none has been resolved
by guessing, per the design's explicit instruction.

Fill this in from a real Local install, one running site, before freezing
any fixture's prompt hash (design §11.4's freeze condition) or any pin this
table gates.

| # | Question | Gates | Status | Local version | Observed value |
|---|---|---|---|---|---|
| 13.1 | `display_errors` in Local's per-site php.ini | fixtures 1, 4, 13 prompt wording; prompt freeze | OPEN | — | — |
| 13.2 | Source of the `error_log` directive (php.ini vs php-fpm pool `php_value`/`php_admin_value`) | fixture 2's mechanism | OPEN | — | — |
| 13.3 | Site-shell cwd and `--path` behavior | C1 shim fidelity (design §4.1) | OPEN | — | — |
| 13.4 | Constants Local writes into a fresh wp-config.php | golden constant block (§2.4); parity round-trip | OPEN | — | — |
| 13.5 | nginx `fastcgi_read_timeout` and `log_format` | fixture 12 wording; `read_access_log` parity | OPEN | — | — |
| 13.6 | MySQL/MariaDB TCP port allocation per site | C0 pin (iii) | OPEN | — | — |
| 13.7 | Bundled WP-CLI path on macOS, existence + mode | C0 pin (i) | OPEN | — | — |
| 13.8 | Whether Local's router serves 443 with a self-signed cert | fixture 11 wording | OPEN | — | — |
| 13.9 | `output_buffering` | fixtures 1, 4, 13 wording | OPEN | — | — |
| 13.10 | Local's current default PHP version; per-site `mysqli.default_socket` | stack pin; C0 socket friction story | OPEN | — | — |

Lane H's current pins (this build pass, `conf/php.ini` and `conf/nginx.conf`)
are documented inline in those files with the design section they come from
and the direction Lane H follows if Local's real value differs — they are
committed, reproducible defaults, not claims about what Local does.
