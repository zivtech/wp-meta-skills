#!/usr/bin/env bash
# Reproduces this session's fixture-1 end-to-end proof from scratch.
# Run from an empty scratch directory; needs Docker (OrbStack/Docker Desktop)
# and the `claude` CLI on PATH for the last (agent) step.
set -euo pipefail

HARNESS_REPO=/Users/AlexUA_1/claude/wp-meta-skills
FORK_REPO=/Users/AlexUA_1/claude/localwp-agent-tools
STACK_DIR="$HARNESS_REPO/evals/suites/localwp-agent-tools-value/stack"
FIXTURE_DIR="$HARNESS_REPO/evals/suites/localwp-agent-tools-value/fixtures/fatal-undefined-function-page-scoped"
SCRATCH="$(pwd)/lane-h"                       # any writable scratch dir
CONTAINER=lane-h-fixture1
TOKEN=lane-h-test-token-12345

mkdir -p "$SCRATCH/srv-sites"

# 1. Build the stack image (nginx + php8.3-fpm + MariaDB + wp-cli + node).
bash "$STACK_DIR/build.sh" localwp-tool-value-stack:dev

# 2. Run it: only /srv/sites is bind-mounted (not /srv/run or /srv/local-app,
#    which must stay container-internal so the image's baked-in wp-cli.phar
#    and mysql-client-not-on-PATH pins are undisturbed). Publish HTTP (8080)
#    and a placeholder MCP port (24842, reassigned to an nginx relay below).
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  -p 8080:80 -p 24842:24842 \
  -v "$SCRATCH/srv-sites:/srv/sites" \
  -v "$FORK_REPO:/opt/localwp-agent-tools-src:ro" \
  localwp-tool-value-stack:dev
sleep 3

SITE_ROOT="$SCRATCH/srv-sites/acme/app/public"
SOCK=/srv/run/acme-site/mysql/mysqld.sock
WP=/srv/local-app/extraResources/bin/wp-cli/wp-cli.phar
wpcli() { docker exec lane-h-fixture1 php -d mysqli.default_socket=$SOCK -d pdo_mysql.default_socket=$SOCK $WP --allow-root --path=/srv/sites/acme/app/public "$@"; }

# 3. Provision WordPress core + golden constants + the real acme-events
#    plugin + 6 haystack stub plugins + the Events page + 3 golden events.
docker exec lane-h-fixture1 bash -c "php -d mysqli.default_socket=$SOCK -d pdo_mysql.default_socket=$SOCK $WP core download --path=/srv/sites/acme/app/public --allow-root --version=6.8.2"
wpcli config create --dbname=local --dbuser=root --dbpass=root --dbhost=localhost --dbprefix=wp_ --skip-check --force
# Inject the golden debug/http/updater constants (see fixture metadata.yaml
# "golden.wp_config_constants") and drop wp-cli's own conditional WP_DEBUG
# block so there is exactly one definition per constant — see
# evals/harness/tool_value_oracle_lib.py for why this matters (semantic diff).
docker exec -i "$CONTAINER" python3 - <<'PY'
path = "/srv/sites/acme/app/public/wp-config.php"
text = open(path).read()
text = text.replace("if ( ! defined( 'WP_DEBUG' ) ) {\n\tdefine( 'WP_DEBUG', false );\n}\n\n", "")
block = (
    "define( 'WP_DEBUG', false );\ndefine( 'WP_DEBUG_LOG', false );\ndefine( 'SCRIPT_DEBUG', false );\n"
    "define( 'WP_ENVIRONMENT_TYPE', 'local' );\ndefine( 'WP_HTTP_BLOCK_EXTERNAL', true );\ndefine( 'AUTOMATIC_UPDATER_DISABLED', true );\n"
)
open(path, "w").write(text.replace("/* That's all, stop editing!", block + "/* That's all, stop editing!", 1))
PY
wpcli core install --url=http://127.0.0.1:8080 --title="Acme Fixture Site" --admin_user=admin --admin_password=admin --admin_email=admin@example.test --skip-email
wpcli rewrite structure '/%postname%/' --hard
wpcli rewrite flush --hard || wpcli rewrite flush

