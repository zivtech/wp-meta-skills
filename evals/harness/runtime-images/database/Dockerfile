ARG DATABASE_BASE
FROM ${DATABASE_BASE}
COPY entrypoint.sh /usr/local/bin/wp-sandbox-db-entrypoint
RUN set -eu; \
    chmod 0555 /usr/local/bin/wp-sandbox-db-entrypoint; \
    mkdir -p /usr/local/share/wp-sandbox-db-seed /run/mysqld; \
    chown -R mysql:mysql /usr/local/share/wp-sandbox-db-seed /run/mysqld; \
    mariadb-install-db --user=mysql --datadir=/usr/local/share/wp-sandbox-db-seed --skip-test-db; \
    mariadbd --user=mysql --datadir=/usr/local/share/wp-sandbox-db-seed --socket=/run/mysqld/seed.sock --pid-file=/run/mysqld/seed.pid --skip-networking & \
    daemon_pid="$!"; \
    ready=0; for i in $(seq 1 60); do if mariadb-admin --socket=/run/mysqld/seed.sock ping; then ready=1; break; fi; sleep 1; done; \
    test "$ready" = 1; \
    printf '%s\n' 'CREATE DATABASE wordpress;' "CREATE USER 'wordpress'@'%' IDENTIFIED BY 'wordpress-canary';" "GRANT ALL ON wordpress.* TO 'wordpress'@'%';" 'FLUSH PRIVILEGES;' | mariadb --socket=/run/mysqld/seed.sock -uroot; \
    mariadb-admin --socket=/run/mysqld/seed.sock -uroot shutdown; \
    wait "$daemon_pid"; \
    rm -f /usr/local/share/wp-sandbox-db-seed/*.pid /usr/local/share/wp-sandbox-db-seed/*.sock /usr/local/share/wp-sandbox-db-seed/*.log; \
    ( cd /usr/local/share/wp-sandbox-db-seed && find . -xdev -type f -print0 | sort -z | xargs -0 -r sha256sum ) > /usr/local/share/wp-sandbox-db-seed.manifest; \
    chown mysql:mysql /usr/local/share/wp-sandbox-db-seed.manifest
USER mysql
ENTRYPOINT ["/usr/local/bin/wp-sandbox-db-entrypoint"]
