import { expect, test } from "@playwright/test";

const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("downloads a real, correct health-report Markdown file for the seeded repo", async ({ page }) => {
  // Scoped to the demo-store repo card specifically, same as repos.spec.ts's
  // own SBOM test -- a second scan root (MAGEWIKI_SCAN_ROOT_2) may also be
  // configured and shown as its own card, see global-setup.ts.
  const scanRootsResponse = await fetch(`${API_URL}/scan-roots`);
  const { scan_roots: scanRoots } = (await scanRootsResponse.json()) as { scan_roots: string[] };
  const repoRoot = scanRoots[0];

  await page.goto("/repos");
  const repoCard = page.locator(`a[href="/modules?repo=${encodeURIComponent(repoRoot)}"]`);

  // downloadFile() (lib/csv.ts) uses a synthetic <a download> click on a
  // Blob object URL, not a server round trip -- Playwright observes it the
  // same way as the server-generated SBOM download either way.
  const downloadPromise = page.waitForEvent("download");
  await repoCard.getByRole("button", { name: "Download health report" }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/^.+-health-report-\d{4}-\d{2}-\d{2}\.md$/);
  const path = await download.path();
  expect(path).toBeTruthy();

  const fs = await import("node:fs/promises");
  const markdown = await fs.readFile(path, "utf-8");

  expect(markdown).toContain("# MageWiki health report");
  expect(markdown).toContain(`**Repo:** \`${repoRoot}\``);
  expect(markdown).toContain("- 1 module\n");
  // Vendor_Module's real, deterministic single-module findings: a
  // composer_completeness issue (missing require-dev phpunit/phpunit) and
  // 4 php-analyzer findings (2 phpmd + 2 phpcs). No Magento-upgrade finding
  // here -- its real require.php (">=8.1") and magento/module-sales
  // requirement are evaluated against global-setup.ts's deliberately fake,
  // network-free "2.4.8" cache entry (empty "replace" map), not real GitHub
  // data, so magento_version_blocker can never fire in this seeded e2e
  // environment (see quality-checks.spec.ts's own comment on the same cache
  // entry, used there for Vendor_QualityChecks' magento_php_incompatible).
  expect(markdown).toContain("- **Composer issues**: 1");
  expect(markdown).toContain("- **PHP static-analysis findings**: 4");
  expect(markdown).toMatch(/\[Vendor_Module]\(.*\/modules\/\d+\) — 5 findings/);
});