mkdir -p "$SITE_ROOT/wp-content/plugins"
cp -a "$FIXTURE_DIR/plugins/acme-events" "$SITE_ROOT/wp-content/plugins/acme-events"
for name in acme-seo acme-forms acme-related acme-reports acme-meta acme-cache; do
  mkdir -p "$SITE_ROOT/wp-content/plugins/$name"
  cat > "$SITE_ROOT/wp-content/plugins/$name/$name.php" <<PHP
<?php
/**
 * Plugin Name: $name
 * Description: Haystack stub plugin (design §5 row 1: 7 plugins total).
 */
defined( 'ABSPATH' ) || exit;
PHP
done
wpcli plugin deactivate akismet hello --quiet || true
wpcli plugin activate acme-events acme-seo acme-forms acme-related acme-reports acme-meta acme-cache
wpcli post create --post_type=page --post_title=Events --post_name=events --post_status=publish
wpcli post create --post_type=event --post_status=publish --post_title="Harvest Market" --meta_input='{"acme_event_date":"2026-10-03"}'
wpcli post create --post_type=event --post_status=publish --post_title="Winter Lights Walk" --meta_input='{"acme_event_date":"2026-12-12"}'
wpcli post create --post_type=event --post_status=publish --post_title="Spring Repair Cafe" --meta_input='{"acme_event_date":"2027-04-17"}'
wpcli option update timezone_string UTC

# 4. Snapshot golden (unfaulted) state for the oracle's comparisons.
rm -rf "$FIXTURE_DIR/golden/public"
mkdir -p "$FIXTURE_DIR/golden/public"
rsync -a --exclude 'wp-content/uploads/' "$SITE_ROOT/" "$FIXTURE_DIR/golden/public/"
cp "$SITE_ROOT/wp-config.php" "$FIXTURE_DIR/golden/wp-config.php"
wpcli plugin list --format=json --fields=name,status > "$FIXTURE_DIR/golden/plugin-list.json"

# 5. Build the fork's headless MCP server INSIDE the container (own
#    node_modules; never touches the host repo's).
docker exec "$CONTAINER" bash -c "rm -rf /opt/localwp-agent-tools && cp -r /opt/localwp-agent-tools-src /opt/localwp-agent-tools && cd /opt/localwp-agent-tools && npm install --no-audit --no-fund && npm run build"

# 6. Start it as www-data (NOT root — wp-cli refuses root without
#    --allow-root, which runWpCli() never passes) on an internal-only port,
#    then relay the published 24842 through nginx (already running in the
#    container) rewriting Host to a value the server's own Host allowlist
#    accepts (loopback host:port for the port it was CONSTRUCTED with) — a raw TCP
#    relay like socat preserves the client's Host header and fails this).
cat > /tmp/site-config.json <<JSON
{"siteId":"acme-site","sitePath":"/srv/sites/acme","wpPath":"/srv/sites/acme/app/public","phpBin":"php","phpIniDir":"/srv/run/acme-site/conf/php","wpCliBin":"$WP","mysqlBin":"/srv/local-app/lightning-services/mysql-10.11/bin/linux/bin/mysql","dbName":"local","dbUser":"root","dbPassword":"root","dbSocket":"$SOCK","dbPort":10003,"dbHost":"localhost","siteDomain":"acme.local","siteUrl":"http://127.0.0.1:8080","logPath":"/srv/sites/acme/logs"}
JSON
docker cp /tmp/site-config.json "$CONTAINER":/opt/harness/site-config.json 2>/dev/null || { docker exec "$CONTAINER" mkdir -p /opt/harness; docker cp /tmp/site-config.json "$CONTAINER":/opt/harness/site-config.json; }
docker exec -d -u www-data -i "$CONTAINER" env HEADLESS_MCP_TOKEN=$TOKEN node /opt/localwp-agent-tools/lib/headless.js --site-config /opt/harness/site-config.json --port 24843
python3 - "$CONTAINER" <<'PY'
import sys
container = sys.argv[1]
path = f"/srv/sites/acme/conf/nginx/nginx.conf"
PY
docker exec -i "$CONTAINER" python3 - <<'PY'
path = "/srv/sites/acme/conf/nginx/nginx.conf"
text = open(path).read()
marker = "        location ~ /\\.ht {\n            deny all;\n        }\n    }\n}\n"
addition = """
    server {
        listen 24842;
        server_name _;
        location / {
            proxy_pass http://127.0.0.1:24843;
            proxy_http_version 1.1;
            proxy_set_header Host "127.0.0.1:24843";
            proxy_set_header Connection "";
            proxy_buffering off;
        }
    }
}
"""
if "listen 24842" not in text:
    text = text[: -len("}\n")] + addition
    open(path, "w").write(text)
