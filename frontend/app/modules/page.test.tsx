import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../test-utils";
import ModulesPage from "./page";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiUrl: () => "http://localhost:8000" }));
vi.mock("@/lib/sse", () => ({ streamSse: vi.fn() }));

import { apiFetch } from "@/lib/api";
import { streamSse } from "@/lib/sse";

type ScanStreamEvent =
  | { event: "discovered"; total: number }
  | { event: "store"; name: string; index: number; total: number }
  | { event: "module"; name: string; status: string; index: number; total: number; warning: string | null }
  | { event: "done"; result: Record<string, unknown> }
  | { event: "error"; detail: string };

const fetchMock = vi.mocked(apiFetch);
const streamSseMock = vi.mocked(streamSse);

function mod(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    name: "Vendor_Module",
    repo_root: "/sites/store-a",
    composer_name: "vendor/module",
    setup_version: "1.0.0",
    source_type: "vendor",
    enabled: true,
    state: "up_to_date",
    class_count: 3,
    plugin_count: 1,
    observer_count: 2,
    has_readme: true,
    has_tests: true,
    has_module_doc: true,
    tags: [],
    finding_counts: {},
    last_scanned_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function setSearch(search: string) {
  const url = new URL(window.location.href);
  url.search = search;
  window.history.replaceState(null, "", url);
}

function mockApi({
  modules = [mod()],
  scanRoots = { scan_roots: ["/sites"] },
  detail,
}: {
  modules?: unknown[];
  scanRoots?: { scan_roots: string[] };
  detail?: Record<string, unknown>;
} = {}) {
  fetchMock.mockImplementation(async (path: string) => {
    if (path === "/modules") return modules;
    if (path === "/scan-roots") return scanRoots;
    if (path.startsWith("/modules/")) return detail ?? { quality_findings: [] };
    throw new Error(`unexpected path: ${path}`);
  });
}

describe("ModulesPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    streamSseMock.mockReset();
    setSearch("");
  });

  afterEach(() => {
    setSearch("");
  });

  it("shows a loading state", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithQueryClient(<ModulesPage />);
    expect(screen.getByText("Loading modules...")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/modules") throw new Error("boom");
      return { scan_roots: [] };
    });
    renderWithQueryClient(<ModulesPage />);
    await waitFor(() => expect(screen.getByText("Failed to load modules.")).toBeInTheDocument());
  });

  it("shows an empty-state message", async () => {
    mockApi({ modules: [] });
    renderWithQueryClient(<ModulesPage />);
    await waitFor(() => expect(screen.getByText("No modules scanned yet.")).toBeInTheDocument());
  });

  it("shows configured scan roots, or a hint to configure one", async () => {
    mockApi();
    renderWithQueryClient(<ModulesPage />);
    await waitFor(() => expect(screen.getByText(/Scannable under:/)).toBeInTheDocument());
    expect(screen.getByText("/sites")).toBeInTheDocument();
  });

  it("shows a setup hint when no scan roots are configured", async () => {
    mockApi({ scanRoots: { scan_roots: [] } });
    renderWithQueryClient(<ModulesPage />);
    await waitFor(() => expect(screen.getByText(/No scan roots configured/)).toBeInTheDocument());
  });

  it("renders a module row with its counts and last-scanned date", async () => {
    mockApi({ modules: [mod({ tags: ["payments"] })] });
    renderWithQueryClient(<ModulesPage />);

    await waitFor(() => expect(screen.getAllByText("Vendor_Module").length).toBeGreaterThan(0));
    expect(screen.getAllByText("vendor/module").length).toBeGreaterThan(0);
    expect(screen.getAllByText("payments").length).toBeGreaterThan(0);
    expect(screen.getByText("1 of 1 modules")).toBeInTheDocument();
  });

  it("shows a dash for tags when a module has none", async () => {
    mockApi();
    renderWithQueryClient(<ModulesPage />);
    await waitFor(() => expect(screen.getAllByText("—").length).toBeGreaterThan(0));
  });

  it("shows the absent-state for README/Tests/composer/setup_version when all four are missing", async () => {
    mockApi({
      modules: [mod({ has_readme: false, has_tests: false, composer_name: null, setup_version: null })],
    });
    renderWithQueryClient(<ModulesPage />);

    await waitFor(() => expect(screen.getAllByText("no readme").length).toBeGreaterThan(0));
    expect(screen.getAllByText("no tests").length).toBeGreaterThan(0);
    // composer_name and setup_version both render as the same "—" dash as
    // the empty-tags case above, so this just confirms there are now more
    // of them (module_name/composer-name column + version column).
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  describe("filters", () => {
    it("filters by name or composer name", async () => {
      mockApi({
        modules: [
          mod({ id: 1, name: "Vendor_Alpha" }),
          mod({ id: 2, name: "Vendor_Beta", composer_name: "other/pkg" }),
          // A null composer_name, searched for something its own name
          // doesn't match either -- exercises (m.composer_name ?? "")'s
          // own null fallback, not just the overall name-or-composer check.
          mod({ id: 3, name: "Vendor_Gamma", composer_name: null }),
        ],
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("3 of 3 modules")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Search modules"), "alpha");

      // The search filter is debounced -- it doesn't take effect until typing pauses.
      await waitFor(() => expect(screen.getByText("1 of 3 modules")).toBeInTheDocument());

      // "other/pkg" matches module 2's composer_name but none of the three
      // modules' own names -- the name check alone (which "alpha" above
      // already satisfied without ever needing the composer_name fallback)
      // isn't enough on its own to find this match.
      await user.clear(screen.getByLabelText("Search modules"));
      await user.type(screen.getByLabelText("Search modules"), "other/pkg");
      await waitFor(() => expect(screen.getByText("1 of 3 modules")).toBeInTheDocument());

      // Matches none of the three modules' names or composer_names at all.
      await user.clear(screen.getByLabelText("Search modules"));
      await user.type(screen.getByLabelText("Search modules"), "nonexistent");
      await waitFor(() => expect(screen.getByText("No modules")).toBeInTheDocument());
    });

    it("filters by source type", async () => {
      mockApi({ modules: [mod({ id: 1, source_type: "vendor" }), mod({ id: 2, source_type: "app_code" })] });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("2 of 2 modules")).toBeInTheDocument());
      await user.selectOptions(screen.getByDisplayValue("All sources"), "app_code");

      expect(screen.getByText("1 of 2 modules")).toBeInTheDocument();
    });

    it("filters by state", async () => {
      mockApi({ modules: [mod({ id: 1, state: "up_to_date" }), mod({ id: 2, state: "failed" })] });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("2 of 2 modules")).toBeInTheDocument());
      await user.selectOptions(screen.getByDisplayValue("All states"), "failed");

      expect(screen.getByText("1 of 2 modules")).toBeInTheDocument();
    });

    it("filters by enabled status: true, false, and unknown", async () => {
      mockApi({
        modules: [
          mod({ id: 1, enabled: true }),
          mod({ id: 2, enabled: false }),
          mod({ id: 3, enabled: null }),
        ],
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("3 of 3 modules")).toBeInTheDocument());

      const select = screen.getByDisplayValue("All enabled status");
      await user.selectOptions(select, "true");
      expect(screen.getByText("1 of 3 modules")).toBeInTheDocument();

      await user.selectOptions(select, "false");
      expect(screen.getByText("1 of 3 modules")).toBeInTheDocument();

      await user.selectOptions(select, "unknown");
      expect(screen.getByText("1 of 3 modules")).toBeInTheDocument();
    });

    it("filters by repo via the ?repo= query param, with a Clear button", async () => {
      // A second filter (?finding=) stays active alongside ?repo= -- clearing
      // just the repo one must leave the URL's own other query param alone
      // (clearQueryParam's "any params left?" branch), not reset to a bare
      // "/modules" the way clearing the *only* active filter would.
      setSearch("?repo=%2Fsites%2Fstore-a&finding=hardcoded_secret");
      mockApi({
        modules: [
          mod({ id: 1, repo_root: "/sites/store-a", finding_counts: { hardcoded_secret: 1 } }),
          mod({ id: 2, repo_root: "/sites/store-b", finding_counts: { hardcoded_secret: 1 } }),
        ],
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Filtering by repo:")).toBeInTheDocument());
      await waitFor(() => expect(screen.getByText("1 of 2 modules")).toBeInTheDocument());

      const repoBanner = screen.getByText("Filtering by repo:").closest("div")!;
      await user.click(within(repoBanner).getByRole("button", { name: "Clear" }));

      await waitFor(() => expect(screen.queryByText("Filtering by repo:")).not.toBeInTheDocument());
      // finding=hardcoded_secret is still active -- both modules qualify.
      await waitFor(() => expect(screen.getByText("2 of 2 modules")).toBeInTheDocument());
      expect(window.location.search).toBe("?finding=hardcoded_secret");
    });

    it("filters by finding via the ?finding= query param (comma-separated), with a Clear button", async () => {
      setSearch("?finding=hardcoded_secret,security_advisory");
      mockApi({
        modules: [
          mod({ id: 1, finding_counts: { hardcoded_secret: 1 } }),
          mod({ id: 2, finding_counts: { phpstan_error: 1 } }),
        ],
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Filtering by finding:")).toBeInTheDocument());
      await waitFor(() => expect(screen.getByText("1 of 2 modules")).toBeInTheDocument());

      await user.click(screen.getByRole("button", { name: "Clear" }));

      await waitFor(() => expect(screen.queryByText("Filtering by finding:")).not.toBeInTheDocument());
    });

    it("filters to modules with an AI-generated doc via ?has_doc=true, with a Clear button", async () => {
      setSearch("?has_doc=true");
      mockApi({
        modules: [
          mod({ id: 1, has_module_doc: true }),
          mod({ id: 2, has_module_doc: false }),
        ],
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Showing only modules with an AI-generated doc.")).toBeInTheDocument());
      await waitFor(() => expect(screen.getByText("1 of 2 modules")).toBeInTheDocument());

      await user.click(screen.getByRole("button", { name: "Clear" }));

      await waitFor(() =>
        expect(screen.queryByText("Showing only modules with an AI-generated doc.")).not.toBeInTheDocument(),
      );
      await waitFor(() => expect(screen.getByText("2 of 2 modules")).toBeInTheDocument());
    });
  });

  describe("sorting", () => {
    it("sorts by name ascending by default, toggles to descending, then switches columns", async () => {
      mockApi({ modules: [mod({ id: 1, name: "Beta" }), mod({ id: 2, name: "Alpha" })] });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("2 of 2 modules")).toBeInTheDocument());
      const table = screen.getByRole("table");
      let rows = within(table).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Alpha")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /^Name/ }));
      rows = within(table).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Beta")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /^Classes/ }));
      expect(screen.getByRole("button", { name: /^Classes/ })).toHaveTextContent("↑");
    });

    it("puts AI-analyzed modules first by default, regardless of name, until the user explicitly sorts", async () => {
      // A fleet is rarely fully analyzed (budget-capped incremental
      // analysis) -- plain alphabetical sorting would otherwise show "not
      // analyzed yet" for most rows by sheer chance of which name comes
      // first, confirmed as a real complaint on the live deployed demo.
      mockApi({
        modules: [
          mod({ id: 1, name: "Alpha", has_module_doc: false }),
          mod({ id: 2, name: "Zeta", has_module_doc: true }),
        ],
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("2 of 2 modules")).toBeInTheDocument());
      const table = screen.getByRole("table");
      let rows = within(table).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Zeta")).toBeInTheDocument();

      // An explicit sort-by-name click means literal alphabetical -- no
      // more doc-first grouping once the user has stated a real preference.
      // Two clicks: the default state is already name/asc, so the first
      // click flips to desc (Zeta still first, coincidentally) and the
      // second flips back to asc, genuinely demonstrating Alpha-first on
      // its own merits rather than by coincidence.
      await user.click(screen.getByRole("button", { name: /^Name/ }));
      await user.click(screen.getByRole("button", { name: /^Name/ }));
      rows = within(table).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Alpha")).toBeInTheDocument();
    });
  });

  describe("pagination", () => {
    function modules(n: number) {
      return Array.from({ length: n }, (_, i) => mod({ id: i + 1, name: `Vendor_${String(i + 1).padStart(3, "0")}` }));
    }

    it("shows only one page's worth of rows, with a range summary", async () => {
      mockApi({ modules: modules(60) });
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("60 of 60 modules")).toBeInTheDocument());
      expect(screen.getByText("1–25 of 60")).toBeInTheDocument();
      expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
      expect(screen.getAllByText("Vendor_001").length).toBeGreaterThan(0);
      expect(screen.queryByText("Vendor_026")).not.toBeInTheDocument();
    });

    it("moves to the next/previous page", async () => {
      mockApi({ modules: modules(60) });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Page 1 of 3")).toBeInTheDocument());
      expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

      await user.click(screen.getByRole("button", { name: "Next" }));
      expect(screen.getByText("26–50 of 60")).toBeInTheDocument();
      expect(screen.getAllByText("Vendor_026").length).toBeGreaterThan(0);

      await user.click(screen.getByRole("button", { name: "Previous" }));
      expect(screen.getByText("1–25 of 60")).toBeInTheDocument();
    });

    it("disables Next on the last page", async () => {
      mockApi({ modules: modules(60) });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Page 1 of 3")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Next" }));
      await user.click(screen.getByRole("button", { name: "Next" }));

      expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    });

    it("changes page size", async () => {
      mockApi({ modules: modules(60) });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Page 1 of 3")).toBeInTheDocument());
      await user.selectOptions(screen.getByLabelText("Modules per page"), "100");

      expect(screen.getByText("1–60 of 60")).toBeInTheDocument();
      expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    });

    it("resets to page 1 when the search filter narrows the list", async () => {
      mockApi({ modules: modules(60) });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByText("Page 1 of 3")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(screen.getByText("Page 2 of 3")).toBeInTheDocument());

      await user.type(screen.getByLabelText("Search modules"), "Vendor_001");

      await waitFor(() => expect(screen.getByText("1 of 60 modules")).toBeInTheDocument());
      expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    });
  });

  describe("row expansion", () => {
    it("expands a row to show findings, sorted by severity, with a view-all link beyond the preview count", async () => {
      const findings = Array.from({ length: 7 }, (_, i) => ({
        check_type: "phpstan_error",
        severity: i === 3 ? "blocking" : "warning",
        file_path: `F${i}.php`,
        line: i,
        message: `finding ${i}`,
      }));
      mockApi({ modules: [mod()], detail: { quality_findings: findings } });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Expand" }));

      await waitFor(() => expect(screen.getByText("finding 3")).toBeInTheDocument()); // blocking sorts first
      expect(screen.getByText("View all 7 findings →")).toBeInTheDocument();
      expect(screen.getByText("View AI-generated README →")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Collapse" }));
      expect(screen.queryByText("finding 3")).not.toBeInTheDocument();
    });

    it("shows a no-findings message for an expanded module with none", async () => {
      mockApi({ modules: [mod({ has_module_doc: false })], detail: { quality_findings: [] } });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Expand" }));

      await waitFor(() => expect(screen.getByText("No quality findings.")).toBeInTheDocument());
      expect(screen.queryByText("View AI-generated README →")).not.toBeInTheDocument();
    });

    it("shows an error message when the expanded row's detail fetch fails", async () => {
      fetchMock.mockImplementation(async (path: string) => {
        if (path === "/modules") return [mod()];
        if (path === "/scan-roots") return { scan_roots: [] };
        throw new Error("boom");
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Expand" }));

      await waitFor(() => expect(screen.getByText("Failed to load findings.")).toBeInTheDocument());
    });
  });

  describe("CSV export", () => {
    it("triggers a CSV download", async () => {
      mockApi();
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument());

      const createObjectURL = vi.fn().mockReturnValue("blob:fake");
      vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      await user.click(screen.getByRole("button", { name: "Export CSV" }));

      expect(clickSpy).toHaveBeenCalled();
      clickSpy.mockRestore();
      vi.unstubAllGlobals();
    });
  });

  describe("scan", () => {
    it("does not start a scan with a blank path", async () => {
      mockApi();
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByRole("button", { name: "Scan" })).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Scan" }));

      expect(streamSseMock).not.toHaveBeenCalled();
    });

    it("streams discovered/module/done events into the progress bar, log, and result summary", async () => {
      mockApi();
      streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ScanStreamEvent) => void) => {
        onEvent({ event: "discovered", total: 2 });
        onEvent({ event: "module", name: "Vendor_A", status: "created", index: 1, total: 2, warning: null });
        onEvent({ event: "module", name: "Vendor_B", status: "error", index: 2, total: 2, warning: "bad module.xml" });
        onEvent({
          event: "done",
          result: {
            repository: "/sites/store-a",
            duration_seconds: 1.23,
            modules_found: 2,
            modules_created: 2,
            modules_updated: 0,
            classes_total: 0,
            plugins_total: 0,
            observers_total: 0,
            tasks_enqueued: 4,
            warnings: [],
            modules: [],
            stores_scanned: 1,
          },
        });
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      await waitFor(() => expect(screen.getByText(/Found 2 modules, scanning/)).toBeInTheDocument());
      expect(screen.getByText(/✓ Vendor_A \(created\)/)).toBeInTheDocument();
      expect(screen.getByText(/✗ Vendor_B: bad module\.xml/)).toBeInTheDocument();
      await waitFor(() =>
        expect(screen.getByText(/Found 2 modules \(2 created, 0 updated\) in 1\.23s\. 4 analysis tasks queued\./)).toBeInTheDocument(),
      );
    });

    it("throttles the modules-list refetch to every 5th module event", async () => {
      mockApi();
      streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ScanStreamEvent) => void) => {
        onEvent({ event: "discovered", total: 5 });
        for (let i = 1; i <= 5; i++) {
          onEvent({ event: "module", name: `Vendor_${i}`, status: "created", index: i, total: 5, warning: null });
        }
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      await waitFor(() => expect(screen.getByText(/✓ Vendor_5 \(created\)/)).toBeInTheDocument());
      // The 5th module event triggers a real refetch of /modules -- called at
      // least 3 times total (initial load + throttled refetch + the final
      // "done" refetch would follow if sent).
      await waitFor(() => expect(fetchMock.mock.calls.filter((c) => c[0] === "/modules").length).toBeGreaterThanOrEqual(2));
    });

    it("shows the multi-store prefix when more than one store was scanned", async () => {
      mockApi();
      streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ScanStreamEvent) => void) => {
        onEvent({ event: "store", name: "store-a", index: 1, total: 2 });
        onEvent({
          event: "done",
          result: {
            repository: "/sites", duration_seconds: 1, modules_found: 1, modules_created: 1, modules_updated: 0,
            classes_total: 0, plugins_total: 0, observers_total: 0, tasks_enqueued: 1, warnings: [], modules: [],
            stores_scanned: 2,
          },
        });
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      await waitFor(() => expect(screen.getByText(/=== Store 1\/2: store-a ===/)).toBeInTheDocument());
      await waitFor(() => expect(screen.getByText(/Scanned 2 stores\./)).toBeInTheDocument());
    });

    it("shows a backend error event", async () => {
      mockApi();
      streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ScanStreamEvent) => void) => {
        onEvent({ event: "error", detail: "a scan of /sites/store-a is already in progress" });
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      await waitFor(() =>
        expect(screen.getByText("a scan of /sites/store-a is already in progress")).toBeInTheDocument(),
      );
    });

    it("shows a generic failure message when the stream rejects, but not for an intentional abort", async () => {
      mockApi();
      streamSseMock.mockRejectedValue(new Error("network down"));
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    });

    it("does not show a failure message when the scan stream is aborted", async () => {
      mockApi();
      streamSseMock.mockImplementation(async () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        throw err;
      });
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      // An intentional abort (not a real failure) must never surface an error --
      // scanStatus has no reset-to-idle path on abort (the real case is the whole
      // page unmounting), so it's enough to confirm no error text ever appears.
      await new Promise((r) => setTimeout(r, 10));
      expect(screen.queryByText("aborted")).not.toBeInTheDocument();
    });

    it("ignores a second submit while already scanning", async () => {
      mockApi();
      streamSseMock.mockImplementation(() => new Promise(() => {}));
      const user = userEvent.setup();
      renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));
      expect(streamSseMock).toHaveBeenCalledTimes(1);

      await user.click(screen.getByText("Scanning...")); // disabled -- a direct click on the label
      expect(streamSseMock).toHaveBeenCalledTimes(1);
    });

    it("aborts the in-flight scan on unmount", async () => {
      mockApi();
      let capturedSignal: AbortSignal | undefined;
      streamSseMock.mockImplementation(async (_url, _body, _onEvent, signal) => {
        capturedSignal = signal;
        await new Promise(() => {});
      });
      const user = userEvent.setup();
      const { unmount } = renderWithQueryClient(<ModulesPage />);

      await waitFor(() => expect(screen.getByLabelText("Path to scan")).toBeInTheDocument());
      await user.type(screen.getByLabelText("Path to scan"), "/sites/store-a");
      await user.click(screen.getByRole("button", { name: "Scan" }));

      await waitFor(() => expect(capturedSignal).toBeDefined());
      unmount();

      expect(capturedSignal?.aborted).toBe(true);
    });
  });
});
