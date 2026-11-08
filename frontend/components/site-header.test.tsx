import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OnboardingProvider } from "./onboarding-wizard";
import { SiteHeader } from "./site-header";
import { renderWithQueryClient } from "../test-utils";

let pathname = "/modules";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

// SiteHeader's own Help button needs an OnboardingProvider ancestor in real
// usage (app/providers.tsx always supplies one) -- these tests aren't about
// onboarding, so it's dismissed by default to keep the wizard from popping
// open and crowding every other assertion here.
function renderHeader(ui: React.ReactElement) {
  return renderWithQueryClient(<OnboardingProvider>{ui}</OnboardingProvider>);
}

describe("SiteHeader", () => {
  beforeEach(() => {
    localStorage.setItem("mw-onboarding-dismissed", "true");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('shows "API online" once the health check succeeds', async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }),
    );
    renderHeader(<SiteHeader />);

    expect(screen.getByText("Checking API…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("API online")).toBeInTheDocument());
  });

  it('shows "API unreachable" when the health check fails', async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    renderHeader(<SiteHeader />);

    await waitFor(() => expect(screen.getByText("API unreachable")).toBeInTheDocument());
  });

  it("marks the active nav link for the current pathname", async () => {
    pathname = "/modules";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    renderHeader(<SiteHeader />);

    const links = screen.getAllByRole("link", { name: "Modules" });
    expect(links[0]).toHaveClass("bg-accent");
    const chatLinks = screen.getAllByRole("link", { name: "Chat" });
    expect(chatLinks[0]).not.toHaveClass("bg-accent");
  });

  it("also marks the active link for a nested route", async () => {
    pathname = "/modules/42";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    renderHeader(<SiteHeader />);

    const links = screen.getAllByRole("link", { name: "Modules" });
    expect(links[0]).toHaveClass("bg-accent");
  });

  it("toggles the mobile nav open and closed, and closing it on a link click", async () => {
    pathname = "/modules";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    const user = userEvent.setup();
    renderHeader(<SiteHeader />);

    const toggle = screen.getByRole("button", { name: "Open menu" });
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toBeInTheDocument();

    const mobileLinks = screen.getAllByRole("link", { name: "Repos" });
    await user.click(mobileLinks[mobileLinks.length - 1]);

    expect(screen.getByRole("button", { name: "Open menu" })).toBeInTheDocument();
  });

  it('reopens the onboarding wizard from the "Show setup guide" button', async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    const user = userEvent.setup();
    renderHeader(<SiteHeader />);

    expect(screen.queryByText("Welcome to MageWiki-AI")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show setup guide" }));
    expect(screen.getByText("Welcome to MageWiki-AI")).toBeInTheDocument();
  });
});
