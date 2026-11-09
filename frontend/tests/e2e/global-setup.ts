/**
 * Seeds one real scan of the committed demo-store fixture before any e2e
 * test runs. Playwright runs spec files in parallel (playwright.config.ts's
 * fullyParallel: true) with no guaranteed order between them, so a
 * per-spec-file scan would race: two files hitting POST /scan for the same
 * repo_root at the same time get ScanAlreadyInProgressError, not a queued
 * retry. Seeding once here, before the parallel run starts, is the standard
 * Playwright pattern for this and sidesteps the race entirely.
 *
 * Calls the backend API directly (not through the UI) -- this is setup, not
 * the thing under test; modules.spec.ts has its own dedicated test that
 * exercises the actual Scan button/progress UI.
 */
async function globalSetup() {
  const apiUrl = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";
  const scanRootsResponse = await fetch(`${apiUrl}/scan-roots`);
  const { scan_roots: scanRoots } = (await scanRootsResponse.json()) as { scan_roots: string[] };

  if (scanRoots.length === 0) {
    throw new Error(
      "No MAGEWIKI_SCAN_ROOT_* configured for this run -- the e2e suite needs at least one " +
        "real scan root (see .github/workflows/ci.yml's e2e-smoke job) to have anything real " +
        "to test against.",
    );
  }

  const response = await fetch(`${apiUrl}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: scanRoots[0] }),
  });
  if (!response.ok) {
    throw new Error(`Seed scan of ${scanRoots[0]} failed: ${response.status} ${await response.text()}`);
  }
}

export default globalSetup;
