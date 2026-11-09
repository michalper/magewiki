import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("the seeded repo shows real stats and a working SBOM download", async ({ page }) => {
  await page.goto("/repos");

  await expect(page.getByText("1 module", { exact: true })).toBeVisible();
  await expect(page.getByText("1/1 enabled")).toBeVisible();

  // downloadSbom() (app/repos/page.tsx) uses window.open(url, "_self") --
  // a real navigation, not an <a download> click, but the backend's
  // Content-Disposition: attachment header (GET /repos/sbom) still makes
  // this a real browser download Playwright can observe the same way.
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download SBOM" }).click();
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
