# Lane H stack image (design §2.2 (b-native), §2.4).
#
# A native nginx + php8.3-fpm + MariaDB stack laid out exactly like a Local
# site — SiteConfig maps 1:1 with no wrappers, because the localwp-agent-
# tools fork's own code (mcp-server.ts, src/tools/*) imports nothing from
# @getflywheel/local and only cares about a directory layout and a set of
# binaries (design §1). Ubuntu 24.04 ("noble") ships PHP 8.3 as its default
# `php` package, matching the design's PHP 8.3.x pin without a third-party
# PPA.
#
# Build:  docker build -t localwp-tool-value-stack:dev -f Dockerfile .
# Run:    docker run --rm -it -p 8080:80 localwp-tool-value-stack:dev
# Smoke:  curl http://127.0.0.1:8080/  (serves whatever is in app/public/;
#         empty until a fixture's golden/ is materialized into the site)
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    php8.3-fpm php8.3-cli php8.3-mysql php8.3-curl php8.3-mbstring \
    php8.3-xml php8.3-zip php8.3-gd php8.3-bcmath php8.3-intl \
    mariadb-server mariadb-client \
    curl ca-certificates perl python3 less unzip \
    && rm -rf /var/lib/apt/lists/*

# wp-cli.phar at the Local-shaped bundled path (design §2.4), NOT on PATH.
# Pinned by digest at build time would be ideal; pinned by an explicit
# version tag here so the image is reproducible without a floating
# "latest" — bump deliberately, record the new sha256 in
# local-observations.md when you do.
ARG WP_CLI_VERSION=2.11.0
ARG WP_CLI_SHA256=""
RUN mkdir -p /srv/local-app/extraResources/bin/wp-cli && \
    curl -fsSL -o /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar \
      "https://github.com/wp-cli/wp-cli/releases/download/v${WP_CLI_VERSION}/wp-cli-${WP_CLI_VERSION}.phar" && \
    if [ -n "$WP_CLI_SHA256" ]; then \
      echo "${WP_CLI_SHA256}  /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar" | sha256sum -c -; \
    fi && \
    chmod 0644 /srv/local-app/extraResources/bin/wp-cli/wp-cli.phar

# Node.js (for the fork's headless MCP entrypoint) — LTS via NodeSource
# would be one more external dependency; Ubuntu 24.04's own nodejs package
# is new enough (18.x/20.x depending on point release) for the fork's needs.
# # SEAM(headless-entrypoint): the runner is expected to `npm install` and
# `npm run build` the fork (or COPY a prebuilt lib/) into this image and
# invoke `node lib/headless.js` — neither step is wired up here, since the
# fork lives in a sibling repository (/Users/AlexUA_1/claude/localwp-agent-tools)
# not inside this one, and baking a specific commit into this Dockerfile is
# a decision for whoever owns the build pipeline, not this scaffold.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY conf/nginx.conf /opt/stack-templates/nginx.conf
COPY conf/php.ini /opt/stack-templates/php.ini
COPY conf/php-fpm-pool.conf /opt/stack-templates/php-fpm-pool.conf
COPY conf/my.cnf /opt/stack-templates/my.cnf
COPY site-layout.sh /opt/stack-templates/site-layout.sh
COPY entrypoint.sh /opt/stack-templates/entrypoint.sh
RUN chmod +x /opt/stack-templates/site-layout.sh /opt/stack-templates/entrypoint.sh

# Not-on-PATH mysql client copy (design C0 pin iii) is created by
# site-layout.sh at container start, once `mysql` is confirmed installed —
# doing it at build time would bake in a path that differs if the apt
# package's binary location changes across base-image updates.

EXPOSE 80

ENTRYPOINT ["/opt/stack-templates/entrypoint.sh"]
