#!/usr/bin/env bash
# Lane H container entrypoint: lays out a default site, starts MariaDB,
# php8.3-fpm, and nginx as foreground-supervised background services, then
# execs the container's CMD (default: sleep, so `docker run -it` and
# `docker exec` both work for manual poking and CI's fixture-validity job).
#
# This is deliberately NOT a production init system — one shot, one site,
# meant for the harness's runner (evals/harness/run_localwp_tool_value_eval.py)
# or CI to reset/seed/probe against, matching design §2's "one Docker
# container on macOS" framing.
set -euo pipefail

SITE_NAME="${SITE_NAME:-acme}"
SITE_ID="${SITE_ID:-acme-site}"

/opt/stack-templates/site-layout.sh "$SITE_NAME" "$SITE_ID"

# --- MariaDB -----------------------------------------------------------------
RUN_DIR="/srv/run/$SITE_ID"
chown -R mysql:mysql "$RUN_DIR/mysql"
if [ ! -d "$RUN_DIR/mysql/data/mysql" ]; then
  mariadb-install-db --datadir="$RUN_DIR/mysql/data" --auth-root-authentication-method=normal \
    --user=mysql >/tmp/mariadb-install.log 2>&1
  chown -R mysql:mysql "$RUN_DIR/mysql"
fi
mariadbd --defaults-file="/srv/sites/$SITE_NAME/conf/mysql/my.cnf" --user=mysql &
MARIADB_PID=$!

for _ in $(seq 1 30); do
  if mysqladmin --socket="$RUN_DIR/mysql/mysqld.sock" ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
mysql --socket="$RUN_DIR/mysql/mysqld.sock" -u root -e \
  "CREATE DATABASE IF NOT EXISTS local; CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY 'root'; GRANT ALL ON *.* TO 'root'@'127.0.0.1'; SET PASSWORD FOR 'root'@'localhost' = PASSWORD('root'); FLUSH PRIVILEGES;" \
  || echo "entrypoint.sh: initial DB bootstrap step failed (non-fatal for image build verification)" >&2

# --- php-fpm -------------------------------------------------------------------
mkdir -p /run/php
php-fpm8.3 --fpm-config <(cat /etc/php/8.3/fpm/php-fpm.conf; echo "include=/srv/sites/$SITE_NAME/conf/php/php-fpm-pool.conf") \
  -c "$RUN_DIR/conf/php/php.ini" --nodaemonize &
PHP_FPM_PID=$!

# --- nginx -----------------------------------------------------------------------
ln -sf "/srv/sites/$SITE_NAME/conf/nginx/nginx.conf" /etc/nginx/nginx.conf
nginx -g 'daemon off;' &
NGINX_PID=$!

echo "entrypoint.sh: site=$SITE_NAME id=$SITE_ID mariadb=$MARIADB_PID php-fpm=$PHP_FPM_PID nginx=$NGINX_PID"

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec sleep infinity
