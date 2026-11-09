import { expect, test } from "@playwright/test";

test("the built app boots and serves the Modules page", async ({ page }) => {
  // Every Playwright test context starts with empty storage, i.e. always a
  // "first visit" -- without this, the onboarding wizard (see
  // components/onboarding-wizard.tsx) auto-opens and covers the page,
  // hiding the Scan button this test checks for. This test verifies the
  // underlying page renders, not the onboarding flow itself.
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));

  const response = await page.goto("/modules");
  expect(response?.ok()).toBeTruthy();

  await expect(page.getByRole("heading", { name: "Modules" })).toBeVisible();
  await expect(page.getByPlaceholder("/path/to/magento-store-or-module")).toBeVisible();
  // exact: true -- with real scanned data now present (see tests/e2e/
  // global-setup.ts), the module table's own "Last scanned" sortable column
  // header otherwise substring-matches "Scan" too.
  await expect(page.getByRole("button", { name: "Scan", exact: true })).toBeVisible();
});
