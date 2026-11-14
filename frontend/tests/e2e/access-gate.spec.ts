import { expect, test, type Route } from "@playwright/test";

const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";

// None of this suite's other specs mock the network -- they all exercise a
// real backend (see global-setup.ts). But ci.yml's e2e-smoke job never sets
// WRITE_ACCESS_TOKEN (see CLAUDE.md's Phase 24 decision note / app/api/auth.py),
// and that backend is one shared container for the whole parallel run, so
// there is no way to make it actually return a 401 here without breaking
// every other spec that relies on these same endpoints staying open. The
// backend's own enforcement is already covered by
// backend/tests/api/test_access_gate.py; what has no coverage at all is the
// *frontend's* reaction to a 401 it could get from a deployment that does set
// the token -- showing the prompt, storing what's typed into it, and retrying
// the exact same request with the header attached. Mocking only the network
// boundary at the three endpoints app/api/auth.py's require_write_access
// actually gates is the standard way to test that reaction deterministically.
const UNAUTHORIZED_BODY = JSON.stringify({ detail: "missing or invalid access token" });

async function expectTokenHeaderThenFulfill(route: Route, body: string, contentType = "text/event-stream") {
  const token = await route.request().headerValue("x-access-token");
  expect(token).toBe("test-secret-token");
  await route.fulfill({ status: 200, contentType, body });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mw-onboarding-dismissed", "true"));
});

test("chat shows the access-token prompt on a 401 and retries with the entered token on unlock", async ({
  page,
}) => {
  let chatCalls = 0;
  await page.route(`${API_URL}/chat`, async (route) => {
    chatCalls += 1;
    if (chatCalls === 1) {
      await route.fulfill({ status: 401, contentType: "application/json", body: UNAUTHORIZED_BODY });
      return;
    }
    await expectTokenHeaderThenFulfill(
      route,
      `event: token\ndata: ${JSON.stringify({ text: "Mocked answer after unlock." })}\n\n` +
        `event: done\ndata: ${JSON.stringify({ usage: {} })}\n\n`,
    );
  });

  await page.goto("/chat");
  await page.getByLabel("Chat message").fill("Do we have a Klaviyo integration?");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("This deployment requires an access token for this action.")).toBeVisible();

  await page.getByLabel("Access token").fill("test-secret-token");
  await page.getByRole("button", { name: "Unlock" }).click();

  await expect(page.getByText("This deployment requires an access token for this action.")).not.toBeVisible();
  await expect(page.getByText("Mocked answer after unlock.")).toBeVisible();
  expect(chatCalls).toBe(2);
});

test("settings save shows the access-token prompt on a 401 and retries with the entered token on unlock", async ({
  page,
}) => {
  let patchCalls = 0;
  await page.route(`${API_URL}/settings/llm`, async (route) => {
    if (route.request().method() !== "PATCH") {
      await route.continue();
      return;
    }
    patchCalls += 1;
    if (patchCalls === 1) {
      await route.fulfill({ status: 401, contentType: "application/json", body: UNAUTHORIZED_BODY });
      return;
    }
    const token = await route.request().headerValue("x-access-token");
    expect(token).toBe("test-secret-token");
    // The "Current: ..." display is driven by a separate, real GET
    // /settings/llm refetch this mutation's onSuccess triggers (not by this
    // response), and that real GET is left unmocked -- so the only thing
    // this response needs to get right is a 200 that unblocks the retry.
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        llm_model: "anthropic/claude-sonnet-5-5",
        llm_api_base: null,
        llm_key_configured: false,
        embedding_model: "openai/text-embedding-3-small",
        embedding_api_base: null,
        embedding_key_configured: false,
      }),
    });
  });

  await page.goto("/settings");
  await page.getByLabel("LLM model").fill("anthropic/claude-sonnet-5-5");
  await page.getByRole("button", { name: "Save" }).first().click();

  await expect(page.getByText("This deployment requires an access token for this action.")).toBeVisible();

  await page.getByLabel("Access token").fill("test-secret-token");
  await page.getByRole("button", { name: "Unlock" }).click();

  await expect(page.getByText("This deployment requires an access token for this action.")).not.toBeVisible();
  await expect(page.getByText("Failed to save settings.")).not.toBeVisible();
  expect(patchCalls).toBe(2);
});

test("scanning shows the access-token prompt on a 401 and retries with the entered token on unlock", async ({
  page,
}) => {
  let scanCalls = 0;
  await page.route(`${API_URL}/scan/stream`, async (route) => {
    scanCalls += 1;
    if (scanCalls === 1) {
      await route.fulfill({ status: 401, contentType: "application/json", body: UNAUTHORIZED_BODY });
      return;
    }
    await expectTokenHeaderThenFulfill(
      route,
      `event: done\ndata: ${JSON.stringify({
        result: {
          stores_scanned: 1,
          modules_found: 1,
          modules_created: 0,
          modules_updated: 1,
          duration_seconds: 0.12,
          tasks_enqueued: 0,
        },
      })}\n\n`,
    );
  });

  await page.goto("/modules");
  // The path's real validity doesn't matter -- POST /scan/stream is fully
  // mocked above, so the real backend never sees it.
  await page.getByLabel("Path to scan").fill("/mocked/path");
  await page.getByRole("button", { name: "Scan", exact: true }).click();

  await expect(page.getByText("This deployment requires an access token for this action.")).toBeVisible();

  await page.getByLabel("Access token").fill("test-secret-token");
  await page.getByRole("button", { name: "Unlock" }).click();

  await expect(page.getByText("This deployment requires an access token for this action.")).not.toBeVisible();
  await expect(page.getByText("Found 1 modules (0 created, 1 updated) in 0.12s. 0 analysis tasks queued.")).toBeVisible();
  expect(scanCalls).toBe(2);
});
