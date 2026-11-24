import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../../test-utils";
import UpgradeImpactClient from "./UpgradeImpactClient";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiUrl: () => "http://localhost:8000" }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function setSearch(search: string) {
  const url = new URL(window.location.href);
  url.search = search;
  window.history.replaceState(null, "", url);
}

function impactResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    version: "2.4.7",
    checked_count: 3,
    blocked_modules: [],
    ...overrides,
  };
}

describe("UpgradeImpactClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    setSearch("");
  });

  it("prompts to pick a repo when repo_root is missing from the URL", () => {
    renderWithQueryClient(<UpgradeImpactClient />);

    expect(screen.getByText(/No repo selected/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Repos" })).toHaveAttribute("href", "/repos");
  });

  it("disables Check until a version is typed, then queries the backend with it", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    fetchMock.mockResolvedValue(impactResponse());
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    expect(screen.getByText("/sites/store-a")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check" })).toBeDisabled();

    await user.type(screen.getByLabelText("Target Magento version"), "2.4.7");
    expect(screen.getByRole("button", { name: "Check" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/repos/upgrade-impact?repo_root=%2Fsites%2Fstore-a&version=2.4.7",
      ),
    );
  });

  it("shows a clean summary when nothing would break", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    fetchMock.mockResolvedValue(impactResponse({ checked_count: 5, blocked_modules: [] }));
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    await user.type(screen.getByLabelText("Target Magento version"), "2.4.7");
    await user.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText("0 of 5 modules would break on 2.4.7.")).toBeInTheDocument());
    expect(screen.getByText("No blocking findings.")).toBeInTheDocument();
  });

  it("lists each blocked module with its findings and a link to its detail page", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    fetchMock.mockResolvedValue(
      impactResponse({
        checked_count: 2,
        blocked_modules: [
          {
            module_id: 7,
            name: "Vendor_Old",
            path: "app/code/Vendor/Old",
            findings: [
              {
                check_type: "magento_php_incompatible",
                severity: "blocking",
                file_path: "composer.json",
                line: null,
                message: "Requires PHP ~7.4.0, but Magento 2.4.7 needs ~8.1.0",
              },
            ],
          },
        ],
      }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    await user.type(screen.getByLabelText("Target Magento version"), "2.4.7");
    await user.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText("Vendor_Old")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Vendor_Old" })).toHaveAttribute("href", "/modules/7");
    expect(screen.getByText(/Requires PHP ~7\.4\.0/)).toBeInTheDocument();
  });

  it("singularizes the module count when exactly one module was checked", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    fetchMock.mockResolvedValue(impactResponse({ checked_count: 1, blocked_modules: [] }));
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    await user.type(screen.getByLabelText("Target Magento version"), "2.4.7");
    await user.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText("0 of 1 module would break on 2.4.7.")).toBeInTheDocument());
  });

  it("does not query the backend when submitting a whitespace-only version", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    await user.type(screen.getByLabelText("Target Magento version"), "   ");
    screen.getByLabelText("Target Magento version").closest("form")?.requestSubmit();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the backend's error message when the version is not recognized", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    fetchMock.mockRejectedValue(new Error("Magento release '9.9.9' not found"));
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    await user.type(screen.getByLabelText("Target Magento version"), "9.9.9");
    await user.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText("Magento release '9.9.9' not found")).toBeInTheDocument());
  });

  it("falls back to a generic error message for a non-Error rejection", async () => {
    setSearch("?repo_root=%2Fsites%2Fstore-a");
    fetchMock.mockRejectedValue("boom");
    const user = userEvent.setup();
    renderWithQueryClient(<UpgradeImpactClient />);

    await user.type(screen.getByLabelText("Target Magento version"), "2.4.7");
    await user.click(screen.getByRole("button", { name: "Check" }));

    await waitFor(() => expect(screen.getByText("Failed to check upgrade impact.")).toBeInTheDocument());
  });
});