PY
docker exec "$CONTAINER" nginx -s reload

# 7. Smoke it (design item 3): tools/list == 13, wp_cli/read_error_log/get_site_info real.
python3 - <<PY
import sys; sys.path.insert(0, "$HARNESS_REPO/evals/harness")
import tool_value_parity as parity
records = parity.fetch_lane_h_records("http://127.0.0.1:24842/sites/acme-site/mcp", "$TOKEN", "acme-site")
print("tools/list count OK:", parity.assert_tools_list_count(records))
print("wp_cli plugin list sample:", str(records["wp_cli_plugin_list"].response)[:200])
PY

# 8. THE DETERMINISTIC PROOF (design item 4): fail-on-seed, pass-on-fix, fail-on-cheat.
run_oracle() {
  SITE_ROOT="$SITE_ROOT" GOLDEN_DIR="$FIXTURE_DIR/golden" SITE_BASE_URL="http://127.0.0.1:8080" \
  SITE_ERROR_LOG="$SCRATCH/srv-sites/acme/logs/php/error.log" POST_AGENT_LOG_OFFSET="$1" \
  WP_CLI_COMMAND="docker exec -i $CONTAINER php -d mysqli.default_socket=$SOCK -d pdo_mysql.default_socket=$SOCK $WP --path=/srv/sites/acme/app/public --allow-root" \
  python3 "$FIXTURE_DIR/oracle.py"
}
bash "$FIXTURE_DIR/seed.sh" "$SITE_ROOT"
run_oracle "$(wc -c < "$SCRATCH/srv-sites/acme/logs/php/error.log" | tr -d ' ')" | python3 -c "import json,sys;print('SEED ->', json.load(sys.stdin)['outcome'])"

bash "$FIXTURE_DIR/reference-fix.sh" "$SITE_ROOT"
run_oracle "$(wc -c < "$SCRATCH/srv-sites/acme/logs/php/error.log" | tr -d ' ')" | python3 -c "import json,sys;print('REFERENCE-FIX ->', json.load(sys.stdin)['outcome'])"

bash "$FIXTURE_DIR/seed.sh" "$SITE_ROOT"
bash "$FIXTURE_DIR/cheats/deactivate.sh" "/srv/sites/acme/app/public" docker exec -i "$CONTAINER" php -d mysqli.default_socket=$SOCK -d pdo_mysql.default_socket=$SOCK $WP --allow-root
run_oracle "$(wc -c < "$SCRATCH/srv-sites/acme/logs/php/error.log" | tr -d ' ')" | python3 -c "import json,sys;print('CHEAT(deactivate) ->', json.load(sys.stdin)['outcome'])"

# restore golden before the agent step
bash "$FIXTURE_DIR/reference-fix.sh" "$SITE_ROOT"
wpcli plugin activate acme-events
bash "$FIXTURE_DIR/seed.sh" "$SITE_ROOT"   # re-break it for the agent to actually fix

# 9. ONE real agent run (design item 5).
cat > "$SITE_ROOT/.mcp.json" <<JSON
{"mcpServers":{"local-wp":{"type":"http","url":"http://localhost:24842/sites/acme-site/mcp?token=$TOKEN","headers":{"Authorization":"Bearer $TOKEN"}}}}
JSON
( cd "$SITE_ROOT" && claude -p "$(cat "$FIXTURE_DIR/prompt.md")" \
    --model sonnet --max-turns 30 --permission-mode bypassPermissions \
    --output-format stream-json --verbose \
    --mcp-config "$SITE_ROOT/.mcp.json" --strict-mcp-config \
    > "$SCRATCH/agent-run-transcript.jsonl" 2> "$SCRATCH/agent-run-stderr.log" )
rm -f "$SITE_ROOT/.mcp.json"

run_oracle "$(wc -c < "$SCRATCH/srv-sites/acme/logs/php/error.log" | tr -d ' ')" | python3 -c "import json,sys;print('REAL AGENT ->', json.load(sys.stdin)['outcome'])"
