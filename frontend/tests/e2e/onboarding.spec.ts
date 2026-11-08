import { expect, test } from "@playwright/test";

test.describe("onboarding wizard", () => {
  test("auto-opens on a first visit, steps through every step, and closing it remembers the dismissal", async ({
    page,
  }) => {
    await page.goto("/modules");

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Welcome to MageWiki-AI")).toBeVisible();

    await dialog.getByRole("button", { name: "Next" }).click();
    await expect(dialog.getByText("Scanning your store")).toBeVisible();

    await dialog.getByRole("button", { name: "Next" }).click();
    await expect(dialog.getByText("AI features are optional")).toBeVisible();

    await dialog.getByRole("button", { name: "Back" }).click();
    await expect(dialog.getByText("Scanning your store")).toBeVisible();

    await dialog.getByRole("button", { name: "Next" }).click();
    await dialog.getByRole("button", { name: "Next" }).click();
    await expect(dialog.getByText("You're all set")).toBeVisible();

    await dialog.getByRole("button", { name: "Got it" }).click();
    await expect(dialog).not.toBeVisible();

    // The dismissal must survive a real reload, not just the in-memory state.
    await page.reload();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("reopens from the header's Help button after being dismissed, on any page", async ({ page }) => {
    await page.goto("/modules");
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();

    await page.goto("/chat");
    await expect(page.getByRole("dialog")).not.toBeVisible();

    await page.getByRole("button", { name: "Show setup guide" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Welcome to MageWiki-AI")).toBeVisible();
  });

  test("shows the live configured scan roots on the scanning step", async ({ page }) => {
    await page.goto("/modules");
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Next" }).click();

    // Either a real configured path or the explicit "none configured" message
    // -- whichever is true for this deployment, but never a loading/blank gap.
    await expect(
      dialog.getByText(/Already configured on this deployment:|No scan roots configured yet/),
    ).toBeVisible();
  });
});
