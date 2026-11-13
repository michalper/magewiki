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

  // No fixture module ships a README or an AI-generated doc -- real,
  // deterministic 0% on both, proving the percentage math itself runs (not
  // just that the tile renders).
  const readmeTile = page.locator(".rounded-2xl.bg-card", { hasText: "Have a README" });
  await expect(readmeTile.getByText("0%")).toBeVisible();
  const aiDocTile = page.locator(".rounded-2xl.bg-card", { hasText: "Have an AI-generated doc" });
  await expect(aiDocTile.getByText("0%")).toBeVisible();
  // "Have tests" is no longer 0% once conflict-store's Vendor_PhpunitSample
  // (a real Test/Unit dir, for phpunit_failure e2e coverage) joins the
  // fleet -- a real, nonzero percentage now, not a permanent zero-state.
  const testsTile = page.locator(".rounded-2xl.bg-card", { hasText: "Have tests" });
  await expect(testsTile.getByText(/\d+%/)).toBeVisible();
});

test("a KPI tile's info tooltip reveals its real description on hover", async ({ page }) => {
  await page.goto("/stats");

  await page.getByRole("button", { name: 'What is "Hardcoded secrets"?' }).hover();
  await expect(
    page.getByText(/API keys, passwords, or tokens written directly in the code/),
  ).toBeVisible();
});
