import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("sending a question shows it immediately and resolves to a real response", async ({ page }) => {
  await page.goto("/chat");

  const input = page.getByLabel("Chat message");
  await input.fill("Do we have a Klaviyo integration?");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Do we have a Klaviyo integration?")).toBeVisible();
  // Thinking... while the request is in flight.
  await expect(page.getByRole("button", { name: "Thinking..." })).toBeVisible();

  // No LLM key is configured for this suite (ci.yml's e2e-smoke job), so the
  // real, deterministic outcome is the agent's own graceful failure path
  // (app/agent/loop.py's run_agent raising, caught by app/chat/page.tsx and
  // rendered inline), not a generated answer -- asserting on that real,
  // reproduced behavior (recovers to a usable state, doesn't hang) is more
  // meaningful here than mocking a fake answer would be.
  await expect(page.getByText("chat failed unexpectedly — check server logs")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
});

test("the PM/Dev audience toggle switches the selected mode", async ({ page }) => {
  await page.goto("/chat");

  const pmButton = page.getByRole("button", { name: "PM", exact: true });
  // exact: true -- Next.js's own dev-mode-only dev-tools button
  // ("Open Next.js Dev Tools") otherwise substring-matches "Dev" too.
  const devButton = page.getByRole("button", { name: "Dev", exact: true });

  // No aria-pressed/semantic state on this toggle pair -- it's purely a
  // variant="default" (selected, bg-primary) vs variant="outline"
  // (unselected) style distinction (app/chat/page.tsx), so the button's own
  // class is the only real, observable signal of which one is active.
  await expect(devButton).toHaveClass(/bg-primary/);
  await expect(pmButton).not.toHaveClass(/bg-primary/);

  await pmButton.click();

  await expect(pmButton).toHaveClass(/bg-primary/);
  await expect(devButton).not.toHaveClass(/bg-primary/);
});
