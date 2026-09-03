#!/usr/bin/env bash
# Lays out one site's directory tree exactly per design §2.4:
#
#   /srv/sites/<name>/{app/public, logs/php, logs/nginx, conf}
#   /srv/run/<siteId>/mysql
#   /srv/run/<siteId>/conf/php   (PHPRC dir)
#
# Renders the stack's templated conf files (nginx.conf, php.ini,
# php-fpm-pool.conf, my.cnf — all under /opt/stack-templates/ in the image)
# with SITE_NAME/SITE_ID substituted, and installs the bundled wp-cli.phar
# and a not-on-PATH mysql client copy at the Local-shaped paths paths.ts
# looks for (findWpCli() candidate 1; findMysqlBinary()).
#
# Usage: site-layout.sh <site-name> <site-id>
set -euo pipefail

SITE_NAME="${1:?usage: site-layout.sh <site-name> <site-id>}"
SITE_ID="${2:?usage: site-layout.sh <site-name> <site-id>}"
TEMPLATES_DIR="${STACK_TEMPLATES_DIR:-/opt/stack-templates}"

SITE_DIR="/srv/sites/$SITE_NAME"
RUN_DIR="/srv/run/$SITE_ID"

mkdir -p "$SITE_DIR/app/public" "$SITE_DIR/logs/php" "$SITE_DIR/logs/nginx" "$SITE_DIR/conf/nginx" "$SITE_DIR/conf/php" "$SITE_DIR/conf/mysql"
mkdir -p "$RUN_DIR/mysql/data" "$RUN_DIR/conf/php"

render() {
  local template="$1" target="$2"
  sed -e "s/SITE_NAME/$SITE_NAME/g" -e "s/SITE_ID/$SITE_ID/g" "$TEMPLATES_DIR/$template" > "$target"
}

render nginx.conf "$SITE_DIR/conf/nginx/nginx.conf"
render php.ini "$RUN_DIR/conf/php/php.ini"
render php-fpm-pool.conf "$SITE_DIR/conf/php/php-fpm-pool.conf"
render my.cnf "$SITE_DIR/conf/mysql/my.cnf"

# Bundled wp-cli.phar: on disk, mode 0644, NOT on PATH (paths.ts findWpCli
# candidate 1). C0 can `find / -name wp-cli.phar` exactly as a Local user
# could (design C0 pin i).
mkdir -p /srv/local-app/extraResources/bin/wp-cli
if [ ! -f /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar ]; then
  echo "site-layout.sh: /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar is missing (should be baked into the image)" >&2
  exit 1
fi
chmod 0644 /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar

# Not-on-PATH mysql client copy at the Local-shaped lightning-services path
# (design C0 pin iii; paths.ts findMysqlBinary()).
mkdir -p /srv/local-app/lightning-services/mysql-10.11/bin/linux/bin
if [ ! -f /srv/local-app/lightning-services/mysql-10.11/bin/linux/bin/mysql ]; then
  cp "$(command -v mysql)" /srv/local-app/lightning-services/mysql-10.11/bin/linux/bin/mysql
fi

echo "site-layout.sh: laid out $SITE_NAME ($SITE_ID)"
