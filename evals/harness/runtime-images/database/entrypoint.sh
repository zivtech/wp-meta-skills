#!/bin/sh
set -eu
test "$(id -u)" != 0
test -d /var/lib/mysql
test -z "$(find /var/lib/mysql -mindepth 1 -print -quit)"
cp -a /usr/local/share/wp-sandbox-db-seed/. /var/lib/mysql/
test -z "$(find /var/lib/mysql \( -type l -o -type b -o -type c -o -type p -o -type s \) -print -quit)"
( cd /var/lib/mysql && sha256sum -c /usr/local/share/wp-sandbox-db-seed.manifest )
test "$(find /var/lib/mysql ! -user mysql -print -quit)" = ""
exec mariadbd --datadir=/var/lib/mysql --socket=/run/mysqld/mysqld.sock --pid-file=/run/mysqld/mysqld.pid --tmpdir=/tmp --innodb-log-file-size=16M --log-error=/dev/stderr
