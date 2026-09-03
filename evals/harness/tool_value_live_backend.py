"""LiveSiteBackend — the SiteBackend implementation a real Lane H run uses.

Design: docs/wordpress/localwp-agent-tools-eval-design-2026-09-02.md.
Every oracle.py in evals/suites/localwp-agent-tools-value/fixtures/*/ is
written against the `tool_value_oracle_lib.SiteBackend` protocol so its
decision logic (regex extraction, semantic diffing, subset checks) can be
unit-tested with a fake backend. This module is the real implementation.

Filesystem access (read_file/hash_site_tree/mtime/error_log_*) needs no
container awareness at all: it is plain `Path` I/O against whatever
directory `site_root` points at.

HTTP and WP-CLI access needed a live Lane H stack — as of 2026-09-03 that
stack exists and this backend has been run against it for real (fixture
`fatal-undefined-function-page-scoped`: oracle fail-on-seed,
pass-on-reference-fix, fail-on-cheat, all against the actual container; see
evals/suites/localwp-agent-tools-value/README.md and this session's report).
The remaining `# SEAM(stack):` markers below describe generic HTTP-client
logic that is stack-agnostic by construction, not missing functionality.

**Architecture decision (proven, not just proposed): everything native to
one site — nginx, php-fpm, MariaDB, wp-cli, AND the fork's headless MCP
server (`node lib/headless.js`) — runs INSIDE one Docker container**
(`stack/Dockerfile`, image `localwp-tool-value-stack:dev`), because that
container already ships Node next to PHP/MariaDB (`stack/Dockerfile`'s
nodejs/npm layer) and every one of `SiteConfig`'s paths (phpBin, wpCliBin,
dbSocket, phpIniDir, logPath) is then a native, unwrapped, container-local
path — no docker-exec shimming inside the MCP server's own tool
implementations, no host/container path translation for the tools under
test. Two things run OUTSIDE the container, on the host, per the design's
own "operator-run, not CI" framing for the agent lanes:

  1. The harness (oracle.py, this module) — because `site_root` needs to be
     a real host `Path` for plain filesystem access. This works via a
     **bind mount of `/srv/sites` only** (not all of `/srv` — `/srv/run`
     and `/srv/local-app` stay container-internal so the image's baked-in
     wp-cli.phar and mysql-client-not-on-PATH pins, design C0 pins i/iii,
     are undisturbed): `docker run -v <host_dir>:/srv/sites ...`. HTTP goes
     straight from host to the container's published port (`-p 8080:80`);
     WP-CLI goes through `docker exec` (see `build_docker_lane_h_backend`
     below) because the host has no reachable path to the container's
     MariaDB unix socket (a bind-mounted socket *file* is not a live
     AF_UNIX peer across the macOS/Linux-VM boundary Docker Desktop/OrbStack
     impose) and no guaranteed-matching PHP/wp-cli version.
  2. `claude -p` itself (design §2.3: never in CI) — reaching the
     container's headless MCP server over its own published port
     (`-p 24842:24842`) via `.mcp.json`'s `http://localhost:<port>/...`
     URL, and editing site files through the SAME `/srv/sites` bind mount
     Bash/Read/Edit already need for arm T's default tool set.

This module never imports or calls anything from the fork under test — the
oracle "reads site state only" and "invokes WP-CLI via the lane's
SiteBackend, never via the MCP server" (design §11.5).
"""

from __future__ import annotations

import hashlib
import shlex
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode

HARNESS = Path(__file__).resolve().parent
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import bounded_subprocess  # noqa: E402
import tool_value_oracle_lib as lib  # noqa: E402


