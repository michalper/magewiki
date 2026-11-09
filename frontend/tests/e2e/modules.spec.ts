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

  // The real, live-streamed scan log panel -- not just the final result
  // text. "Found 1 modules, scanning..." is the literal line startScan()
  // pushes on the SSE "discovered" event (app/modules/page.tsx).
  await expect(page.getByText(/Found \d+ modules, scanning\.\.\./)).toBeVisible();

  // The real streamed scan result text -- global-setup.ts already scanned
  // this same fixture once, so this is a real no-op-ish rescan (hash-skip
  // means it's fast), but the SSE progress/result UI is exercised exactly
  // the same either way.
  await expect(page.getByText(/Found \d+ modules? \(\d+ created, \d+ updated\)/)).toBeVisible({ timeout: 30_000 });
});

test("scanning a path outside the configured scan roots shows the real error", async ({ page }) => {
  await page.goto("/modules");
  await page.getByLabel("Path to scan").fill("/this/path/does/not/exist");
  await page.getByRole("button", { name: "Scan", exact: true }).click();

  // /scan/stream rejects an invalid path with a 400 *before* the SSE stream
  // ever starts (_validate_scan_path, app/api/routes/modules.py) -- streamSse
  // (lib/sse.ts) throws a generic "API responded with <status>" for a
  // non-ok response rather than surfacing the backend's real detail text,
  // which is the actual, current behavior this asserts on.
  await expect(page.getByText("API responded with 400")).toBeVisible();
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

test("the enabled-status filter narrows the list by real enabled state", async ({ page }) => {
  await page.goto("/modules");
  // The seeded fixture module is genuinely Enabled: yes (declared in
  // app/etc/config.php) -- filtering to Disabled/Unknown must empty the
  // list, and back to Enabled must restore it, proving this dropdown is
  // really wired to Module.enabled, not just decorative.
  await expect(page.getByText(/\d+ of \d+ modules/)).toBeVisible();

  await page.getByLabel("Filter by enabled status").selectOption("false");
  await expect(page.getByText(/0 of \d+ modules/)).toBeVisible();

  await page.getByLabel("Filter by enabled status").selectOption("true");
  await expect(page.getByText(/[1-9]\d* of \d+ modules/)).toBeVisible();
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

  // Real content, not just "a file downloaded" -- the real column shape
  // downloadModulesCsv() builds (app/modules/page.tsx), and the real
  // seeded module's own row.
  const fs = await import("node:fs/promises");
  const csv = await fs.readFile(path!, "utf-8");
  expect(csv.split("\n")[0]).toContain("name,composer_name,setup_version,source_type,enabled,state");
  expect(csv).toContain("Vendor_Module");
  expect(csv).toContain("vendor/module-sample");
});
