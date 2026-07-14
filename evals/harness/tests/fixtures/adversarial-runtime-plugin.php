<?php
/** Plugin Name: Safe */
define('WP_RUNTIME_ADVERSARIAL_PLUGIN', 'generated-php-canary');
function wp_runtime_adversarial_php_canary(array $targets, int $port): string {
    foreach ($targets as $host) {
        $socket = @fsockopen($host, $port, $errno, $message, 1);
        if ($socket) { fclose($socket); return 'gateway-reachable'; }
    }
    return WP_RUNTIME_ADVERSARIAL_PLUGIN;
}
function wp_runtime_adversarial_route_canary(): string {
    foreach (array(array('127.0.0.1',8080),array('10.0.0.1',80),array('169.254.169.254',80),array('93.184.216.34',80)) as $target) {
        $socket=@fsockopen($target[0],$target[1],$errno,$message,1); if ($socket) { fclose($socket); return 'route-reachable'; }
    } if (dns_get_record('example.com')) return 'dns-reachable'; return 'generated-route-canary';
}
function wp_runtime_adversarial_memory(): void {
    ini_set('memory_limit', '-1'); $items = array();
    while (true) { $items[] = str_repeat('x', 8 * 1024 * 1024); }
}
function wp_runtime_adversarial_cpu(): void { while (true) {} }
function wp_runtime_adversarial_fd(): bool {
    $items = array(); for ($i = 0; $i < 2048; $i++) {
        $handle = @fopen('/dev/null', 'r'); if (false === $handle) return true;
        $items[] = $handle;
    } return false;
}
function wp_runtime_adversarial_process(): bool {
    $items = array(); $failed = false;
    for ($i = 0; $i < 256; $i++) {
        $pipes = array(); $process = @proc_open(array('/bin/sleep','2'), array(array('pipe','r'),array('pipe','w'),array('pipe','w')), $pipes);
        if (!is_resource($process)) { $failed = true; break; }
        foreach ($pipes as $pipe) fclose($pipe); $items[] = $process;
    } foreach ($items as $process) { @proc_terminate($process, 9); @proc_close($process); }
    return $failed;
}
function wp_runtime_adversarial_output(string $stream): void {
    $payload = str_repeat('x', 65536); if ('stdout' === $stream) echo $payload; else fwrite(STDERR, $payload);
}
function wp_runtime_adversarial_storage(string $root, string $kind): bool {
    $dir = $root . '/.wp-runtime-generated'; @mkdir($dir); $failed = false;
    if ('bytes' === $kind) { $payload = str_repeat('x', 1024 * 1024); for ($i=0; $i<256; $i++) { if (false === @file_put_contents($dir . '/' . $i, $payload)) { $failed=true; break; } } }
    else { for ($i=0; $i<20000; $i++) { if (false === @touch($dir . '/' . $i)) { $failed=true; break; } } }
    foreach ((array) @scandir($dir) as $name) { if ('.' !== $name && '..' !== $name) @unlink($dir . '/' . $name); }
    $recovered = false !== @file_put_contents($dir . '/recovered', 'ok'); @unlink($dir . '/recovered'); @rmdir($dir);
    return $failed && $recovered;
}
function wp_runtime_adversarial_database(): array {
    mysqli_report(MYSQLI_REPORT_OFF); $db = @new mysqli(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME);
    if ($db->connect_errno) return array('created'=>false,'error'=>$db->connect_error);
    $db->query('DROP TABLE IF EXISTS wp_sandbox_quota');
    if (false === $db->query("CREATE TABLE wp_sandbox_quota(payload LONGBLOB) ENGINE=MyISAM")) return array('created'=>false,'error'=>$db->error);
    $inserted = 0;
    for (; $inserted < 4; $inserted++) { if (false === $db->query("INSERT INTO wp_sandbox_quota VALUES (REPEAT('x', 1048576))")) break; }
    $quota_inserts = 0; $failed = false;
    for (; $quota_inserts < 16; $quota_inserts++) { if (false === $db->query("SET STATEMENT max_statement_time=5 FOR INSERT INTO wp_sandbox_quota VALUES (REPEAT('x', 8388608))")) { $failed = true; break; } }
    $error = $db->error; $db->query('DROP TABLE IF EXISTS wp_sandbox_quota');
    $result = $db->query('SELECT 1'); $recovered = $result instanceof mysqli_result; if ($recovered) $result->free(); $db->close();
    return array('created'=>true,'inserted'=>$inserted,'quota_inserts'=>$quota_inserts,'failed'=>$failed,'error'=>$error,'recovered'=>$recovered);
}
function wp_runtime_adversarial_rest(): void {
    register_rest_route('wp-runtime-canary/v1', '/output', array('methods'=>'GET','permission_callback'=>'__return_true','callback'=>static function (): WP_REST_Response { return new WP_REST_Response(str_repeat('x', 65536)); }));
}
add_action('rest_api_init', 'wp_runtime_adversarial_rest');
function wp_runtime_adversarial_enqueue(): void {
    wp_enqueue_script('wp-runtime-adversarial', plugins_url('wp-runtime-adversarial.js', __FILE__), array(), '1', true);
}
add_action('wp_enqueue_scripts', 'wp_runtime_adversarial_enqueue');
add_action('admin_enqueue_scripts', 'wp_runtime_adversarial_enqueue');