class LiveSiteBackend:
    """Implements tool_value_oracle_lib.SiteBackend against a real site.

    Constructed from the runner's environment contract (see each fixture's
    oracle.py `_main()` for the exact env var names): a filesystem root, a
    base URL, an error-log path, and a WP-CLI command prefix (the lane's own
    wrapper — e.g. the C1 shim's equivalent for the oracle's own use, never
    the MCP endpoint).
    """

    def __init__(
        self,
        *,
        site_root: Path,
        base_url: str,
        error_log_path: Path,
        wp_cli_command: list[str],
        default_wp_cli_timeout: float = 60.0,
    ) -> None:
        self.site_root = site_root
        self.base_url = base_url.rstrip("/")
        self.error_log_path = error_log_path
        self.wp_cli_command = wp_cli_command
        self.default_wp_cli_timeout = default_wp_cli_timeout

    # -- filesystem: real today, no live stack required ---------------------

    def read_file(self, relpath: str) -> bytes | None:
        path = self.site_root / relpath
        try:
            return path.read_bytes()
        except OSError:
            return None

    def file_exists(self, relpath: str) -> bool:
        return (self.site_root / relpath).is_file()

    def mtime(self, relpath: str) -> float | None:
        try:
            return (self.site_root / relpath).stat().st_mtime
        except OSError:
            return None

    def hash_site_tree(self) -> dict[str, str]:
        return lib.hash_tree(self.site_root)

    def resolve_wp_config(self) -> Path | None:
        """Locates wp-config.php the way real WP-CLI does (design §5 row 11):
        ABSPATH first, then one directory up. Deliberately NOT the MCP
        tool's own `path.join(wpPath, 'wp-config.php')`-only behavior."""
        return lib.find_wp_config(self.site_root)

    def error_log_length(self) -> int:
        try:
            return self.error_log_path.stat().st_size
        except OSError:
            return 0

    def error_log_tail_after(self, offset: int) -> bytes:
        try:
            with self.error_log_path.open("rb") as handle:
                handle.seek(max(offset, 0))
                return handle.read()
        except OSError:
            return b""

    # -- network + WP-CLI: need a live Lane H stack --------------------------

    def http_get(
        self, path: str, *, max_redirects: int = 3, cookies: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> lib.HttpResponse:
        # SEAM(stack): resolves against a running nginx + php-fpm + WordPress
        # site. Redirects are followed by hand (not by urllib's default
        # opener) so max_redirects and the chain are both observable.
        return self._request("GET", path, cookies=cookies, max_redirects=max_redirects, timeout=timeout)

    def http_post(
        self, path: str, *, form: dict[str, str], max_redirects: int = 0,
        cookies: dict[str, str] | None = None, timeout: float = 10.0,
    ) -> lib.HttpResponse:
        # SEAM(stack): same live-site requirement as http_get.
        return self._request(
            "POST", path, cookies=cookies, max_redirects=max_redirects, timeout=timeout,
            body=urlencode(form).encode("ascii"),
        )

    def _request(
        self, method: str, path: str, *, cookies: dict[str, str] | None, max_redirects: int,
        timeout: float, body: bytes | None = None,
    ) -> lib.HttpResponse:
        # SEAM(stack): every branch below only produces a meaningful result
        # against a real Lane H stack; the redirect-following loop itself is
        # generic HTTP client logic and is not stack-specific.
        url = f"{self.base_url}{path}"
        chain: list[str] = []
        started = time.monotonic()
        for _hop in range(max_redirects + 1):
            chain.append(url)
            request = urllib.request.Request(url, data=body, method=method)
            if cookies:
                request.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
            try:
                response = urllib.request.urlopen(request, timeout=timeout)
                status = response.status
                response_body = response.read().decode("utf-8", errors="replace")
                headers = dict(response.headers.items())
            except urllib.error.HTTPError as exc:
                status = exc.code
                response_body = exc.read().decode("utf-8", errors="replace")
                headers = dict(exc.headers.items()) if exc.headers else {}
            location = headers.get("Location")
            if location and 300 <= status < 400 and _hop < max_redirects:
                url = location if location.startswith("http") else f"{self.base_url}{location}"
                body = None
                method = "GET"
                continue
            return lib.HttpResponse(
                status=status, headers=headers, body=response_body, final_url=url,
                redirect_chain=tuple(chain), elapsed_seconds=time.monotonic() - started,
            )
        raise RuntimeError(f"exceeded max_redirects={max_redirects} fetching {path}")

    def wp_cli(self, args: str, *, timeout_seconds: float | None = None) -> lib.WpCliResult:
        # SEAM(stack): needs a real `wp` (or the lane's wrapper) plus a live
        # database. `args` is a shell-quoted argument string, matching the
        # MCP tool's own `wp_cli` calling convention (design §1) so an
        # oracle author can copy an example straight from the design doc.
        deadline = time.monotonic() + (timeout_seconds or self.default_wp_cli_timeout)
        command = [*self.wp_cli_command, *shlex.split(args)]
        try:
            completed = bounded_subprocess.run_bounded(
                command, deadline_monotonic=deadline,
                stdout_limit=10 * 1024 * 1024, stderr_limit=1024 * 1024,
                cwd=self.site_root,
            )
            return lib.WpCliResult(completed.returncode, completed.stdout, completed.stderr)
        except bounded_subprocess.BoundedProcessTimeout:
            return lib.WpCliResult(-1, "", "wp-cli call exceeded its bound", timed_out=True)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_docker_lane_h_backend(
    *,
    container: str,
    site_name: str,
    site_id: str,
    host_site_root: Path,
    base_url: str,
    php_bin: str = "php",
    wp_cli_phar: str = "/srv/local-app/extraResources/bin/wp-cli/wp-cli.phar",
    db_socket: str | None = None,
    wp_path: str | None = None,
    default_wp_cli_timeout: float = 60.0,
) -> LiveSiteBackend:
    """Builds a LiveSiteBackend for the proven "everything in one container"
    architecture (module docstring above). This is the exact recipe used to
    wire fixture 1 end to end against `localwp-tool-value-stack:dev`
    2026-09-03: `docker exec` supplies the container-native php/wp-cli.phar
    invocation (mirroring `src/tools/wpcli.ts` runWpCli()'s own
    `-d mysqli.default_socket=` / `-d pdo_mysql.default_socket=` /
    `--path=` construction, design §4.1); filesystem and HTTP access stay
    plain because `host_site_root` is the host side of a
    `-v <host_site_root's parent's parent>:/srv/sites` bind mount and
    `base_url` is the container's published HTTP port.

    `container` must already be running (`docker run -d --name <container>
    -p <http_port>:80 -p <mcp_port>:<mcp_port>
    -v <host>/srv-sites:/srv/sites localwp-tool-value-stack:dev`) with the
    site laid out by `stack/site-layout.sh <site_name> <site_id>` (the
    image's entrypoint does this for its default site automatically; a
    second or renamed site needs `site-layout.sh` run again inside the
    container first).
    """
    db_socket = db_socket or f"/srv/run/{site_id}/mysql/mysqld.sock"
    wp_path = wp_path or f"/srv/sites/{site_name}/app/public"
    wp_cli_command = [
        "docker", "exec", "-i", container,
        php_bin,
        "-d", f"mysqli.default_socket={db_socket}",
        "-d", f"pdo_mysql.default_socket={db_socket}",
        wp_cli_phar,
        "--allow-root",  # docker exec runs as the image's default user (root); matches the C1 shim's own effective privilege in Lane H, not a Local behavior
        f"--path={wp_path}",
    ]
    error_log_path = host_site_root.parent.parent / "logs" / "php" / "error.log"
    return LiveSiteBackend(
        site_root=host_site_root,
        base_url=base_url,
        error_log_path=error_log_path,
        wp_cli_command=wp_cli_command,
        default_wp_cli_timeout=default_wp_cli_timeout,
    )
