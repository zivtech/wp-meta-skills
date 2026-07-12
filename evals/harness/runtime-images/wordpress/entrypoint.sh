#!/bin/sh
set -eu
test "$(id -u)" != 0
mkdir -p /tmp/apache2
test -w /tmp/apache2
test -r /var/www/html/wp-config.php
exec apache2-foreground
