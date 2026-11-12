import { expect, test } from "@playwright/test";

/**
 * Real e2e coverage for every remaining check_type that had none before this
 * round: the single-module parser/cache-backed checks (hardcoded_secret,
 * deprecated_annotation, license_risk, magento_php_incompatible), the five
 * real php-analyzer static-analysis tools (phpstan/phpmd/phpcs/rector/
 * phpmetrics), and a real, deliberately failing PHPUnit run
 * (phpunit_failure). Skipped entirely when MAGEWIKI_SCAN_ROOT_2 isn't
 * configured, same pattern as conflicts.spec.ts.
 *
 * Vendor_QualityChecks briefly lived under an "Acme_" namespace: php-
 * analyzer's phpcs --ignore flag is always matched as an unanchored,
 * case-insensitive substring over each file's full absolute path (phpcs's
 * own CLI --ignore= has no "relative" mode), so the bare
 * star-slash-vendor-star-slash pattern matched any ancestor directory
 * merely *named* "Vendor" too --
 * silently excluding every module this project has ever scanned under
 * app/code/Vendor/... from phpcs entirely. Fixed in
 * php-analyzer/public/index.php by anchoring both tools' exclude patterns
 * to the real scanned module path; this module is back to "Vendor_" like
 * its siblings, which now doubles as the regression test for that fix --
 * see the decision log for the full root-cause story.
 */
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

async function hasSecondScanRoot(): Promise<boolean> {
  const apiUrl = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";
  const response = await fetch(`${apiUrl}/scan-roots`);
  const { scan_roots: scanRoots } = (await response.json()) as { scan_roots: string[] };
  return scanRoots.length > 1;
}

test("Vendor_QualityChecks shows every single-module check this fixture is designed to trigger", async ({
  page,
}) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/modules");
  await page.getByLabel("Search modules").fill("Vendor_QualityChecks");
  await expect(page.getByText(/^1 of \d+ modules$/)).toBeVisible();

  // Every row renders twice (a `md:hidden` card for small viewports, a real
  // <table> for the rest) -- scoped to the <table> instance, same fix
  // conflicts.spec.ts already needed for the identical reason.
  const table = page.locator("table");
  for (const label of [
    "1 secret", // hardcoded_secret
    "1 deprecated", // deprecated_annotation
    "1 license-risk", // license_risk
    "1 magento-php", // magento_php_incompatible
    "2 phpstan", // phpstan_error
    "4 phpmd", // phpmd_issue
    "7 phpcs", // phpcs_violation
    "1 php-compat", // php_compat_issue
    "1 phpmetrics", // phpmetrics_issue
  ]) {
    await expect(table.getByText(label, { exact: true })).toBeVisible();
  }
});

test("Vendor_PhpunitSample shows a real failing PHPUnit test", async ({ page }) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/modules");
  await page.getByLabel("Search modules").fill("Vendor_PhpunitSample");
  await expect(page.getByText(/^1 of \d+ modules$/)).toBeVisible();

  const table = page.locator("table");
  await expect(table.getByText("1 test-failure", { exact: true })).toBeVisible();
});
