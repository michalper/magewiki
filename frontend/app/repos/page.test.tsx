import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../test-utils";
import ReposPage from "./page";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiUrl: () => "http://localhost:8000" }));

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/csv", () => ({ downloadFile: vi.fn() }));

import { apiFetch } from "@/lib/api";
import { downloadFile } from "@/lib/csv";

const fetchMock = vi.mocked(apiFetch);
const downloadFileMock = vi.mocked(downloadFile);

function moduleSummary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    name: "Vendor_Module",
    composer_name: "vendor/module",
    source_type: "app_code",
    path: "app/code/Vendor/Module",
    repo_root: "/sites/store-a",
    enabled: true,
    state: "up_to_date",
    setup_version: "1.0.0",
    class_count: 0,
    plugin_count: 0,
    observer_count: 0,
    last_scanned_at: "2026-01-01T00:00:00Z",
    tags: [],
    has_readme: true,
    has_tests: true,
    has_module_doc: true,
    phpunit_tests_run: null,
    phpunit_tests_failed: null,
    phpunit_coverage_percent: null,
    finding_counts: {},
    ...overrides,
  };
}

function repo(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    repo_root: "/sites/store-a",
    module_count: 10,
    enabled_count: 8,
    has_readme_count: 5,
    has_tests_count: 3,
    last_scanned_at: "2026-01-01T00:00:00Z",
    finding_counts: {},
    ...overrides,
  };
}

