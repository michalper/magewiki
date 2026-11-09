import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

// serial: both tests mutate the same backend singleton (RuntimeLlmConfig,
// id=1) -- playwright.config.ts's fullyParallel:true runs tests within one
// file concurrently by default too, and the two tests racing to save/reset
// the same row produced a real, confirmed flake (one test observing the
// other's write mid-reload) until this was added.
test.describe.serial("Settings — BYOK", () => {
  test("saving a new LLM model persists and is reflected back", async ({ page }) => {
    await page.goto("/settings");

    await expect(page.getByRole("heading", { name: "Settings — BYOK" })).toBeVisible();

    await page.getByLabel("LLM model").fill("anthropic/claude-sonnet-5-5");
    await page.getByRole("button", { name: "Save" }).first().click();

    await expect(page.getByText("Current: anthropic/claude-sonnet-5-5")).toBeVisible();

    // Real persistence, not just optimistic local state -- a reload
    // re-fetches from the backend's own stored RuntimeLlmConfig row.
    await page.reload();
    await expect(page.getByText("Current: anthropic/claude-sonnet-5-5")).toBeVisible();
  });

  test("Reset to .env default clears an override back to the configured default", async ({ page }) => {
    await page.goto("/settings");

    await page.getByLabel("LLM model").fill("some/overridden-model");
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect(page.getByText("Current: some/overridden-model")).toBeVisible();

    await page.getByRole("button", { name: "Reset to .env default" }).first().click();
    // LLM_MODEL's real .env default (see .env.example / docker-compose.yml)
    // -- the specific value matters less than it no longer being the
    // override.
    await expect(page.getByText("Current: some/overridden-model")).not.toBeVisible();
  });
});
