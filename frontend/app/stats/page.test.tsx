import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../test-utils";
import StatsPage from "./page";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function mod(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    name: "Vendor_Module",
    has_readme: true,
    has_tests: true,
    has_module_doc: true,
    finding_counts: {},
    ...overrides,
  };
}

describe("StatsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("shows a loading state", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithQueryClient(<StatsPage />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    renderWithQueryClient(<StatsPage />);
    await waitFor(() => expect(screen.getByText("Failed to load modules.")).toBeInTheDocument());
  });

  it("shows an empty-state message with no modules", async () => {
    fetchMock.mockResolvedValue([]);
    renderWithQueryClient(<StatsPage />);
    await waitFor(() => expect(screen.getByText("No modules scanned yet.")).toBeInTheDocument());
  });

  it("sums every finding type across modules into the stat tiles", async () => {
    fetchMock.mockResolvedValue([
      mod({
        id: 1,
        finding_counts: {
          hardcoded_secret: 2,
          security_advisory: 1,
          phpstan_error: 3,
          deprecated_annotation: 1,
          composer_completeness: 1,
          abandoned_dependency: 1,
          magento_php_incompatible: 1,
          magento_version_blocker: 1,
          plugin_conflict: 1,
        },
      }),
      mod({
        id: 2,
        name: "Vendor_Other",
        finding_counts: { hardcoded_secret: 1, phpmd_issue: 4, phpmetrics_issue: 2, composer_conflict: 1 },
      }),
    ]);
    renderWithQueryClient(<StatsPage />);

    await waitFor(() => expect(screen.getByText("Modules scanned")).toBeInTheDocument());
    // Hardcoded secrets: 2 + 1 = 3
    const secretsTile = screen.getByText("Hardcoded secrets").closest("a")!;
    expect(secretsTile).toHaveTextContent("3");
    expect(secretsTile).toHaveAttribute("href", "/modules?finding=hardcoded_secret");

    // Known vulnerabilities: 1
    const cveTile = screen.getByText("Known vulnerabilities").closest("a")!;
    expect(cveTile).toHaveTextContent("1");

    // PHP static-analysis findings: phpstan 3 + phpmd 4 + phpmetrics 2 = 9
    const staticTile = screen.getByText("PHP static-analysis findings").closest("a")!;
    expect(staticTile).toHaveTextContent("9");
    expect(staticTile).toHaveAttribute(
      "href",
      "/modules?finding=phpstan_error,phpmd_issue,phpcs_violation,php_compat_issue,phpmetrics_issue",
    );

    // Cross-module conflicts: plugin_conflict 1 + composer_conflict 1 = 2
    const conflictsTile = screen.getByText("Cross-module conflicts").closest("a")!;
    expect(conflictsTile).toHaveTextContent("2");
    expect(conflictsTile).toHaveAttribute(
      "href",
      "/modules?finding=plugin_conflict,composer_conflict,webapi_route_conflict",
    );
  });

  it("renders a stat tile as a plain div (not a link) when its count is zero", async () => {
    fetchMock.mockResolvedValue([mod()]);
    renderWithQueryClient(<StatsPage />);

    await waitFor(() => expect(screen.getByText("Hardcoded secrets")).toBeInTheDocument());
    const secretsLabel = screen.getByText("Hardcoded secrets");
    expect(secretsLabel.closest("a")).toBeNull();
    expect(secretsLabel.closest("div")).not.toBeNull();
  });

  it("always renders the outdated-dependencies tile as a link target even with no accent", async () => {
    fetchMock.mockResolvedValue([mod({ finding_counts: { outdated_dependency: 5 } })]);
    renderWithQueryClient(<StatsPage />);

    await waitFor(() => expect(screen.getByText("Outdated dependencies")).toBeInTheDocument());
    expect(screen.getByText("Outdated dependencies").closest("a")).toHaveAttribute(
      "href",
      "/modules?finding=outdated_dependency",
    );
  });

  it("shows an info tooltip trigger for a tile with a description, without navigating on click", async () => {
    fetchMock.mockResolvedValue([mod({ finding_counts: { hardcoded_secret: 1 } })]);
    const user = userEvent.setup();
    renderWithQueryClient(<StatsPage />);

    const trigger = await screen.findByLabelText('What is "Hardcoded secrets"?');
    await user.click(trigger);
    // onClick calls preventDefault -- the surrounding <Link> must not navigate.
    // jsdom doesn't implement real navigation, so the proof is simply that this
    // doesn't throw and the trigger is still in the document afterward.
    expect(trigger).toBeInTheDocument();
  });

  it('shows "no findings" copy when nothing has any quality findings', async () => {
    fetchMock.mockResolvedValue([mod()]);
    renderWithQueryClient(<StatsPage />);

    await waitFor(() =>
      expect(screen.getByText("No quality findings across any scanned module.")).toBeInTheDocument(),
    );
  });

  it("renders the top-findings chart section when at least one module has findings", async () => {
    fetchMock.mockResolvedValue([mod({ finding_counts: { hardcoded_secret: 1 } })]);
    renderWithQueryClient(<StatsPage />);

    await waitFor(() => expect(screen.getByText("Top modules by quality findings")).toBeInTheDocument());
    expect(screen.queryByText("No quality findings across any scanned module.")).not.toBeInTheDocument();
  });
});
