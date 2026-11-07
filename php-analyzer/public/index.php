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

// Only phpstan uses this (bitexpert/phpstan-magento's magentoRoot) — optional,
// and falls back to the module's own path (correct for a self-contained
// standalone checkout that ships its own full vendor/magento/*, e.g. the real
// Ordo_Automation fixture) when the caller doesn't know a wider store root.
$magentoRootRaw = is_array($body) ? ($body['magento_root'] ?? null) : null;
$magentoRoot = is_string($magentoRootRaw) && $magentoRootRaw !== '' && is_dir($magentoRootRaw)
    ? (realpath($magentoRootRaw) ?: $realModulePath)
    : $realModulePath;

// Validated against a strict allowlist (not passed straight through) even
// though this endpoint is internal-only — it still ends up as the first
// element of a proc_open() command array, i.e. the actual binary executed.
// Picked by the Python caller from the scanned module's own composer.json
// php constraint (see app/scanner/php_analyzer_client.py's _pick_php_binary);
// php83/php84/php85 are installed side by side for exactly this (see
// Dockerfile) — a scanned module's own vendor/autoload.php, loaded for
// bitexpert/phpstan-magento's class resolution, enforces its declared PHP
// version strictly via Composer's generated platform_check.php, and no
// single fixed interpreter version can satisfy every scanned module.
$phpBinaryRaw = is_array($body) ? ($body['php_binary'] ?? null) : null;
$phpBinary = in_array($phpBinaryRaw, ['php83', 'php84', 'php85'], true) ? $phpBinaryRaw : 'php84';

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
function with_memory_limit(string $phpBinary, string $binary): array
{
    return [$phpBinary, '-d', 'memory_limit=-1', $binary];
}

// NEON single-quoted strings escape an embedded ' by doubling it, same as
// YAML — these paths come from realpath() upstream (not arbitrary user
// text), but escape defensively anyway rather than assume that always holds.
function neon_quote(string $value): string
{
    return "'" . str_replace("'", "''", $value) . "'";
}

// magentoRoot/bootstrapFiles can't be set dynamically via %env(...)% in
// phpstan.neon itself — confirmed empirically that PHPStan's env()
// resolution doesn't reliably apply to these two keys (one left the literal,
// unsubstituted "%env(...)%" text in a file path; the other failed
// differently, as a Nette DI "Statement" object reaching code that expects a
// plain string). Generating a tiny overlay config with both as literal, real
// paths and including the real phpstan.neon from it sidesteps the issue.
// PHPStan's own "PHP version for analysis: X (from runtime)" auto-detection
// (visible in --debug output) does not actually reach every rule — confirmed
// empirically with a minimal reproduction: a bare `private const array X =
// [...]` (valid PHP 8.3+ syntax) still raised the non-ignorable
// classConstant.nativeTypeNotSupported error when run under php85 with
// nothing else in the config, and only setting `phpVersion` explicitly as a
// literal integer fixed it. Maps 1:1 to the three binaries installed in the
// Dockerfile.
const PHP_VERSION_IDS = ['php83' => 80300, 'php84' => 80400, 'php85' => 80500];

function _run_phpstan_with_bootstrap(
    string $root, string $modulePath, string $magentoRoot, string $autoloadFile, string $phpBinary
): ?array {
    $overlayPath = tempnam(sys_get_temp_dir(), 'phpstan_overlay_') . '.neon';
    $phpVersionId = PHP_VERSION_IDS[$phpBinary] ?? PHP_VERSION_IDS['php84'];
    file_put_contents(
        $overlayPath,
        "includes:\n    - " . neon_quote($root . '/phpstan.neon') . "\n" .
        "parameters:\n" .
        "    phpVersion: $phpVersionId\n" .
        "    magento:\n        magentoRoot: " . neon_quote($magentoRoot) . "\n" .
        "    bootstrapFiles:\n        - " . neon_quote($autoloadFile) . "\n"
    );
    try {
        $result = run_command([
            ...with_memory_limit($phpBinary, $root . '/vendor/bin/phpstan'),
            'analyse', '--error-format=json', '--no-progress', '--configuration=' . $overlayPath, $modulePath,
        ]);
    } finally {
        unlink($overlayPath);
    }
    $data = json_decode($result['stdout'], true);
    if (!is_array($data)) {
        return null;
    }
    // A non-empty top-level "errors" entry means PHPStan itself crashed
    // (a config/internal error, not a per-file analysis result) — confirmed
    // as a real risk by a separate, battle-tested internal Magento-module
    // scanner: bitexpert/phpstan-magento's autoloader services (Factory/
    // Proxy/ExtensionInterface) can throw this way when magentoRoot isn't
    // backed by a real Magento install. Only treat it as a full failure (to
    // trigger run_phpstan()'s own retry-without-bootstrap below) when
    // "files" is ALSO empty — if PHPStan ever emits both a scan-wide error
    // alongside real per-file messages, those real messages are still worth
    // keeping. Verified directly against this sidecar's own two real cases
    // (a real vendor/autoload.php, and the no-op fallback) that "errors" is
    // normally empty — this is a defensive check for a failure mode not yet
    // observed here, not a fix for one that was.
    if (!empty($data['errors']) && empty($data['files'])) {
        return null;
    }
    return $data;
}

