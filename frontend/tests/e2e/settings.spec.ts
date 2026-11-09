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

  test("Reset to .env default for Embeddings is a true no-op with no embedding key configured", async ({ page }) => {
    // Regression test for a real bug: PATCH /settings/llm used to run its
    // live embedding-dimension probe whenever embedding_model was present in
    // the request body at all, even when the *effective* model wasn't
    // actually changing -- so a genuine no-op reset made a real API call and
    // 400'd outright in an environment (like this one) with no embedding
    // key configured. Fixed to only probe on an actual change; this
    // confirms Reset now succeeds silently instead of showing an error.
    await page.goto("/settings");

    await page.getByRole("button", { name: "Reset to .env default" }).last().click();
    await expect(page.getByText(/could not verify/)).not.toBeVisible();
    await expect(page.getByText("Current: openai/text-embedding-3-small")).toBeVisible();
  });

  test("saving a genuinely new embedding model without a real provider key shows the real error", async ({
    page,
  }) => {
    // No embedding API key is configured for this suite (see ci.yml's
    // e2e-smoke job) -- a genuine model change always fails the live
    // dimension probe, and this asserts on that real, deterministic error
    // text rather than assuming a success path this environment can't reach.
    await page.goto("/settings");

    await page.getByLabel("Embedding model").fill("openai/text-embedding-3-large");
    await page.getByRole("button", { name: "Save" }).last().click();

    await expect(page.getByText(/could not verify openai\/text-embedding-3-large's embedding dimension/)).toBeVisible();
    // Rejected, not persisted.
    await expect(page.getByText("Current: openai/text-embedding-3-small")).toBeVisible();
  });
});