describe("ReposPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    pushMock.mockReset();
    downloadFileMock.mockReset();
  });

  it("shows loading state before any query resolves", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithQueryClient(<ReposPage />);

    expect(screen.getAllByText("Loading...")).toHaveLength(3);
  });

  it("shows an error message when a query fails", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("Failed to load repos.")).toBeInTheDocument());
    expect(screen.getByText("Failed to load module overlap.")).toBeInTheDocument();
    expect(screen.getByText("Failed to load duplicate modules.")).toBeInTheDocument();
  });

  it("shows an empty-state message when no repos are scanned", async () => {
    fetchMock.mockImplementation(async (path: string) => (path === "/repos" ? [] : []));
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("No repos scanned yet.")).toBeInTheDocument());
  });

  it("renders a repo card with counts and a link to its pre-filtered modules list", async () => {
    fetchMock.mockImplementation(async (path: string) => (path === "/repos" ? [repo()] : []));
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    expect(screen.getByText("10 modules")).toBeInTheDocument();
    expect(screen.getByText("8/10 enabled")).toBeInTheDocument();
    expect(screen.getByText("5/10 with README")).toBeInTheDocument();
    expect(screen.getByText("3/10 with tests")).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /sites\/store-a/ });
    expect(link).toHaveAttribute("href", "/modules?repo=%2Fsites%2Fstore-a");
  });

  it("downloads the SBOM for a repo without navigating to its filtered modules list", async () => {
    fetchMock.mockImplementation(async (path: string) => (path === "/repos" ? [repo()] : []));
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download SBOM" }));

    expect(openSpy).toHaveBeenCalledWith(
      "http://localhost:8000/repos/sbom?repo_root=%2Fsites%2Fstore-a",
      "_self",
    );
    openSpy.mockRestore();
  });

  it("downloads a health report for a repo without navigating to its filtered modules list", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/repos") return [repo()];
      if (path.startsWith("/modules?repo_root=")) {
        return { total: 1, modules: [moduleSummary({ finding_counts: { hardcoded_secret: 1 } })] };
      }
      return [];
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download health report" }));

    await waitFor(() => expect(downloadFileMock).toHaveBeenCalledTimes(1));
    const [filename, content, mimeType] = downloadFileMock.mock.calls[0];
    expect(filename).toMatch(/^store-a-health-report-\d{4}-\d{2}-\d{2}\.md$/);
    expect(content).toContain("Vendor_Module");
    expect(mimeType).toBe("text/markdown;charset=utf-8;");
    expect(fetchMock).toHaveBeenCalledWith("/modules?repo_root=%2Fsites%2Fstore-a&limit=5000");
  });

  it("disables only the clicked repo's health-report button while the download is in flight", async () => {
    let resolveModules!: (value: { total: number; modules: unknown[] }) => void;
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/repos") return [repo()];
      if (path.startsWith("/modules?repo_root=")) {
        return new Promise((resolve) => {
          resolveModules = resolve;
        });
      }
      return [];
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download health report" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Downloading..." })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Download SBOM" })).toBeEnabled();

    resolveModules({ total: 1, modules: [moduleSummary()] });
    await waitFor(() => expect(downloadFileMock).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Download health report" })).toBeEnabled();
  });

  it("falls back to a generic filename segment when repo_root has no path segments", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/repos") return [repo({ repo_root: "/" })];
      if (path.startsWith("/modules?repo_root=")) return { total: 1, modules: [moduleSummary()] };
      return [];
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download health report" }));

    await waitFor(() => expect(downloadFileMock).toHaveBeenCalledTimes(1));
    expect(downloadFileMock.mock.calls[0][0]).toMatch(/^repo-health-report-\d{4}-\d{2}-\d{2}\.md$/);
  });

  it("shows a generic error message when the failure isn't a real Error", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/repos") return [repo()];
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- deliberately a non-Error rejection
      if (path.startsWith("/modules?repo_root=")) throw "not a real error";
      return [];
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download health report" }));

    await waitFor(() => expect(screen.getByText("Failed to build health report.")).toBeInTheDocument());
  });

  it("shows an inline error and re-enables the button when building the health report fails", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === "/repos") return [repo()];
      if (path.startsWith("/modules?repo_root=")) throw new Error("boom");
      return [];
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download health report" }));

    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Download health report" })).toBeEnabled();
    expect(downloadFileMock).not.toHaveBeenCalled();
  });

  it("navigates to the upgrade-impact page for a repo without navigating to its filtered modules list", async () => {
    fetchMock.mockImplementation(async (path: string) => (path === "/repos" ? [repo()] : []));
    const user = userEvent.setup();
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Check upgrade impact" }));

    expect(pushMock).toHaveBeenCalledWith("/repos/upgrade-impact?repo_root=%2Fsites%2Fstore-a");
  });

  it("singularizes the module count for exactly one module", async () => {
    fetchMock.mockImplementation(async (path: string) => (path === "/repos" ? [repo({ module_count: 1 })] : []));
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("1 module")).toBeInTheDocument());
  });

  it("renders the overlap table with version drift and a known setup_version", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      path === "/modules/overlap"
        ? [
            {
              name: "Vendor_Shared",
              store_count: 2,
              version_drift: true,
              stores: [
                { repo_root: "/sites/store-a", setup_version: "1.0.0" },
                { repo_root: "/sites/store-b", setup_version: null },
              ],
            },
          ]
        : [],
    );
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("Vendor_Shared")).toBeInTheDocument());
    expect(screen.getByText("drift")).toBeInTheDocument();
    expect(screen.getByText("(1.0.0)")).toBeInTheDocument();
    expect(screen.getByText("(unknown)")).toBeInTheDocument();
  });

  it('renders "same" for a module with no version drift', async () => {
    fetchMock.mockImplementation(async (path: string) =>
      path === "/modules/overlap"
        ? [
            {
              name: "Vendor_Shared",
              store_count: 2,
              version_drift: false,
              stores: [{ repo_root: "/sites/store-a", setup_version: "1.0.0" }],
            },
          ]
        : [],
    );
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("same")).toBeInTheDocument());
  });

  it("omits the overlap table entirely when there is no overlap", async () => {
    fetchMock.mockImplementation(async () => []);
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("No repos scanned yet.")).toBeInTheDocument());
    expect(screen.queryByText("Shared across stores")).not.toBeInTheDocument();
  });

  it("renders the duplicate-pairs table with a compare link", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      path === "/modules/duplicate-pairs"
        ? [
            {
              module_a_id: 1,
              module_a_name: "Vendor_Klaviyo",
              module_a_composer_name: "vendor/klaviyo",
              module_b_id: 2,
              module_b_name: "Other_Klaviyo",
              module_b_composer_name: "other/klaviyo",
              similarity: 0.92,
            },
          ]
        : [],
    );
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("Vendor_Klaviyo")).toBeInTheDocument());
    expect(screen.getByText("Other_Klaviyo")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Compare" })).toHaveAttribute(
      "href",
      "/modules/compare?a=1&b=2",
    );
  });

  it("omits the duplicate-pairs table entirely when there are no duplicates", async () => {
    fetchMock.mockImplementation(async () => []);
    renderWithQueryClient(<ReposPage />);

    await waitFor(() => expect(screen.getByText("No repos scanned yet.")).toBeInTheDocument());
    expect(screen.queryByText("Possible duplicate modules")).not.toBeInTheDocument();
  });
});
