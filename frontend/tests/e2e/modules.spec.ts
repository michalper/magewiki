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

test("pagination controls move between real pages without skipping or repeating a module", async ({ page }) => {
  await page.goto("/modules");

  // Sort by Plugins, not the default Name column -- every seeded module's
  // name is a distinct string, so sorting by name has no real ties at all.
  // plugin_count is 1 for three modules (Vendor_Module, Vendor_ConflictA,
  // Vendor_ConflictB) and 0 for the other four, a real tie that (with
  // pageSize:5 below) lands exactly on the page boundary. NOTE: confirmed by
  // hand that even this doesn't reliably catch a missing Module.id
  // tiebreaker (modules.py's order_by) -- Postgres returns a consistent scan
  // order for a tiny, unmodified table regardless, tie or no tie. The real
  // regression-proof for that is the white-box SQL `ORDER BY`-inspection
  // test in the backend (test_modules_list_api.py /
  // test_tools.py's `..._order_by_includes_module_id_tiebreaker`). This test
  // still exercises real pagination end to end with real tied data, which is
  // worth having even though it can't prove the tiebreaker by itself.
  await page.getByRole("button", { name: /^Plugins/ }).click();

  // Real fleet total (same pattern as the filters test above) -- demo-store +
  // conflict-store (including its two Vendor_PaginationFiller* modules, added
  // purely so this fleet has more than one 5-row page) put the real seeded
  // total comfortably past a pageSize:5 page, so this can actually cross a
  // page boundary with real data instead of only ever rendering a single
  // page's worth of rows.
  const countText = page.getByText(/\d+ of \d+ modules/);
  await expect(countText).toBeVisible();
  const [, total] = (await countText.textContent())!.match(/(\d+) of (\d+) modules/)!;
  const pageSize = 5;
  const expectedPageCount = Math.ceil(Number(total) / pageSize);
  expect(expectedPageCount).toBeGreaterThan(1); // otherwise this test can't prove anything

  await page.getByLabel("Modules per page").selectOption(String(pageSize));
  await expect(page.getByText(`Page 1 of ${expectedPageCount}`)).toBeVisible();

  // exact: true -- "Next" would otherwise also substring-match the
  // Next.js dev-tools overlay button's "Open Next.js Dev Tools" accessible
  // name (docker-compose.yml's web service runs `npm run dev`, dev-tools
  // overlay included, in CI's e2e-smoke job too -- same reasoning as the
  // "Scan" button match above).
  const previousButton = page.getByRole("button", { name: "Previous", exact: true });
  const nextButton = page.getByRole("button", { name: "Next", exact: true });
  await expect(previousButton).toBeDisabled();
  await expect(nextButton).toBeEnabled();

  // Scope to the desktop table, not the md:hidden mobile-card layout
  // (ModuleCard renders plain divs, never a <table>) -- this avoids matching
  // the same module twice, once per responsive layout.
  const firstColumnCells = () => page.locator("table tbody tr td:first-child");
  // The "Page X of Y" label is plain local state and updates the instant a
  // page/pageSize change is clicked, but the table keeps rendering the
  // *previous* page's rows until the refetch resolves (TanStack Query's
  // placeholderData: keepPreviousData, by design, so the table never
  // flashes empty mid-fetch) -- expect.poll on the row count rather than a
  // single read, so this doesn't race that gap and assert against stale rows.
  const remainder = Number(total) % pageSize || pageSize;

  await expect.poll(() => firstColumnCells().allTextContents()).toHaveLength(pageSize);
  const page1Names = await firstColumnCells().allTextContents();

  await nextButton.click();
  await expect(page.getByText(`Page 2 of ${expectedPageCount}`)).toBeVisible();
  await expect.poll(() => firstColumnCells().allTextContents()).toHaveLength(remainder);
  const page2Names = await firstColumnCells().allTextContents();

  // A real bug this would catch *if* Postgres happened to reorder a tied
  // group between the two queries -- it didn't in manual testing on this
  // small, static fleet (see the comment above), so this is a real pagination
  // sanity check, not a reliable proof of the tiebreaker fix itself.
  expect(new Set([...page1Names, ...page2Names]).size).toBe(page1Names.length + page2Names.length);

  await previousButton.click();
  await expect(page.getByText(`Page 1 of ${expectedPageCount}`)).toBeVisible();
  await expect.poll(() => firstColumnCells().allTextContents()).toEqual(page1Names);
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

test("Export CSV respects an active filter instead of exporting everything", async ({ page }) => {
  // exportCsv() (app/modules/page.tsx) re-fetches /modules with the current
  // filters still applied (not an unfiltered export) -- a real data-wiring
  // behavior distinct from the UI merely *showing* 0 rows.
  await page.goto("/modules");
  await page.getByLabel("Search modules").fill("this-module-name-cannot-possibly-exist-xyz");
  await expect(page.getByText(/0 of \d+ modules/)).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const download = await downloadPromise;

  const path = await download.path();
  const fs = await import("node:fs/promises");
  const csv = await fs.readFile(path!, "utf-8");
  // Header row only -- no Vendor_Module data row once filtered out.
  expect(csv.trim().split("\n")).toHaveLength(1);
  expect(csv).not.toContain("Vendor_Module");
});
