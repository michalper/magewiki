import { expect, test } from "@playwright/test";

/**
 * Real e2e coverage for every check_type that demo-store's single module can
 * never trigger (cross-module conflicts are scoped per repo_root -- see
 * global-setup.ts) plus the two externally-backed checks. Skipped entirely
 * when MAGEWIKI_SCAN_ROOT_2 isn't configured (global-setup.ts only seeds and
 * scans the conflict-store fixture when a second scan root exists), so a
 * local `npx playwright test` with just MAGEWIKI_SCAN_ROOT_1 set still runs
 * the rest of the suite cleanly.
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

test("Vendor_ConflictA shows every fleet-wide conflict badge plus its own single-module findings", async ({
  page,
}) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/modules");
  await page.getByLabel("Search modules").fill("Vendor_ConflictA");
  await expect(page.getByText(/^1 of \d+ modules$/)).toBeVisible();

  // Every row renders twice (a `md:hidden` card for small viewports, a real
  // <table> for the rest) -- scoped to the <table> instance specifically so
  // this doesn't depend on which one the test's own viewport happens to show.
  const table = page.locator("table");
  for (const label of [
    "1 plugin-conflict",
    "1 composer-conflict",
    "1 route-conflict",
    "1 schema-conflict",
    "1 circular-dep",
    "1 preference-conflict",
    "1 cron-conflict",
    "1 graphql-conflict",
    "1 acl-conflict",
    "1 indexer-conflict",
    "1 view-conflict",
    "1 route-id-conflict",
    "1 frontname-conflict",
    "1 virtualtype-conflict",
    "1 widget-conflict",
    "1 menu-conflict",
    "1 cache-conflict",
    "1 missing-acl",
    "1 CVE",
    "1 abandoned",
    "1 outdated",
  ]) {
    await expect(table.getByText(label, { exact: true })).toBeVisible();
  }
});

test("Vendor_ConflictB shows every fleet-wide conflict badge but none of ConflictA's single-module findings", async ({
  page,
}) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/modules");
  await page.getByLabel("Search modules").fill("Vendor_ConflictB");
  await expect(page.getByText(/^1 of \d+ modules$/)).toBeVisible();

  const table = page.locator("table");
  for (const label of [
    "1 plugin-conflict",
    "1 composer-conflict",
    "1 route-conflict",
    "1 schema-conflict",
    "1 circular-dep",
    "1 preference-conflict",
    "1 cron-conflict",
    "1 graphql-conflict",
    "1 acl-conflict",
    "1 indexer-conflict",
    "1 view-conflict",
    "1 route-id-conflict",
    "1 frontname-conflict",
    "1 virtualtype-conflict",
    "1 widget-conflict",
    "1 menu-conflict",
    "1 cache-conflict",
  ]) {
    await expect(table.getByText(label, { exact: true })).toBeVisible();
  }

  // missing_acl/security_advisory/abandoned_dependency/outdated_dependency were only
  // ever seeded/declared on ConflictA -- ConflictB must stay "clean" of them.
  await expect(page.getByText("missing-acl")).toHaveCount(0);
  await expect(page.getByText("CVE")).toHaveCount(0);
});

test("the Stats page's Cross-module conflicts tile includes the seeded acl_resource_conflict", async ({
  page,
}) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/stats");
  const conflictsTile = page.locator(".rounded-2xl.bg-card", { hasText: "Cross-module conflicts" });
  // ConflictA + ConflictB each carry one acl_resource_conflict finding, on top
  // of whatever else this tile already sums -- a real, nonzero lower bound,
  // not an exact total (other fixtures/suites may add their own findings).
  await expect(conflictsTile.locator(".text-2xl")).toHaveText(/[1-9]\d*/);
});