function run_phpstan(string $root, string $modulePath, string $magentoRoot, string $phpBinary): array
{
    // bitexpert's autoloaders only synthesize Magento's *Factory/*Proxy/
    // extension-interface classes (generated code that never exists as real
    // files) — an ordinary real class like Magento\Backend\Block\Template
    // still needs the scanned store's own real Composer autoloader to
    // resolve at all, confirmed empirically: bitexpert's magentoRoot alone
    // left those as "extends unknown class". Falls back to a no-op file when
    // the scanned module has no real vendor/autoload.php of its own (e.g. a
    // minimal fixture) — bootstrapFiles require()s the path unconditionally.
    $realAutoload = $magentoRoot . '/vendor/autoload.php';
    $noopAutoload = $root . '/noop-autoload.php';
    $preferredAutoload = is_file($realAutoload) ? $realAutoload : $noopAutoload;

    $data = _run_phpstan_with_bootstrap($root, $modulePath, $magentoRoot, $preferredAutoload, $phpBinary);
    if ($data === null && $preferredAutoload !== $noopAutoload) {
        // The real autoloader can fail outright — most commonly, the scanned
        // module's own composer.json declares a PHP version requirement this
        // sidecar's own PHP runtime doesn't satisfy (Composer's generated
        // vendor/composer/platform_check.php enforces this strictly, and
        // can't be disabled without mutating the scanned module's own files,
        // which MageWiki never does). Retry without the real autoloader:
        // bitexpert's magentoRoot-independent features (DataObject magic
        // methods, ObjectManager type hints) and the custom stub still apply,
        // just without real-class resolution — degraded, not zero, findings,
        // for a module whose PHP requirement doesn't match this sidecar's.
        $data = _run_phpstan_with_bootstrap($root, $modulePath, $magentoRoot, $noopAutoload, $phpBinary);
    }
    $findings = [];
    foreach (($data['files'] ?? []) as $file => $info) {
        foreach (($info['messages'] ?? []) as $message) {
            $findings[] = ['file' => $file, 'line' => $message['line'] ?? null, 'message' => $message['message'] ?? ''];
        }
    }
    return $findings;
}

function run_phpmd(string $root, string $modulePath, string $phpBinary): array
{
    $result = run_command([
        ...with_memory_limit($phpBinary, $root . '/vendor/bin/phpmd'), $modulePath, 'json', 'codesize,unusedcode,design',
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

function run_phpcs(string $root, string $modulePath, string $phpBinary): array
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
            ...with_memory_limit($phpBinary, $root . '/vendor/bin/phpcs'), '--standard=' . ($ownRuleset ?? 'Magento2'),
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

function run_rector(string $root, string $modulePath, string $phpBinary): array
{
    $result = run_command([
        ...with_memory_limit($phpBinary, $root . '/vendor/bin/rector'), 'process', $modulePath, '--dry-run',
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
    $findings = $requestPath === '/phpstan'
        ? run_phpstan($analyzerRoot, $realModulePath, $magentoRoot, $phpBinary)
        : ($tools[$requestPath])($analyzerRoot, $realModulePath, $phpBinary);
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
