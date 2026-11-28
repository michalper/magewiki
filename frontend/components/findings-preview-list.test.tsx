import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FindingsPreviewList } from "./findings-preview-list";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function finding(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    check_type: "hardcoded_secret",
    severity: "blocking",
    file_path: "Model/Thing.php",
    line: 12,
    message: "An API key was found.",
    ...overrides,
  };
}

describe("FindingsPreviewList", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("renders a finding's severity, location, and message", () => {
    render(<FindingsPreviewList findings={[finding()]} limit={10} footer={null} />);

    expect(screen.getByText("blocking")).toBeInTheDocument();
    expect(screen.getByText(/Model\/Thing\.php:12/)).toBeInTheDocument();
    expect(screen.getByText("An API key was found.")).toBeInTheDocument();
  });

  it("sorts findings by severity, most severe first", () => {
    render(
      <FindingsPreviewList
        findings={[finding({ severity: "info", message: "info one" }), finding({ severity: "blocking", message: "blocking one" })]}
        limit={10}
        footer={null}
      />,
    );

    const messages = screen.getAllByText(/one$/).map((el) => el.textContent);
    expect(messages).toEqual(["blocking one", "info one"]);
  });

  it("does not show an Explain button when moduleId is omitted (hypothetical findings)", () => {
    render(<FindingsPreviewList findings={[finding()]} limit={10} footer={null} />);

    expect(screen.queryByRole("button", { name: /Explain/ })).not.toBeInTheDocument();
  });

  it("shows an Explain button when moduleId is given, and reveals the remediation text on click", async () => {
    fetchMock.mockResolvedValue({ remediation: "Remove the hardcoded key and use a secret manager." });
    const user = userEvent.setup();
    render(<FindingsPreviewList findings={[finding()]} limit={10} footer={null} moduleId={42} />);

    const button = screen.getByRole("button", { name: /Explain/ });
    await user.click(button);

    await waitFor(() =>
      expect(screen.getByText("Remove the hardcoded key and use a secret manager.")).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/modules/42/findings/remediation",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          check_type: "hardcoded_secret",
          file_path: "Model/Thing.php",
          line: 12,
          message: "An API key was found.",
        }),
      }),
    );
    expect(screen.queryByRole("button", { name: /Explain/ })).not.toBeInTheDocument();
  });

  it("shows an error message when the remediation fetch fails", async () => {
    fetchMock.mockRejectedValue(new Error("Monthly LLM budget exceeded"));
    const user = userEvent.setup();
    render(<FindingsPreviewList findings={[finding()]} limit={10} footer={null} moduleId={42} />);

    await user.click(screen.getByRole("button", { name: /Explain/ }));

    await waitFor(() => expect(screen.getByText("Monthly LLM budget exceeded")).toBeInTheDocument());
  });

  it("falls back to a generic error message for a non-Error rejection", async () => {
    fetchMock.mockRejectedValue("boom");
    const user = userEvent.setup();
    render(<FindingsPreviewList findings={[finding()]} limit={10} footer={null} moduleId={42} />);

    await user.click(screen.getByRole("button", { name: /Explain/ }));

    await waitFor(() => expect(screen.getByText("Failed to load.")).toBeInTheDocument());
  });

  it("omits the line number suffix when a finding has no line", () => {
    render(<FindingsPreviewList findings={[finding({ line: null })]} limit={10} footer={null} />);

    expect(screen.getByText("Model/Thing.php")).toBeInTheDocument();
  });

  it("renders the footer when there are more findings than the limit", () => {
    render(
      <FindingsPreviewList
        findings={[finding(), finding({ message: "second" })]}
        limit={1}
        footer={<p>more findings</p>}
      />,
    );

    expect(screen.getByText("more findings")).toBeInTheDocument();
  });
});
