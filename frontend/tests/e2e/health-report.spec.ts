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
  // 4 php-analyzer findings (2 phpmd + 2 phpcs) -- both pure local facts,
  // unaffected by anything external. Deliberately NOT asserting on a
  // Magento-upgrade finding or an exact total count here: unlike
  // conflict-store's Vendor_QualityChecks (evaluated against
  // global-setup.ts's seeded, network-free "2.4.8"/"2.4.6" cache entries),
  // demo-store is scanned *before* those entries are seeded (see
  // global-setup.ts's own ordering), so its magento_php_incompatible/
  // magento_version_blocker result depends on whatever Magento's real,
  // live GitHub release actually requires at scan time -- not deterministic
  // across environments or time (confirmed directly: this assertion once
  // flaked in CI on a real, then-current magento_version_blocker finding
  // that this sandbox's own cached data didn't have).
  expect(markdown).toContain("- **Composer issues**: 1");
  expect(markdown).toContain("- **PHP static-analysis findings**: 4");
  expect(markdown).toMatch(/\[Vendor_Module]\(.*\/modules\/\d+\) — \d+ findings?/);
});
