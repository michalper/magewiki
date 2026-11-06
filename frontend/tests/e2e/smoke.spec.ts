import { expect, test } from "@playwright/test";

test("the built app boots and serves the Modules page", async ({ page }) => {
  const response = await page.goto("/modules");
  expect(response?.ok()).toBeTruthy();

  await expect(page.getByRole("heading", { name: "Modules" })).toBeVisible();
  await expect(page.getByPlaceholder("/path/to/magento-store-or-module")).toBeVisible();
  await expect(page.getByRole("button", { name: "Scan" })).toBeVisible();
});
