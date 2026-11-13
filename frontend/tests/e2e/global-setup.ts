import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Seeds one real scan of the committed demo-store fixture before any e2e
 * test runs. Playwright runs spec files in parallel (playwright.config.ts's
 * fullyParallel: true) with no guaranteed order between them, so a
 * per-spec-file scan would race: two files hitting POST /scan for the same
 * repo_root at the same time get ScanAlreadyInProgressError, not a queued
 * retry. Seeding once here, before the parallel run starts, is the standard
 * Playwright pattern for this and sidesteps the race entirely.
 *
 * Calls the backend API directly (not through the UI) -- this is setup, not
 * the thing under test; modules.spec.ts has its own dedicated test that
 * exercises the actual Scan button/progress UI.
 *
 * A second scan root (MAGEWIKI_SCAN_ROOT_2), when configured, points at
 * backend/tests/fixtures/conflict-store -- Vendor_ConflictA/Vendor_ConflictB
 * deliberately conflict with *each other* (not with demo-store's own
 * Vendor_Module; cross-module conflict checks are scoped per repo_root, see
 * app/scanner/orchestrator.py, so a module only ever gets compared against
 * siblings under its own scan root). Two more, unrelated modules carry every
 * single-module check that isn't a cross-module conflict: Vendor_
 * QualityChecks (hardcoded_secret, deprecated_annotation, license_risk,
 * magento_php_incompatible, and the five php-analyzer static-analysis
 * checks) and Vendor_PhpunitSample (phpunit_failure, split into its own
 * module because a committed vendor/bin/phpunit at a module's root breaks
 * phpmd/phpcs's own file discovery for every other file in that same
 * module). Vendor_QualityChecks briefly lived under an "Acme_" namespace as
 * a workaround for a real php-analyzer bug: phpcs's --ignore flag is always
 * matched as an unanchored, case-insensitive substring over each file's
 * full absolute path, so the bare "star-slash-vendor-star-slash" pattern
 * matched any ancestor directory merely named "Vendor" too -- fixed in
 * php-analyzer/public/index.php by anchoring both tools' exclude patterns
 * to the real scanned module path (see the decision log for the full
 * root-cause story). The security_advisory/abandoned_dependency/outdated_dependency/
 * magento_php_incompatible findings need a deterministic, network-free
 * response -- seeded directly into the real packagist_cache table (shared
 * by both the Packagist- and GitHub-backed checks, see
 * app/scanner/packagist_cache.py) via `docker compose exec api python -m
 * app.cli seed-packagist-cache`, the same "the check reads the cache before
 * ever reaching httpx" mechanism this project's own pytest already proves,
 * before that second scan runs.
 */
async function globalSetup() {
  const apiUrl = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";
  const scanRootsResponse = await fetch(`${apiUrl}/scan-roots`);
  const { scan_roots: scanRoots } = (await scanRootsResponse.json()) as { scan_roots: string[] };

  if (scanRoots.length === 0) {
    throw new Error(
      "No MAGEWIKI_SCAN_ROOT_* configured for this run -- the e2e suite needs at least one " +
        "real scan root (see .github/workflows/ci.yml's e2e-smoke job) to have anything real " +
        "to test against.",
    );
  }

  await seedScan(apiUrl, scanRoots[0]);

  if (scanRoots.length > 1) {
    seedPackagistCache(
      "advisories:vendor/vulnerable-pkg",
      JSON.stringify({
        advisories: {
          "vendor/vulnerable-pkg": [
            {
              cve: "CVE-2024-99999",
              title: "Fake test advisory",
              link: "https://example.com",
              affectedVersions: "<2.0",
            },
          ],
        },
      }),
    );
    seedPackagistCache(
      "p2:vendor/abandoned-pkg",
      JSON.stringify({ packages: { "vendor/abandoned-pkg": [{ version: "1.0.0", abandoned: true }] } }),
    );
    seedPackagistCache(
      "p2:vendor/outdated-pkg",
      JSON.stringify({ packages: { "vendor/outdated-pkg": [{ version: "2.0.0", abandoned: false }] } }),
    );
    // Only used for the composer_conflict check (ConflictA requires ^6.0,
    // ConflictB requires ^7.0) -- a fully fake package name, deliberately
    // *not* a real one (an earlier version of this fixture used
    // guzzlehttp/guzzle, which has real Packagist advisories that made
    // security_advisory's count depend on live, changing network data; see
    // the decision log). Seeded "clean" (no advisories, not abandoned, a
    // version satisfying ConflictA's ^6.0 so it doesn't also count as
    // outdated there) purely so neither check ever needs a real HTTP call.
    seedPackagistCache(
      "advisories:vendor/conflict-version-probe",
      JSON.stringify({ advisories: { "vendor/conflict-version-probe": [] } }),
    );
    seedPackagistCache(
      "p2:vendor/conflict-version-probe",
      JSON.stringify({ packages: { "vendor/conflict-version-probe": [{ version: "6.5.0", abandoned: false }] } }),
    );
    // magento_php_incompatible (Vendor_QualityChecks, Phase 12b's
    // check_magento_upgrade_readiness) reads the exact same shared
    // packagist_cache table via app/scanner/magento_github.py -- these two
    // keys avoid a real, changing GitHub API call the same way the Packagist
    // ones above avoid a real Packagist call. Vendor_QualityChecks declares
    // no magento/* requirement, so only the php-constraint key is ever read.
    seedPackagistCache("magento-github:latest-release", JSON.stringify({ tag_name: "2.4.8" }));
    seedPackagistCache(
      "magento-github:2.4.8:composer.json",
      JSON.stringify({ require: { php: "~8.1.0||~8.2.0||~8.3.0" }, replace: {} }),
    );
    await seedScan(apiUrl, scanRoots[1]);
  }
}

async function seedScan(apiUrl: string, repoRoot: string) {
  const response = await fetch(`${apiUrl}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: repoRoot }),
  });
  if (!response.ok) {
    throw new Error(`Seed scan of ${repoRoot} failed: ${response.status} ${await response.text()}`);
  }
}

// repoRoot for docker-compose.yml, two levels up from frontend/ -- array args
// (not a shell string), so the JSON payload's own quotes never need escaping.
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

function seedPackagistCache(cacheKey: string, responseJson: string) {
  execFileSync(
    "docker",
    ["compose", "exec", "-T", "api", "python", "-m", "app.cli", "seed-packagist-cache", cacheKey, responseJson],
    { cwd: REPO_ROOT, stdio: "inherit" },
  );
}

export default globalSetup;
