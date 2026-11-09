import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("KPI tiles show real, non-zero counts from the seeded scan", async ({ page }) => {
  await page.goto("/stats");

  // The tile's label text is "Modules scanned" in the DOM -- CSS
  // (text-transform: uppercase) is what renders it as "MODULES SCANNED" on
  // screen, not an actual uppercase text node.
  const modulesScannedTile = page.locator(".rounded-2xl.bg-card", { hasText: "Modules scanned" });
  await expect(modulesScannedTile.locator(".text-2xl")).toHaveText(/[1-9]\d*/);

  // The fixture's real, parser-only findings (composer_completeness,
  // magento_version_blocker) roll up into these tiles too -- both must read
  // at least 1, proving the tiles are wired to real data, not a permanent
  // zero-state.
  const composerIssuesTile = page.locator(".rounded-2xl.bg-card", { hasText: "Composer issues" });
  await expect(composerIssuesTile.locator(".text-2xl")).toHaveText(/[1-9]\d*/);

  await expect(page.getByText("Top modules by quality findings")).toBeVisible();
  await expect(page.getByText("Vendor_Module").first()).toBeVisible();
});
