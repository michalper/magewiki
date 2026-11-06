<?php

declare(strict_types=1);

// Internal-only HTTP wrapper around PHPStan/PHPMD/phpcs/Rector — never
// reachable outside the docker network, called only by the trusted Python
// backend. Still validates module_path and uses array-form proc_open()
// (which execve()s directly, no shell involved) rather than building a
// shell command string, so there's no injection surface even in principle.

header('Content-Type: application/json');

$requestPath = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
$rawBody = file_get_contents('php://input');
$body = json_decode($rawBody !== false && $rawBody !== '' ? $rawBody : '{}', true);
$modulePath = is_array($body) ? ($body['module_path'] ?? null) : null;

if (!is_string($modulePath) || $modulePath === '' || !is_dir($modulePath)) {
    http_response_code(400);
    echo json_encode(['error' => 'module_path must be an existing directory']);
    exit;
}

// No further prefix restriction beyond is_dir() above: the container's own
// read-only bind mounts (set in docker-compose.yml/k8s, not here) are
// already the real access boundary — module_path can only ever resolve to
// something that was deliberately mounted into this container, whatever
// its host-side path happens to be (the fixture paths are env-var-driven
// and not knowable as a fixed prefix from inside this script).
$realModulePath = realpath($modulePath);
if ($realModulePath === false) {
    http_response_code(400);
    echo json_encode(['error' => 'module_path could not be resolved']);
    exit;
}

function run_command(array $command): array
{
    $descriptors = [1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
    $process = proc_open($command, $descriptors, $pipes);
    if (!is_resource($process)) {
        return ['stdout' => '', 'exit_code' => -1];
    }
    $stdout = stream_get_contents($pipes[1]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    proc_close($process);
    return ['stdout' => $stdout === false ? '' : $stdout];
}

// PHP's default 128M memory_limit is nowhere near enough for a real module
// (confirmed empirically: PHPStan crashed silently — empty stdout, exit 255
// — analysing the real 828-class Ordo_Automation module). Run every tool as
// `php -d memory_limit=-1 <binary>` rather than invoking vendor/bin/* via
// its own shebang, so the override applies uniformly to all four.
function with_memory_limit(string $binary): array
{
    return ['php', '-d', 'memory_limit=-1', $binary];
}

function run_phpstan(string $root, string $modulePath): array
{
    $result = run_command([
        ...with_memory_limit($root . '/vendor/bin/phpstan'),
        'analyse', '--error-format=json', '--no-progress', '--configuration=' . $root . '/phpstan.neon', $modulePath,
    ]);
    $data = json_decode($result['stdout'], true);
    $findings = [];
    foreach (($data['files'] ?? []) as $file => $info) {
        foreach (($info['messages'] ?? []) as $message) {
            $findings[] = ['file' => $file, 'line' => $message['line'] ?? null, 'message' => $message['message'] ?? ''];
        }
    }
    return $findings;
}

function run_phpmd(string $root, string $modulePath): array
{
    $result = run_command([
        ...with_memory_limit($root . '/vendor/bin/phpmd'), $modulePath, 'json', 'codesize,unusedcode,design',
        '--exclude', 'vendor/*',
    ]);
    $data = json_decode($result['stdout'], true);
    $findings = [];
    foreach (($data['files'] ?? []) as $fileEntry) {
        $file = $fileEntry['file'] ?? '';
        foreach (($fileEntry['violations'] ?? []) as $violation) {
            $findings[] = [
                'file' => $file,
                'line' => $violation['beginLine'] ?? null,
                'message' => $violation['description'] ?? '',
            ];
        }
    }
    return $findings;
}

function run_phpcs(string $root, string $modulePath): array
{
    // phpcs writes deprecation/CSS-sniff-registration noise to stdout ahead
    // of the JSON report itself, which silently corrupts a stdout-based
    // parse (json_decode on the mixed text returns null, and "?? []"
    // swallows that into an empty, wrongly-"clean" result) — write the
    // report to its own file instead.
    $reportFile = tempnam(sys_get_temp_dir(), 'phpcs_');
    run_command([
        ...with_memory_limit($root . '/vendor/bin/phpcs'), '--standard=Magento2', '--report=json',
        '--report-file=' . $reportFile, '--extensions=php', '--ignore=*/vendor/*', $modulePath,
    ]);
    $data = json_decode((string) file_get_contents($reportFile), true);
    unlink($reportFile);
    $findings = [];
    foreach (($data['files'] ?? []) as $file => $info) {
        foreach (($info['messages'] ?? []) as $message) {
            $findings[] = [
                'file' => $file,
                'line' => $message['line'] ?? null,
                'message' => trim(($message['source'] ?? '') . ': ' . ($message['message'] ?? '')),
            ];
        }
    }
    return $findings;
}

function run_rector(string $root, string $modulePath): array
{
    $result = run_command([
        ...with_memory_limit($root . '/vendor/bin/rector'), 'process', $modulePath, '--dry-run',
        '--output-format=json', '--config=' . $root . '/rector.php', '--no-progress-bar',
    ]);
    $data = json_decode($result['stdout'], true);
    $findings = [];
    foreach (($data['file_diffs'] ?? []) as $diff) {
        $rules = implode(', ', $diff['applied_rectors'] ?? []);
        $findings[] = [
            'file' => $diff['file'] ?? '',
            'line' => null,
            'message' => 'Rector would apply: ' . ($rules !== '' ? $rules : 'unknown rule'),
        ];
    }
    return $findings;
}

$analyzerRoot = dirname(__DIR__);

$tools = [
    '/phpstan' => 'run_phpstan',
    '/phpmd' => 'run_phpmd',
    '/phpcs' => 'run_phpcs',
    '/rector' => 'run_rector',
];

if (!isset($tools[$requestPath])) {
    http_response_code(404);
    echo json_encode(['error' => 'unknown tool: ' . $requestPath]);
    exit;
}

$findings = ($tools[$requestPath])($analyzerRoot, $realModulePath);
echo json_encode(['findings' => $findings]);
