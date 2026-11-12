import { expect, test } from "@playwright/test";

const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("the seeded repo shows real stats and a working SBOM download", async ({ page }) => {
  // Scoped to the demo-store repo card specifically -- a second scan root
  // (MAGEWIKI_SCAN_ROOT_2, the conflict-store fixture) may also be
  // configured and shown as its own card, see global-setup.ts.
  const scanRootsResponse = await fetch(`${API_URL}/scan-roots`);
  const { scan_roots: scanRoots } = (await scanRootsResponse.json()) as { scan_roots: string[] };
  const repoRoot = scanRoots[0];

  await page.goto("/repos");
  const repoCard = page.locator(`a[href="/modules?repo=${encodeURIComponent(repoRoot)}"]`);

  await expect(repoCard.getByText("1 module", { exact: true })).toBeVisible();
  await expect(repoCard.getByText("1/1 enabled")).toBeVisible();
  // The fixture module genuinely has no README/tests -- real, deterministic
  // zero counts, not just "the tile renders something".
  await expect(repoCard.getByText("0/1 with README")).toBeVisible();
  await expect(repoCard.getByText("0/1 with tests")).toBeVisible();

  // downloadSbom() (app/repos/page.tsx) uses window.open(url, "_self") --
  // a real navigation, not an <a download> click, but the backend's
  // Content-Disposition: attachment header (GET /repos/sbom) still makes
  // this a real browser download Playwright can observe the same way.
  const downloadPromise = page.waitForEvent("download");
  await repoCard.getByRole("button", { name: "Download SBOM" }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/^sbom-.*\.json$/);
  const path = await download.path();
  expect(path).toBeTruthy();

  // A real, valid CycloneDX document -- not just "a file downloaded",
  // actually the right content.
  const fs = await import("node:fs/promises");
  const sbom = JSON.parse(await fs.readFile(path!, "utf-8"));
  expect(sbom.bomFormat).toBe("CycloneDX");
  // Component name is composer_name when present (build_cyclonedx_sbom()'s
  // own bom_ref rule), not the module's own display name.
  expect(sbom.components.some((c: { name: string }) => c.name === "vendor/module-sample")).toBe(true);
});

test("clicking a repo card navigates to a repo-filtered Modules view", async ({ page }) => {
  const scanRootsResponse = await fetch(`${API_URL}/scan-roots`);
  const { scan_roots: scanRoots } = (await scanRootsResponse.json()) as { scan_roots: string[] };
  const repoRoot = scanRoots[0];

  await page.goto("/repos");
  // The whole card is a real <Link href="/modules?repo=..."> (app/repos/
  // page.tsx) -- "Download SBOM" is a nested <button> with its own
  // stopPropagation so it doesn't trigger this same navigation, but the
  // card-level link itself was never exercised. Matched by its real href
  // rather than its accessible name, which would otherwise be the whole
  // card's concatenated text (module count, enabled/README/tests stats,
  // quality badges, and the nested Download SBOM button).
  await page.locator(`a[href="/modules?repo=${encodeURIComponent(repoRoot)}"]`).click();

  await expect(page).toHaveURL(`/modules?repo=${encodeURIComponent(repoRoot)}`);
  // Scoped to the "Filtering by repo:" banner specifically -- the same
  // repoRoot text also legitimately appears elsewhere on this page (the
  // "Scannable under:" scan-form helper text), so a bare page-wide match is
  // ambiguous.
  const filterBanner = page.locator("div", { hasText: "Filtering by repo:" }).last();
  await expect(filterBanner.getByText(repoRoot, { exact: true })).toBeVisible();
  // "1 of N modules" -- the repo filter narrows the visible rows to 1, but
  // the denominator is the *unfiltered* total across every repo (see
  // app/modules/page.tsx), which is no longer exactly 1 once a second scan
  // root (MAGEWIKI_SCAN_ROOT_2) is also configured.
  await expect(page.getByText(/^1 of \d+ modules$/)).toBeVisible();
});
