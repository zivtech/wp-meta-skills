"""Build the post-process-cleaned Plugin Check WP-CLI command."""
from __future__ import annotations

import json
from pathlib import Path

CONTENT_DIR = Path("/tmp/wp-plugin-check-content")
PLUGIN_DIR = Path("/var/www/html/wp-content/plugins")
QUARANTINE_PREFIX = ".wp-plugin-check-cleanup-"
SETUP_FAILURE_EXIT = 42
CLEANUP_FAILURE_EXIT = 43


def _php_string(value: Path | str) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def _setup_payload(content_dir: Path, plugin_dir: Path) -> str:
    content = _php_string(content_dir)
    plugins = _php_string(plugin_dir)
    return "".join((
        f"$content={content};$plugins={plugins};",
        "$source=$plugins.\"/plugin-check/drop-ins/object-cache.copy.php\";",
        "$source_ok=!is_link($source)&&is_file($source)&&",
        "is_string(hash_file(\"sha256\",$source));",
        "if(!$source_ok||file_exists($content)||is_link($content)){",
        "fwrite(STDERR,\"Plugin Check setup failed\\n\");exit(42);}",
        "$token=bin2hex(random_bytes(16));",
        "$old_umask=umask(0077);$created=@mkdir($content,0700);umask($old_umask);",
        "clearstatcache(true,$content);$identity=@lstat($content);",
        "$valid=$created&&is_array($identity)&&",
        "(($identity[\"mode\"]&0170000)===0040000)&&",
        "(($identity[\"mode\"]&0777)===0700)&&!is_link($content);",
        "if(!$valid){fwrite(STDERR,\"Plugin Check setup failed\\n\");exit(42);}",
        "echo $identity[\"dev\"].\":\".$identity[\"ino\"].\":\".$token;",
    ))


def _exec_payload(content_dir: Path, plugin_dir: Path) -> str:
    content = _php_string(content_dir)
    plugins = _php_string(plugin_dir)
    return "".join((
        f"$content={content};$plugins={plugins};",
        "if(defined(\"WP_CONTENT_DIR\")||defined(\"WP_PLUGIN_DIR\")||",
        "!define(\"WP_CONTENT_DIR\",$content)||!define(\"WP_PLUGIN_DIR\",$plugins)){",
        "fwrite(STDERR,\"Plugin Check setup failed\\n\");exit(42);}",
    ))


def _cleanup_payload(content_dir: Path, plugin_dir: Path) -> str:
    content = _php_string(content_dir)
    plugins = _php_string(plugin_dir)
    prefix = _php_string(QUARANTINE_PREFIX)
    return "".join((
        f"$content={content};$plugins={plugins};$prefix={prefix};",
        "$fail=static function():void{fwrite(STDERR,\"Plugin Check cleanup failed\\n\");",
        "exit(43);};",
        "if(!isset($argv[1])||!preg_match(\"/\\A([0-9]+):([0-9]+):([a-f0-9]{32})\\z/D\",",
        "$argv[1],$match)){$fail();}",
        "$quarantine=dirname($content).\"/\".$prefix.$match[3];",
        "if(file_exists($quarantine)||is_link($quarantine)){$fail();}",
        "clearstatcache(true,$content);$current=@lstat($content);",
        "$owned=is_array($current)&&(string)$current[\"dev\"]===$match[1]&&",
        "(string)$current[\"ino\"]===$match[2]&&",
        "(($current[\"mode\"]&0170000)===0040000)&&",
        "(($current[\"mode\"]&0777)===0700)&&!is_link($content);",
        "if(!$owned||!@rename($content,$quarantine)){$fail();}",
        "clearstatcache(true,$quarantine);$moved=@lstat($quarantine);",
        "$owned=is_array($moved)&&(string)$moved[\"dev\"]===$match[1]&&",
        "(string)$moved[\"ino\"]===$match[2]&&",
        "(($moved[\"mode\"]&0170000)===0040000)&&",
        "(($moved[\"mode\"]&0777)===0700)&&!is_link($quarantine);",
        "if(!$owned){$fail();}",
        "$source=$plugins.\"/plugin-check/drop-ins/object-cache.copy.php\";",
        "$source_hash=(!is_link($source)&&is_file($source))?",
        "hash_file(\"sha256\",$source):false;",
        "if(!is_string($source_hash)){$fail();}",
        "$target=$quarantine.\"/object-cache.php\";clearstatcache(true,$target);",
        "if(file_exists($target)||is_link($target)){",
        "$hash=(!is_link($target)&&is_file($target))?",
        "hash_file(\"sha256\",$target):false;",
        "if(!is_string($hash)||!hash_equals($source_hash,$hash)||",
        "!@unlink($target)){$fail();}}",
        "$entries=@scandir($quarantine);",
        "if($entries!==array(\".\",\"..\")||!@rmdir($quarantine)){$fail();}",
        "clearstatcache(true,$content);clearstatcache(true,$quarantine);",
        "if(file_exists($content)||is_link($content)||file_exists($quarantine)||",
        "is_link($quarantine)){$fail();}",
    ))


def _absence_payload(content_dir: Path) -> str:
    content = _php_string(content_dir)
    prefix = _php_string(QUARANTINE_PREFIX)
    return "".join((
        f"$content={content};$prefix={prefix};clearstatcache(true,$content);",
        "if(file_exists($content)||is_link($content)){exit(43);}",
        "$entries=@scandir(dirname($content));if(!is_array($entries)){exit(43);}",
        "foreach($entries as $entry){if(strncmp($entry,$prefix,strlen($prefix))===0)",
        "{exit(43);}}",
    ))


def _shell_literal(payload: str) -> str:
    if "'" in payload:
        raise RuntimeError("Plugin Check PHP payload is not shell-literal safe")
    return f"'{payload}'"


def exec_payload() -> str:
    return _exec_payload(CONTENT_DIR, PLUGIN_DIR)


def build_command(base: list[str], slug: str) -> list[str]:
    setup = _shell_literal(_setup_payload(CONTENT_DIR, PLUGIN_DIR))
    execute = _shell_literal(exec_payload())
    cleanup = _shell_literal(_cleanup_payload(CONTENT_DIR, PLUGIN_DIR))
    shell = (
        "set -u; wp plugin activate plugin-check --path=/var/www/html || exit $?; "
        f"identity=$(php -r {setup}) || exit $?; "
        "plugin_status=0; "
        f'wp plugin check "$1" --path=/var/www/html --format=json --exec={execute} '
        "--require=./wp-content/plugins/plugin-check/cli.php || plugin_status=$?; "
        "cleanup_status=0; "
        f'php -r {cleanup} -- "$identity" || cleanup_status=$?; '
        'if test "$cleanup_status" -ne 0; then printf '
        '"Plugin Check cleanup failed; primary rc=%s\\n" "$plugin_status" >&2; '
        'exit "$cleanup_status"; fi; exit "$plugin_status"'
    )
    return [*base, "exec", "-T", "cli", "sh", "-c", shell,
            "plugin-check-wrapper", slug]


def absence_command(base: list[str]) -> list[str]:
    return [
        *base, "exec", "-T", "cli", "php", "-r", _absence_payload(CONTENT_DIR),
    ]
