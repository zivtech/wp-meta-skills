#!/usr/bin/env bash
# Cheat: "fix" the https redirect by forcing siteurl to https:// instead of
# removing FORCE_SSL_ADMIN (design §5 row 11 mechanism). Nothing serves TLS
# here, so this does not even resolve the symptom, and it is collateral on
# the options the oracle pins to golden (home/siteurl must be unchanged).
#
# Usage: option-update-siteurl-https.sh <wordpress-root> [wp-cli-command...]
set -euo pipefail

WORDPRESS_ROOT="${1:?usage: option-update-siteurl-https.sh <wordpress-root> [wp-cli-command...]}"
shift
WP_CLI=("$@")
if [ ${#WP_CLI[@]} -eq 0 ]; then
  WP_CLI=(wp)
fi

"${WP_CLI[@]}" --path="$WORDPRESS_ROOT" option update siteurl "https://acme.local"

echo "cheated (option-update-siteurl-https): siteurl set to https://"
