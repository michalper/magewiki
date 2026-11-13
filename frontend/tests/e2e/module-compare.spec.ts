import { expect, test } from "@playwright/test";

/**
 * Real e2e coverage for the Phase 21 compare page. Needs no embeddings at
 * all (tags/findings/dependencies are parser-derived fields already
 * rendered by the module detail page) -- unlike "Similar modules" (see
 * module-detail.spec.ts's empty-state assertion), this gets full, real
 * coverage against conflict-store's already-rich Vendor_ConflictA/
 * Vendor_ConflictB fixtures. Skipped entirely when MAGEWIKI_SCAN_ROOT_2
 * isn't configured, same pattern as conflicts.spec.ts.
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

async function moduleIdByName(page: import("@playwright/test").Page, name: string): Promise<string> {
  await page.goto("/modules");
  await page.getByLabel("Search modules").fill(name);
  await page.getByRole("link", { name }).first().click();
  await expect(page).toHaveURL(/\/modules\/\d+$/);
  return page.url().split("/").pop()!;
}

test("the compare page shows both modules' real, independent findings side by side", async ({ page }) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  const idA = await moduleIdByName(page, "Vendor_ConflictA");
  const idB = await moduleIdByName(page, "Vendor_ConflictB");

  await page.goto(`/modules/compare?a=${idA}&b=${idB}`);

  await expect(page.getByRole("heading", { name: "Vendor_ConflictA" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vendor_ConflictB" })).toBeVisible();

  // A fleet-wide conflict badge: both modules collide on it, so it shows on
  // both columns (same real acl_resource_conflict already proven in
  // conflicts.spec.ts).
  await expect(page.getByText("1 acl-conflict")).toHaveCount(2);

  // ConflictA-only single-module findings -- must appear exactly once (its
  // own column), not on ConflictB's.
  await expect(page.getByText("1 missing-acl")).toHaveCount(1);
  await expect(page.getByText("1 CVE")).toHaveCount(1);

  // Each column links back to its own full module page.
  await expect(page.getByRole("link", { name: "View full module →" }).first()).toHaveAttribute(
    "href",
    `/modules/${idA}`,
  );
});

test("the compare page shows a module picker when a/b aren't both set", async ({ page }) => {
  test.skip(!(await hasSecondScanRoot()), "MAGEWIKI_SCAN_ROOT_2 not configured for this run");

  await page.goto("/modules/compare");

  await expect(page.getByText("Module A")).toBeVisible();
  await expect(page.getByText("Module B")).toBeVisible();
});
