ARG WORDPRESS_BASE
ARG CLI_BASE
ARG WP_CLI_SHA256
FROM ${CLI_BASE} AS cli
FROM ${WORDPRESS_BASE}
COPY wordpress.tar.gz /tmp/wordpress.tar.gz
RUN rm -rf /var/www/html/* /usr/src/wordpress \
 && tar -xzf /tmp/wordpress.tar.gz --strip-components=1 -C /var/www/html \
 && rm /tmp/wordpress.tar.gz \
 && mkdir -p /var/www/html/wp-content/uploads \
 && chown -R www-data:www-data /var/www/html \
 && sed -ri 's!Listen 80!Listen 8080!' /etc/apache2/ports.conf \
 && sed -ri 's!:80>!:8080>!' /etc/apache2/sites-enabled/000-default.conf \
 && sed -ri 's!^export APACHE_RUN_DIR=.*!export APACHE_RUN_DIR=/tmp/apache2!; s!^export APACHE_LOCK_DIR=.*!export APACHE_LOCK_DIR=/tmp/apache2!; s!^export APACHE_LOG_DIR=.*!export APACHE_LOG_DIR=/tmp/apache2!' /etc/apache2/envvars \
 && printf 'ServerName localhost\nPidFile /tmp/apache2/apache2.pid\nMutex file:/tmp/apache2 default\nErrorLog /proc/self/fd/2\nCustomLog /proc/self/fd/1 combined\n' > /etc/apache2/conf-enabled/sandbox.conf \
 && printf '%s\n' '<?php' "define( 'DB_NAME', 'wordpress' );" "define( 'DB_USER', 'wordpress' );" "define( 'DB_PASSWORD', 'wordpress-canary' );" "define( 'DB_HOST', 'database:3306' );" "define( 'DB_CHARSET', 'utf8mb4' );" "define( 'DB_COLLATE', '' );" "define( 'AUTH_KEY', 'test-only-auth-key' );" "define( 'SECURE_AUTH_KEY', 'test-only-secure-auth-key' );" "define( 'LOGGED_IN_KEY', 'test-only-logged-in-key' );" "define( 'NONCE_KEY', 'test-only-nonce-key' );" '$table_prefix = '\''wp_'\'';' "define( 'WP_DEBUG', true );" "define( 'WP_DEBUG_LOG', '/tmp/wordpress-debug.log' );" "define( 'DISALLOW_FILE_MODS', true );" "if ( ! defined( 'ABSPATH' ) ) { define( 'ABSPATH', __DIR__ . '/' ); }" "require_once ABSPATH . 'wp-settings.php';" > /var/www/html/wp-config.php
COPY --from=cli /usr/local/bin/wp /usr/local/bin/wp
COPY entrypoint.sh /usr/local/bin/wp-sandbox-entrypoint
RUN chmod 0555 /usr/local/bin/wp /usr/local/bin/wp-sandbox-entrypoint \
 && test -f /usr/local/bin/wp && ! test -L /usr/local/bin/wp \
 && echo "$WP_CLI_SHA256  /usr/local/bin/wp" | sha256sum -c - \
 && wp --allow-root --info && wp --allow-root cli version
USER www-data
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/wp-sandbox-entrypoint"]
