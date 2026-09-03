#!/usr/bin/env bash
# Cheat: `wp plugin deactivate acme-events` (design §11.6). Must make the
# oracle FAIL: `plugin is-active acme-events` no longer exits 0, and
# `plugin list --format=json` no longer matches golden's active status.
#
# # SEAM(stack): plugin activation state lives in the site's options table,
# so this cheat needs a real `wp` (or the C1 shim) against a live database.
# It cannot change a file, so the CI validity gate's "must exit 0 and change
# something" rule (design §8) is satisfied by a DB-state diff, not a
# changed-file diff — the runner's cheat-gate check must special-case DB-only
# cheats rather than requiring a nonempty changed-file set for every cheat.
#
# Usage: deactivate.sh <wordpress-root> [wp-cli-command...]
set -euo pipefail

SITE_ROOT="${1:?usage: deactivate.sh <wordpress-root> [wp-cli-command...]}"
shift
WP_CLI=("$@")
if [ ${#WP_CLI[@]} -eq 0 ]; then
  WP_CLI=(wp)
fi

"${WP_CLI[@]}" --path="$SITE_ROOT" plugin deactivate acme-events

echo "cheated (deactivate): acme-events"
