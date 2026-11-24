import { expect, test } from "@playwright/test";

/**
 * Real e2e coverage for Phase 27's "what if I upgrade to Magento X" page.
 * Deterministic via the two magento-github cache entries global-setup.ts
 * seeds for this exact purpose: "2.4.8" (already seeded for
 * magento_php_incompatible's own e2e coverage, incompatible with
 * Vendor_QualityChecks' real require.php) and "2.4.6" (seeded here,
 * compatible) -- same module, two different target versions, two different
 * outcomes, proving the page is genuinely version-sensitive rather than
 * echoing a cached "latest" result. Skipped entirely when MAGEWIKI_SCAN_ROOT_2
 * isn't configured, same pattern as quality-checks.spec.ts/conflicts.spec.ts.
 */
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

async function secondScanRoot(): Promise<string | null> {
  const apiUrl = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";
  const response = await fetch(`${apiUrl}/scan-roots`);
  const { scan_roots: scanRoots } = (await response.json()) as { scan_roots: string[] };
  return scanRoots.length > 1 ? scanRoots[1] : null;
}

test("flags Vendor_QualityChecks as blocked on 2.4.8 but clean on 2.4.6", async ({ page }) => {
  const repoRoot = await secondScanRoot();
  test.skip(repoRoot === null, "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto(`/repos/upgrade-impact?repo_root=${encodeURIComponent(repoRoot!)}`);
  await expect(page.getByText(repoRoot!)).toBeVisible();

  await page.getByLabel("Target Magento version").fill("2.4.8");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByRole("link", { name: "Vendor_QualityChecks" })).toBeVisible();
  await expect(page.getByText(/Requires PHP .+ Magento 2\.4\.8 needs/)).toBeVisible();

  await page.getByLabel("Target Magento version").fill("2.4.6");
  await page.getByRole("button", { name: "Check" }).click();
  // Other conflict-store fixture modules declare PHP >=8.1/>=8.2 and
  // genuinely do break on this deliberately PHP-7-compatible 2.4.6 stub --
  // only Vendor_QualityChecks (real require.php ~7.4.0) is the one this
  // test cares about, and its absence here (vs. present on 2.4.8 above) is
  // what proves the page is actually version-sensitive.
  await expect(page.getByText(/modules? would break on 2\.4\.6\./)).toBeVisible();
  await expect(page.getByRole("link", { name: "Vendor_QualityChecks" })).not.toBeVisible();
});

test("navigates to the upgrade-impact page from the Repos page", async ({ page }) => {
  const repoRoot = await secondScanRoot();
  test.skip(repoRoot === null, "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/repos");
  const card = page.locator("a", { hasText: repoRoot! });
  await card.getByRole("button", { name: "Check upgrade impact" }).click();

  await expect(page).toHaveURL(new RegExp(`/repos/upgrade-impact\\?repo_root=${encodeURIComponent(repoRoot!)}`));
  await expect(page.getByRole("heading", { name: "Upgrade impact" })).toBeVisible();
});
