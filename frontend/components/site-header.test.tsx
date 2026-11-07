import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SiteHeader } from "./site-header";
import { renderWithQueryClient } from "../test-utils";

let pathname = "/modules";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

describe("SiteHeader", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows "API online" once the health check succeeds', async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }),
    );
    renderWithQueryClient(<SiteHeader />);

    expect(screen.getByText("Checking API…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("API online")).toBeInTheDocument());
  });

  it('shows "API unreachable" when the health check fails', async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    renderWithQueryClient(<SiteHeader />);

    await waitFor(() => expect(screen.getByText("API unreachable")).toBeInTheDocument());
  });

  it("marks the active nav link for the current pathname", async () => {
    pathname = "/modules";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    renderWithQueryClient(<SiteHeader />);

    const links = screen.getAllByRole("link", { name: "Modules" });
    expect(links[0]).toHaveClass("bg-accent");
    const chatLinks = screen.getAllByRole("link", { name: "Chat" });
    expect(chatLinks[0]).not.toHaveClass("bg-accent");
  });

  it("also marks the active link for a nested route", async () => {
    pathname = "/modules/42";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    renderWithQueryClient(<SiteHeader />);

    const links = screen.getAllByRole("link", { name: "Modules" });
    expect(links[0]).toHaveClass("bg-accent");
  });

  it("toggles the mobile nav open and closed, and closing it on a link click", async () => {
    pathname = "/modules";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    const user = userEvent.setup();
    renderWithQueryClient(<SiteHeader />);

    const toggle = screen.getByRole("button", { name: "Open menu" });
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toBeInTheDocument();

    const mobileLinks = screen.getAllByRole("link", { name: "Repos" });
    await user.click(mobileLinks[mobileLinks.length - 1]);

    expect(screen.getByRole("button", { name: "Open menu" })).toBeInTheDocument();
  });
});
