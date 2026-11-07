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
    // tempnam() returns false (not an exception) if it can't create the file
    // — e.g. a full/unwritable temp dir — which previously reached
    // file_get_contents(false) as an uncaught TypeError, a 500 the Python
    // client already tolerates (fails open to "no phpcs findings"), but
    // worth not crashing on: fail open explicitly instead, same as every
    // other tool here when its own report can't be parsed.
    if ($reportFile === false) {
        return [];
    }
    // A module's own phpcs.xml.dist/phpcs.xml (if it ships one) wins over the
    // bare Magento2 ruleset — confirmed against a real case: a module can
    // deliberately exclude specific rule families as a documented style
    // decision (e.g. typed native PHP signatures instead of exhaustive
    // docblocks), and its own CI respects that; re-flagging those same rules
    // here produced findings the module's own maintainers already decided
    // aren't real problems, not genuine noise in MageWiki's own config this
    // time.
    $ownRuleset = null;
    foreach (['phpcs.xml.dist', 'phpcs.xml'] as $candidate) {
        if (is_file($modulePath . '/' . $candidate)) {
            $ownRuleset = $modulePath . '/' . $candidate;
            break;
        }
    }
    try {
        run_command([
            ...with_memory_limit($root . '/vendor/bin/phpcs'), '--standard=' . ($ownRuleset ?? 'Magento2'),
            '--report=json', '--report-file=' . $reportFile, '--extensions=php',
            '--ignore=*/vendor/*,*/Test/*', $modulePath,
        ]);
        $data = json_decode((string) file_get_contents($reportFile), true);
    } finally {
        unlink($reportFile);
    }
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
        // Rector reports "file" relative to this process's CWD (/opt/analyzer
        // per the Dockerfile's WORKDIR), not absolute like every other tool
        // here — resolve it so downstream relativization against the module
        // root actually works instead of producing a "../../Users/..." path.
        $rawFile = $diff['file'] ?? '';
        $resolvedFile = realpath($rawFile);
        $findings[] = [
            'file' => $resolvedFile !== false ? $resolvedFile : $rawFile,
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

try {
    $findings = ($tools[$requestPath])($analyzerRoot, $realModulePath);
} catch (Throwable $e) {
    // An uncaught exception/fatal error here previously reached PHP's
    // built-in dev server's own handler, which closes the connection with a
    // 200 and an empty body rather than a proper 500 — the Python client's
    // raise_for_status() doesn't catch that (200 isn't an error status), so
    // it went on to fail parsing an empty body as JSON. Confirmed in
    // production: that propagated all the way up and failed persisting the
    // *whole module*, not just "no findings from this one tool" the way
    // every other failure mode here is designed to degrade. A real 500 with
    // a JSON body is both correctly caught by the Python client already
    // (fails open per tool) and gives something useful in logs instead of a
    // silent empty response.
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()]);
    exit;
}
echo json_encode(['findings' => $findings]);
