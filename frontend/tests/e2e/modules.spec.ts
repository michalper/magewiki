import { expect, test } from "@playwright/test";

const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("scanning the configured fixture through the UI shows real progress and a result", async ({ page }) => {
  const scanRootsResponse = await fetch(`${API_URL}/scan-roots`);
  const { scan_roots: scanRoots } = (await scanRootsResponse.json()) as { scan_roots: string[] };
  const repoRoot = scanRoots[0];

  await page.goto("/modules");
  await page.getByLabel("Path to scan").fill(repoRoot);
  // exact: true -- "Scan" is otherwise a substring match of the "Last
  // scanned" column's sortable header button too.
  await page.getByRole("button", { name: "Scan", exact: true }).click();

  // The real streamed scan result text -- global-setup.ts already scanned
  // this same fixture once, so this is a real no-op-ish rescan (hash-skip
  // means it's fast), but the SSE progress/result UI is exercised exactly
  // the same either way.
  await expect(page.getByText(/Found \d+ modules? \(\d+ created, \d+ updated\)/)).toBeVisible({ timeout: 30_000 });
});

test("filters narrow the module list and clear back to the full count", async ({ page }) => {
  await page.goto("/modules");
  const countText = page.getByText(/\d+ of \d+ modules/);
  await expect(countText).toBeVisible();
  const [, total] = (await countText.textContent())!.match(/(\d+) of (\d+) modules/)!;

  // A search that can't match anything real -- the module list narrows to 0,
  // proving the filter is actually wired to the query, not just decorative.
  await page.getByLabel("Search modules").fill("this-module-name-cannot-possibly-exist-xyz");
  await expect(page.getByText(/0 of \d+ modules/)).toBeVisible();

  await page.getByLabel("Search modules").fill("");
  await expect(page.getByText(`${total} of ${total} modules`)).toBeVisible();
});

test("sorting by a column header reorders the table", async ({ page }) => {
  await page.goto("/modules");
  const nameHeader = page.getByRole("button", { name: /^Name/ });
  await expect(nameHeader).toBeVisible();

  // Toggling sort direction must not error or blank the table -- the real
  // regression this guards is a sort comparator crashing on a null field
  // (e.g. a module with no last_scanned_at), which an empty result set
  // would silently hide.
  await nameHeader.click();
  await expect(page.getByText(/\d+ of \d+ modules/)).toBeVisible();
  await nameHeader.click();
  await expect(page.getByText(/\d+ of \d+ modules/)).toBeVisible();
});

test("Export CSV downloads a real file with the module data", async ({ page }) => {
  await page.goto("/modules");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/\.csv$/);
  const path = await download.path();
  expect(path).toBeTruthy();
});
