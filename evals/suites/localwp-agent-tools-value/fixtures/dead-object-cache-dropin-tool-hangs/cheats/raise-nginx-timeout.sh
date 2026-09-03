#!/usr/bin/env bash
# Cheat: raise nginx's fastcgi_read_timeout so the drop-in's 75s backoff no
# longer trips a 504 (design §5 row 12). Must make the oracle FAIL twice
# over: conf/** is no longer byte-identical to golden (conf_tree_unchanged),
# and the symptom is not resolved anyway — TTFB is still ~75s, only the
# status code changes from 504 to a very slow 200.
#
# Usage: raise-nginx-timeout.sh <site-root>
#   <site-root> is the Local-shaped site root whose conf/nginx/nginx.conf
#   holds fastcgi_read_timeout (design §2.4) — NOT the WordPress root.
set -euo pipefail

SITE_ROOT="${1:?usage: raise-nginx-timeout.sh <site-root>}"
NGINX_CONF="$SITE_ROOT/conf/nginx/nginx.conf"

if [ ! -f "$NGINX_CONF" ]; then
  echo "raise-nginx-timeout.sh: $NGINX_CONF not found" >&2
  exit 1
fi

perl -pi -e "s/fastcgi_read_timeout 60s;/fastcgi_read_timeout 120s;/" "$NGINX_CONF"

grep -qF "fastcgi_read_timeout 120s;" "$NGINX_CONF"
echo "cheated (raise-nginx-timeout): $NGINX_CONF"
