import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../test-utils";
import { OnboardingProvider, useOnboarding } from "./onboarding-wizard";

// A minimal stub standing in for Radix's real Dialog -- the real one never
// calls onOpenChange(true) in this app (there's no DialogTrigger inside it;
// Radix only invokes onOpenChange on a close-originating interaction like
// Escape/overlay-click/DialogClose), so the onOpenChange(true) branches in
// OnboardingDialog and OnboardingProvider's own handleOpenChange are only
// reachable by simulating an open request directly, same as the real
// component's own contract (open: boolean, onOpenChange: (open: boolean) => void).
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({
    open,
    onOpenChange,
    children,
  }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    children: React.ReactNode;
  }) =>
    open ? (
      <div>
        {children}
        <button type="button" onClick={() => onOpenChange(true)}>
          simulate-open-request
        </button>
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn().mockResolvedValue({ scan_roots: [] }) }));

function HelpButton() {
  const onboarding = useOnboarding();
  return (
    <button type="button" onClick={onboarding.open}>
      reopen
    </button>
  );
}

describe("OnboardingDialog/OnboardingProvider onOpenChange(true)", () => {
  beforeEach(() => {
    localStorage.setItem("mw-onboarding-dismissed", "true");
  });

  it("does not reset the step index or the dismissal flag for an open request", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(
      <OnboardingProvider>
        <HelpButton />
      </OnboardingProvider>,
    );

    await user.click(screen.getByRole("button", { name: "reopen" }));
    await user.click(screen.getByRole("button", { name: "simulate-open-request" }));

    expect(localStorage.getItem("mw-onboarding-dismissed")).toBe("true");
  });
});
