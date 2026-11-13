import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../../test-utils";
import CompareClient from "./CompareClient";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiUrl: () => "http://localhost:8000" }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function setSearch(search: string) {
  const url = new URL(window.location.href);
  url.search = search;
  window.history.replaceState(null, "", url);
}

function moduleDetail(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    name: "Vendor_A",
    composer_name: "vendor/a",
    source_type: "standalone",
    path: ".",
    repo_root: "/sites/store",
    enabled: true,
    state: "up_to_date",
    setup_version: "1.0.0",
    class_count: 0,
    plugin_count: 0,
    observer_count: 0,
    last_scanned_at: "2026-01-01T00:00:00Z",
    tags: [],
    has_readme: false,
    has_tests: false,
    has_module_doc: false,
    finding_counts: {},
    license: null,
    homepage: null,
    authors: [],
    php_extensions: [],
    composer_scripts: [],
    composer_autoload_psr4: {},
    composer_allow_plugins: {},
    dependencies: [],
    classes: [],
    preferences: [],
    plugins: [],
    observers: [],
    quality_findings: [],
    ...overrides,
  };
}

describe("CompareClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  afterEach(() => {
    setSearch("");
  });

  it("shows a module picker when a/b aren't both set", async () => {
    setSearch("");
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/modules") return [moduleDetail({ id: 1, name: "Vendor_A" }), moduleDetail({ id: 2, name: "Vendor_B" })];
      throw new Error(`unexpected path: ${path}`);
    });

    renderWithQueryClient(<CompareClient />);

    await waitFor(() => expect(screen.getByText("Module A")).toBeInTheDocument());
    expect(screen.getByText("Module B")).toBeInTheDocument();
  });

  it("renders both modules side by side, each with their own real findings", async () => {
    setSearch("?a=1&b=2");
    fetchMock.mockImplementation(async (path: string) => {
      // A real entry for module 1's own dependency, in the same repo_root --
      // exercises idByName's real match (module.repo_root === dep's own
      // repo_root) and dependenciesList's "found, render a link" branch.
      // A second entry with a *different* repo_root exercises idByName's
      // own repo_root mismatch skip (it must never match across stores).
      if (path === "/modules") {
        return [
          moduleDetail({ id: 99, name: "Magento_Backend", repo_root: "/sites/store" }),
          moduleDetail({ id: 100, name: "Other_Store_Module", repo_root: "/sites/other-store" }),
        ];
      }
      if (path === "/modules/1") {
        return moduleDetail({
          id: 1,
          name: "Vendor_A",
          tags: ["payments"],
          finding_counts: { missing_acl: 1 },
          // A second, unresolved dependency -- exercises both the "not
          // found, muted text" fallback and the comma separator between
          // two (not just one) rendered dependency entries.
          dependencies: ["Magento_Backend", "Vendor_Unresolved"],
        });
      }
      if (path === "/modules/2") {
        return moduleDetail({ id: 2, name: "Vendor_B", composer_name: null });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderWithQueryClient(<CompareClient />);

    await waitFor(() => expect(screen.getByText("Vendor_A")).toBeInTheDocument());
    expect(screen.getByText("Vendor_B")).toBeInTheDocument();
    expect(screen.getByText("payments")).toBeInTheDocument();
    expect(screen.getByText("1 missing-acl")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Magento_Backend" })).toHaveAttribute("href", "/modules/99");
    expect(screen.getByText("Vendor_Unresolved")).toBeInTheDocument();
    expect(screen.getByText(",")).toBeInTheDocument();
    // module 2's own composer_name is null -- the dash fallback, not "vendor/b".
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows no dependencies as a dash, and tolerates the module list still loading", async () => {
    // allModules stays undefined for as long as /modules hasn't resolved --
    // exercises idByName's own `allModules ?? []` fallback, not just an
    // already-resolved (even if empty) array.
    setSearch("?a=1&b=2");
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/modules") return new Promise(() => {});
      if (path === "/modules/1") return moduleDetail({ id: 1, name: "Vendor_A" });
      if (path === "/modules/2") return moduleDetail({ id: 2, name: "Vendor_B" });
      throw new Error(`unexpected path: ${path}`);
    });

    renderWithQueryClient(<CompareClient />);

    await waitFor(() => expect(screen.getByText("Vendor_A")).toBeInTheDocument());
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("picking a module from either dropdown updates the URL and re-renders", async () => {
    setSearch("");
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/modules") return [moduleDetail({ id: 1, name: "Vendor_A" }), moduleDetail({ id: 2, name: "Vendor_B" })];
      if (path === "/modules/1") return moduleDetail({ id: 1, name: "Vendor_A" });
      if (path === "/modules/2") return moduleDetail({ id: 2, name: "Vendor_B" });
      throw new Error(`unexpected path: ${path}`);
    });
    const user = userEvent.setup();

    renderWithQueryClient(<CompareClient />);

    await waitFor(() => expect(screen.getByText("Module A")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Module A"), "1");
    await user.selectOptions(screen.getByLabelText("Module B"), "2");

    expect(window.location.search).toBe("?a=1&b=2");
    await waitFor(() => expect(screen.getByText("Vendor_A")).toBeInTheDocument());
    expect(screen.getByText("Vendor_B")).toBeInTheDocument();
  });

  it("shows an error for a module that fails to load", async () => {
    setSearch("?a=1&b=2");
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/modules") return [];
      if (path === "/modules/1") throw new Error("boom");
      if (path === "/modules/2") return moduleDetail({ id: 2, name: "Vendor_B" });
      throw new Error(`unexpected path: ${path}`);
    });

    renderWithQueryClient(<CompareClient />);

    await waitFor(() => expect(screen.getByText("Failed to load module 1.")).toBeInTheDocument());
  });

  it("shows an error for module B specifically when only it fails to load", async () => {
    setSearch("?a=1&b=2");
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/modules") return [];
      if (path === "/modules/1") return moduleDetail({ id: 1, name: "Vendor_A" });
      if (path === "/modules/2") throw new Error("boom");
      throw new Error(`unexpected path: ${path}`);
    });

    renderWithQueryClient(<CompareClient />);

    await waitFor(() => expect(screen.getByText("Failed to load module 2.")).toBeInTheDocument());
  });
});
