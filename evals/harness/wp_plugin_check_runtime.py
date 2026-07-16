"""Build the post-process-cleaned Plugin Check WP-CLI command."""
from __future__ import annotations

import json
from pathlib import Path

CONTENT_DIR = Path("/tmp/wp-plugin-check-content")
PLUGIN_DIR = Path("/var/www/html/wp-content/plugins")
OWNER_FILENAME = ".wp-plugin-check-owner"
QUARANTINE_PREFIX = ".wp-plugin-check-cleanup-"
PRODUCTION_DESCRIPTOR = "/proc/self/fd/9"
SETUP_FAILURE_EXIT = 42
CLEANUP_FAILURE_EXIT = 43
_SYNC_POINTS = frozenset((
    "before_rename", "after_rename", "before_unlink_object",
    "before_unlink_sentinel", "before_rmdir",
))
_SyncHook = tuple[str, Path, Path]


def _php_string(value: Path | str) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def _setup_payload(content_dir: Path, plugin_dir: Path) -> str:
    content = _php_string(content_dir)
    plugins = _php_string(plugin_dir)
    owner = _php_string(OWNER_FILENAME)
    return "".join((
        f"$content={content};$plugins={plugins};$owner=$content.\"/\".{owner};",
        "$fail=static function():void{fwrite(STDERR,\"Plugin Check setup failed\\n\");",
        "exit(42);};$source=$plugins.\"/plugin-check/drop-ins/object-cache.copy.php\";",
        "$source_ok=!is_link($source)&&is_file($source)&&",
        "is_string(hash_file(\"sha256\",$source));",
        "if(!$source_ok||file_exists($content)||is_link($content)){$fail();}",
        "$token=bin2hex(random_bytes(16));$old_umask=umask(0077);",
        "$created=@mkdir($content,0700);clearstatcache(true,$content);",
        "$initial=@lstat($content);$handle=$created?@fopen($owner,\"x\"):false;",
        "$written=is_resource($handle)?@fwrite($handle,$token):false;",
        "$flushed=is_resource($handle)&&$written===32&&@fflush($handle);",
        "$closed=is_resource($handle)?@fclose($handle):false;umask($old_umask);",
        "clearstatcache(true,$content);clearstatcache(true,$owner);",
        "$directory=@lstat($content);$sentinel=@lstat($owner);",
        "$dir_ok=is_array($initial)&&is_array($directory)&&",
        "$initial[\"dev\"]===$directory[\"dev\"]&&",
        "$initial[\"ino\"]===$directory[\"ino\"]&&",
        "$initial[\"uid\"]===$directory[\"uid\"]&&",
        "$initial[\"gid\"]===$directory[\"gid\"]&&",
        "(($directory[\"mode\"]&0170000)===0040000)&&",
        "(($directory[\"mode\"]&0777)===0700)&&!is_link($content);",
        "$file_ok=is_array($sentinel)&&(($sentinel[\"mode\"]&0170000)===0100000)&&",
        "(($sentinel[\"mode\"]&0777)===0600)&&$sentinel[\"nlink\"]===1&&",
        "!is_link($owner)&&@file_get_contents($owner)===$token;",
        "if(!$created||$written!==32||!$flushed||!$closed||!$dir_ok||!$file_ok)",
        "{$fail();}",
        "echo $directory[\"dev\"].\":\".$directory[\"ino\"].\":\".",
        "$directory[\"uid\"].\":\".$directory[\"gid\"].\":\".",
        "$sentinel[\"dev\"].\":\".$sentinel[\"ino\"].\":\".",
        "$sentinel[\"uid\"].\":\".$sentinel[\"gid\"].\":\".$token;",
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


def _identity_prelude(
    content_dir: Path, descriptor_path: str, failure_message: str,
) -> str:
    content = _php_string(content_dir)
    descriptor = _php_string(descriptor_path)
    owner = _php_string(OWNER_FILENAME)
    failure_exit = (
        SETUP_FAILURE_EXIT
        if failure_message.endswith("setup failed") else CLEANUP_FAILURE_EXIT
    )
    return "".join((
        f"$content={content};$fd={descriptor};$owner={owner};",
        f"$fail=static function():void{{fwrite(STDERR,\"{failure_message}\\n\");",
        f"exit({failure_exit});}};",
        "if(!isset($argv[1])||!preg_match(\"/\\A([0-9]+):([0-9]+):",
        "([0-9]+):([0-9]+):([0-9]+):([0-9]+):([0-9]+):([0-9]+):",
        "([a-f0-9]{32})\\z/D\",$argv[1],$match)){$fail();}",
        "$dir_ok=static fn($stat):bool=>is_array($stat)&&",
        "(string)$stat[\"dev\"]===$match[1]&&(string)$stat[\"ino\"]===$match[2]&&",
        "(string)$stat[\"uid\"]===$match[3]&&(string)$stat[\"gid\"]===$match[4]&&",
        "(($stat[\"mode\"]&0170000)===0040000)&&",
        "(($stat[\"mode\"]&0777)===0700);",
        "$owner_ok=static fn($stat):bool=>is_array($stat)&&",
        "(string)$stat[\"dev\"]===$match[5]&&(string)$stat[\"ino\"]===$match[6]&&",
        "(string)$stat[\"uid\"]===$match[7]&&(string)$stat[\"gid\"]===$match[8]&&",
        "(($stat[\"mode\"]&0170000)===0100000)&&",
        "(($stat[\"mode\"]&0777)===0600)&&$stat[\"nlink\"]===1;",
        "$same=static fn($left,$right):bool=>is_array($left)&&is_array($right)&&",
        "$left[\"dev\"]===$right[\"dev\"]&&$left[\"ino\"]===$right[\"ino\"]&&",
        "$left[\"uid\"]===$right[\"uid\"]&&$left[\"gid\"]===$right[\"gid\"]&&",
        "$left[\"mode\"]===$right[\"mode\"]&&$left[\"nlink\"]===$right[\"nlink\"];",
        "$sentinel=$fd.\"/\".$owner;$canonical=$content.\"/\".$owner;",
    ))


def _anchor_checks() -> str:
    return "".join((
        "clearstatcache(true,$content);clearstatcache(true,$fd);",
        "clearstatcache(true,$canonical);clearstatcache(true,$sentinel);",
        "$named_dir=@lstat($content);$anchored_dir=@stat($fd);",
        "$named_owner=@lstat($canonical);$anchored_owner=@lstat($sentinel);",
        "$owner_paths_ok=$owner_ok($named_owner)&&$owner_ok($anchored_owner)&&",
        "!is_link($canonical)&&!is_link($sentinel);",
        "$owner_handle=$owner_paths_ok?@fopen($sentinel,\"rb\"):false;",
        "$owner_stat=is_resource($owner_handle)?@fstat($owner_handle):false;",
        "$nonce=is_resource($owner_handle)?@stream_get_contents($owner_handle):false;",
        "$valid=$dir_ok($named_dir)&&$dir_ok($anchored_dir)&&",
        "$same($named_dir,$anchored_dir)&&!is_link($content)&&",
        "$owner_paths_ok&&",
        "$owner_ok($owner_stat)&&$same($named_owner,$anchored_owner)&&",
        "$same($anchored_owner,$owner_stat)&&$nonce===$match[9];",
    ))


def _anchor_payload(content_dir: Path, descriptor_path: str) -> str:
    return "".join((
        _identity_prelude(content_dir, descriptor_path, "Plugin Check setup failed"),
        _anchor_checks(),
        "if(is_resource($owner_handle)){@fclose($owner_handle);}",
        "if(!$valid){$fail();}",
    ))


def _sync_prelude(sync_hook: _SyncHook | None) -> str:
    if sync_hook is None:
        return ""
    point, ready_path, release_path = sync_hook
    if point not in _SYNC_POINTS:
        raise ValueError(f"Unsupported cleanup synchronization point: {point}")
    ready = _php_string(ready_path)
    release = _php_string(release_path)
    return "".join((
        f"$sync_point={_php_string(point)};$sync_ready={ready};",
        f"$sync_release={release};",
        "$sync=static function(string $point)",
        "use($sync_point,$sync_ready,$sync_release,$fail):void{",
        "if($point!==$sync_point){return;}$ready=@fopen($sync_ready,\"wb\");",
        "if(!is_resource($ready)||@fwrite($ready,$point)!==strlen($point)||",
        "!@fflush($ready)||!@fclose($ready)){$fail();}",
        "$release=@fopen($sync_release,\"rb\");",
        "if(!is_resource($release)||@fread($release,1)!==\"1\"||",
        "!@fclose($release)){$fail();}};",
    ))


def _sync_call(sync_hook: _SyncHook | None, point: str) -> str:
    return f'$sync("{point}");' if sync_hook is not None else ""


def _verified_source(plugin_dir: Path) -> str:
    plugins = _php_string(plugin_dir)
    return "".join((
        f"$plugins={plugins};$source=$plugins.",
        "\"/plugin-check/drop-ins/object-cache.copy.php\";",
        "clearstatcache(true,$source);$source_path=@lstat($source);",
        "$source_prevalid=is_array($source_path)&&",
        "(($source_path[\"mode\"]&0170000)===0100000)&&!is_link($source);",
        "$source_handle=$source_prevalid?@fopen($source,\"rb\"):false;",
        "$source_stat=is_resource($source_handle)?@fstat($source_handle):false;",
        "$source_valid=$source_prevalid&&is_array($source_stat)&&",
        "$same($source_path,$source_stat);",
        "$source_context=$source_valid?hash_init(\"sha256\"):false;",
        "$source_hashed=is_resource($source_handle)&&$source_context!==false?",
        "hash_update_stream($source_context,$source_handle):false;",
        "$source_hash=$source_hashed!==false?hash_final($source_context):false;",
        "if(!$source_valid||!is_string($source_hash)){$fail();}",
    ))


def _remove_object_cache(sync_hook: _SyncHook | None) -> str:
    return "".join((
        "$target=$fd.\"/object-cache.php\";clearstatcache(true,$target);",
        "$target_path=@lstat($target);$target_handle=false;",
        "if($target_path!==false||file_exists($target)||is_link($target)){",
        "$target_prevalid=is_array($target_path)&&",
        "(($target_path[\"mode\"]&0170000)===0100000)&&",
        "$target_path[\"nlink\"]===1&&!is_link($target);",
        "$target_handle=$target_prevalid?@fopen($target,\"rb\"):false;",
        "$target_stat=is_resource($target_handle)?@fstat($target_handle):false;",
        "$target_valid=$target_prevalid&&is_array($target_stat)&&",
        "$same($target_path,$target_stat);",
        "$target_context=$target_valid?hash_init(\"sha256\"):false;",
        "$target_hashed=is_resource($target_handle)&&$target_context!==false?",
        "hash_update_stream($target_context,$target_handle):false;",
        "$target_hash=$target_hashed!==false?hash_final($target_context):false;",
        "if(!$target_valid||!is_string($target_hash)||",
        "!hash_equals($source_hash,$target_hash)){$fail();}",
        _sync_call(sync_hook, "before_unlink_object"),
        "if(!@unlink($target)){$fail();}",
        "$unlinked=@fstat($target_handle);",
        "if(!is_array($unlinked)||$unlinked[\"nlink\"]!==0){$fail();}",
        "@fclose($target_handle);}",
    ))


def _after_rename_checks() -> str:
    return "".join((
        "clearstatcache(true,$content);",
        "clearstatcache(true,$quarantine);clearstatcache(true,$fd);",
        "clearstatcache(true,$sentinel);$moved=@lstat($quarantine);",
        "$anchor_after=@stat($fd);$owner_after=@lstat($sentinel);",
        "$handle_after=@fstat($owner_handle);",
        "$rewound_after=@rewind($owner_handle);",
        "$nonce_after=$rewound_after?@stream_get_contents($owner_handle):false;",
        "$post_valid=!file_exists($content)&&!is_link($content)&&$dir_ok($moved)&&",
        "$dir_ok($anchor_after)&&$same($moved,$anchor_after)&&",
        "$owner_ok($owner_after)&&$owner_ok($handle_after)&&",
        "$same($owner_after,$handle_after)&&!is_link($sentinel)&&",
        "$nonce_after===$match[9];if(!$post_valid){$fail();}",
    ))


def _remove_sentinel(sync_hook: _SyncHook | None) -> str:
    return "".join((
        "clearstatcache(true,$sentinel);$owner_before=@lstat($sentinel);",
        "$handle_before=@fstat($owner_handle);$rewound_before=@rewind($owner_handle);",
        "$nonce_before=$rewound_before?@stream_get_contents($owner_handle):false;",
        "if(!$owner_ok($owner_before)||!$owner_ok($handle_before)||",
        "!$same($owner_before,$handle_before)||is_link($sentinel)||",
        "$nonce_before!==$match[9]){$fail();}",
        _sync_call(sync_hook, "before_unlink_sentinel"),
        "if(!@unlink($sentinel)){$fail();}$owner_unlinked=@fstat($owner_handle);",
        "if(!is_array($owner_unlinked)||$owner_unlinked[\"nlink\"]!==0){$fail();}",
        "@fclose($owner_handle);@fclose($source_handle);",
    ))


def _remove_directory(
    require_zero_directory_links: bool, sync_hook: _SyncHook | None,
) -> str:
    link_check = (
        "if(!is_array($removed)||$removed[\"nlink\"]!==0){$fail();}"
        if require_zero_directory_links else
        "if($removed!==false){$fail();}"
    )
    return "".join((
        "$entries=@scandir($fd);if($entries!==array(\".\",\"..\")){$fail();}",
        "clearstatcache(true,$quarantine);clearstatcache(true,$fd);",
        "$named_before=@lstat($quarantine);$anchor_before=@stat($fd);",
        "if(!$dir_ok($named_before)||!$dir_ok($anchor_before)||",
        "!$same($named_before,$anchor_before)){$fail();}",
        _sync_call(sync_hook, "before_rmdir"),
        "if(!@rmdir($quarantine)){$fail();}",
        "clearstatcache(true,$fd);$removed=@stat($fd);", link_check,
        "clearstatcache(true,$content);clearstatcache(true,$quarantine);",
        "if(file_exists($content)||is_link($content)||file_exists($quarantine)||",
        "is_link($quarantine)){$fail();}",
    ))


def _cleanup_payload(
    content_dir: Path,
    plugin_dir: Path,
    descriptor_path: str = PRODUCTION_DESCRIPTOR,
    require_zero_directory_links: bool = True,
    sync_hook: _SyncHook | None = None,
) -> str:
    prefix = _php_string(QUARANTINE_PREFIX)
    direct_rebind = (
        "$fd=$quarantine;$sentinel=$fd.\"/\".$owner;"
        if not descriptor_path.startswith("/proc/self/fd/") else ""
    )
    return "".join((
        _identity_prelude(content_dir, descriptor_path, "Plugin Check cleanup failed"),
        f"$prefix={prefix};", _sync_prelude(sync_hook), _anchor_checks(),
        "if(!$valid){if(is_resource($owner_handle)){@fclose($owner_handle);}$fail();}",
        "$quarantine=dirname($content).\"/\".$prefix.$match[9];",
        "if(file_exists($quarantine)||is_link($quarantine)){$fail();}",
        _sync_call(sync_hook, "before_rename"),
        "if(!@rename($content,$quarantine)){$fail();}",
        _sync_call(sync_hook, "after_rename"), direct_rebind,
        _after_rename_checks(),
        _verified_source(plugin_dir), _remove_object_cache(sync_hook),
        _remove_sentinel(sync_hook),
        _remove_directory(require_zero_directory_links, sync_hook),
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
    anchor = _shell_literal(_anchor_payload(CONTENT_DIR, PRODUCTION_DESCRIPTOR))
    execute = _shell_literal(exec_payload())
    cleanup = _shell_literal(_cleanup_payload(CONTENT_DIR, PLUGIN_DIR))
    shell = (
        "set -u; wp plugin activate plugin-check --path=/var/www/html || exit $?; "
        f"identity=$(php -r {setup}) || exit $?; "
        f"exec 9< {CONTENT_DIR} || exit {SETUP_FAILURE_EXIT}; "
        f'php -r {anchor} -- "$identity" || '
        f'{{ anchor_status=$?; exec 9<&-; exit "$anchor_status"; }}; '
        "plugin_status=0; "
        f'wp plugin check "$1" --path=/var/www/html --format=json --exec={execute} '
        "--require=./wp-content/plugins/plugin-check/cli.php || plugin_status=$?; "
        "cleanup_status=0; "
        f'php -r {cleanup} -- "$identity" || cleanup_status=$?; '
        "exec 9<&-; "
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
