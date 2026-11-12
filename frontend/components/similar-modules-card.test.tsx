import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../test-utils";
import { SimilarModulesCard } from "./similar-modules-card";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiUrl: () => "http://localhost:8000" }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

describe("SimilarModulesCard", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("shows the empty state when there are no similar modules", async () => {
    fetchMock.mockResolvedValue([]);
    renderWithQueryClient(<SimilarModulesCard moduleId="1" />);

    await waitFor(() =>
      expect(screen.getByText(/Not enough analyzed modules yet to compare/)).toBeInTheDocument(),
    );
  });

  it("shows an error message when the query fails", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    renderWithQueryClient(<SimilarModulesCard moduleId="1" />);

    await waitFor(() => expect(screen.getByText("Failed to load similar modules.")).toBeInTheDocument());
  });

  it("lists real similar modules, linking to the compare page, with a similarity percentage", async () => {
    fetchMock.mockResolvedValue([
      { module_id: 2, name: "Vendor_Other", composer_name: "vendor/other", similarity: 0.87 },
    ]);
    renderWithQueryClient(<SimilarModulesCard moduleId="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Other")).toBeInTheDocument());
    expect(screen.getByText("87% similar")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Vendor_Other" })).toHaveAttribute(
      "href",
      "/modules/compare?a=1&b=2",
    );
    expect(fetchMock).toHaveBeenCalledWith("/modules/1/similar");
  });
});
