import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/modules",
}));

// next/font/google's real functions only work inside Next's own SWC build
// pipeline (font optimization happens at build time) -- outside of it, they
// throw. A fake with the same shape (a `variable` className string) is all
// RootLayout actually uses.
vi.mock("next/font/google", () => ({
  Geist: () => ({ variable: "--font-geist-sans" }),
  Geist_Mono: () => ({ variable: "--font-geist-mono" }),
}));

describe("RootLayout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the html/body shell with the site header and children", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) }));
    const { default: RootLayout } = await import("./layout");

    const html = renderToStaticMarkup(
      RootLayout({ children: <div>page content</div>, params: Promise.resolve({}) }) as React.ReactElement,
    );

    expect(html).toContain("page content");
    expect(html).toContain("MageWiki-AI");
  });
});
