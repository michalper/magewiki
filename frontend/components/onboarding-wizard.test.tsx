import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../test-utils";
import { OnboardingProvider, useOnboarding } from "./onboarding-wizard";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

const DISMISSED_KEY = "mw-onboarding-dismissed";

function HelpButton() {
  const onboarding = useOnboarding();
  return (
    <button type="button" onClick={onboarding.open}>
      reopen
    </button>
  );
}

describe("OnboardingProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ scan_roots: ["/sites/store-a"] });
  });

  it("auto-opens on first visit", () => {
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    expect(screen.getByText("Welcome to MageWiki-AI")).toBeInTheDocument();
  });

  it("does not auto-open once already dismissed", () => {
    localStorage.setItem(DISMISSED_KEY, "true");
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    expect(screen.queryByText("Welcome to MageWiki-AI")).not.toBeInTheDocument();
  });

  it("steps forward through every step, showing live scan-roots data on step 2, and back again", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    expect(screen.getByText("Welcome to MageWiki-AI")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(screen.getByText("Scanning your store")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("/sites/store-a")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("AI features are optional")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("You're all set")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("AI features are optional")).toBeInTheDocument();
  });

  it("shows a message when no scan roots are configured yet", async () => {
    fetchMock.mockResolvedValue({ scan_roots: [] });
    const user = userEvent.setup();
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(screen.getByText("No scan roots configured yet on this deployment.")).toBeInTheDocument(),
    );
  });

  it("dismisses on Got it and remembers the dismissal across a remount", async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Got it" }));

    expect(screen.queryByText("You're all set")).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISSED_KEY)).toBe("true");

    unmount();
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );
    expect(screen.queryByText("Welcome to MageWiki-AI")).not.toBeInTheDocument();
  });

  it("dismisses via the close button and resets back to step 1 for next time", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Scanning your store")).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISSED_KEY)).toBe("true");
  });

  it("lets a consumer reopen the wizard via useOnboarding().open() after dismissal", async () => {
    localStorage.setItem(DISMISSED_KEY, "true");
    const user = userEvent.setup();
    renderWithQueryClient(
      <OnboardingProvider>
        <HelpButton />
      </OnboardingProvider>,
    );

    expect(screen.queryByText("Welcome to MageWiki-AI")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "reopen" }));
    expect(screen.getByText("Welcome to MageWiki-AI")).toBeInTheDocument();
  });

  it("falls back to not auto-opening when localStorage throws (private browsing)", () => {
    const getItemSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderWithQueryClient(
      <OnboardingProvider>
        <p>page content</p>
      </OnboardingProvider>,
    );

    expect(screen.queryByText("Welcome to MageWiki-AI")).not.toBeInTheDocument();
    getItemSpy.mockRestore();
  });

  it("throws when useOnboarding is called outside an OnboardingProvider", () => {
    // Swallow the expected React error-boundary console noise for this one case.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderWithQueryClient(<HelpButton />)).toThrow(
      "useOnboarding must be used within an OnboardingProvider",
    );
    consoleError.mockRestore();
  });
});
