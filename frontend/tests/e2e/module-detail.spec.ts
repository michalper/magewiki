import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("the module detail page shows real facts, a pending README, and real quality findings", async ({ page }) => {
  await page.goto("/modules");
  // Navigate via the real list, not a hardcoded id -- the seeded module's
  // row/id isn't guaranteed stable across CI runs.
  await page.getByRole("link", { name: "Vendor_Module" }).first().click();
  await expect(page).toHaveURL(/\/modules\/\d+$/);

  await expect(page.getByRole("heading", { name: "Vendor_Module" })).toBeVisible();
  // .first(): the composer name can legitimately appear more than once on
  // this page (the facts list, plus any card referencing it) -- this just
  // needs to confirm it's shown somewhere, not pin down which element.
  await expect(page.getByText("vendor/module-sample").first()).toBeVisible();

  // No LLM key is configured for this suite (see ci.yml's e2e-smoke job) --
  // the module can never actually get analyzed, so this pending state is
  // the one real, deterministic outcome to assert on, not a transient
  // loading state that would make this test flaky.
  await expect(page.getByText("This module has not been analyzed yet.")).toBeVisible();

  // Real, parser-only quality findings -- composer_completeness and
  // magento_version_blocker both fire for this fixture with no AI involved,
  // so this section is never empty regardless of LLM configuration.
  await expect(page.getByText(/Quality findings/)).toBeVisible();
  await expect(page.getByText("composer.json").first()).toBeVisible();

  // Real composer.json facts, parsed (not AI-written) -- the fixture's own
  // license list, PSR-4 autoload map, and its one real dependency (the
  // composer require on magento/module-sales resolves to the Magento_Sales
  // module name), none previously asserted on.
  await expect(page.getByText("MIT, OSL-3.0")).toBeVisible();
  await expect(page.getByText("Autoload (PSR-4)")).toBeVisible();
  await expect(page.getByText(/Vendor\\Module/)).toBeVisible();
  await expect(page.getByText("Depends on")).toBeVisible();
  await expect(page.getByText("Magento_Sales").first()).toBeVisible();
});

test("a nonexistent module id shows a real error instead of hanging or crashing", async ({ page }) => {
  // GET /modules/999999999 genuinely 404s -- moduleQuery.isError (not a
  // transient loading state) is the one deterministic outcome here. The
  // QueryClient has no custom retry config, so TanStack Query's own default
  // (3 retries, exponential backoff: 1s/2s/4s) genuinely delays this past
  // Playwright's default 5s assertion timeout -- confirmed live (~8s) before
  // raising it here, not guessed.
  await page.goto("/modules/999999999");
  await expect(page.getByText("Failed to load module.")).toBeVisible({ timeout: 15_000 });
});

test("the dependency graph page renders real nodes for the module", async ({ page }) => {
  await page.goto("/modules");
  await page.getByRole("link", { name: "Vendor_Module" }).first().click();
  await page.getByRole("link", { name: "View dependency graph" }).click();

  await expect(page).toHaveURL(/\/modules\/\d+\/graph$/);
  await expect(page.getByRole("heading", { name: /Vendor_Module.*dependency graph/ })).toBeVisible();
  // The fixture's own real di.xml/composer.json facts -- a plugin target and
  // a composer dependency -- not a placeholder/empty graph. Scoped to the
  // graph node itself (its title attribute) since "Magento_Sales" can also
  // legitimately appear in a details panel elsewhere on the page.
  await expect(page.getByTitle("Magento_Sales")).toBeVisible();
});
