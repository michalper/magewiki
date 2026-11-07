import { afterEach, describe, expect, it, vi } from "vitest";

describe("DependencyGraphPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("generateMetadata uses the real module name on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ name: "Vendor_Module" }) }));
    const { generateMetadata } = await import("./page");

    const metadata = await generateMetadata({ params: Promise.resolve({ id: "42" }) });

    expect(metadata).toEqual({ title: "Vendor_Module — Graph" });
  });

  it("generateMetadata falls back to a generic title when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));
    const { generateMetadata } = await import("./page");

    const metadata = await generateMetadata({ params: Promise.resolve({ id: "42" }) });

    expect(metadata).toEqual({ title: "Module 42 — Graph" });
  });

  it("generateMetadata falls back to a generic title on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const { generateMetadata } = await import("./page");

    const metadata = await generateMetadata({ params: Promise.resolve({ id: "99" }) });

    expect(metadata).toEqual({ title: "Module 99 — Graph" });
  });

  it("renders GraphClient with the resolved id", async () => {
    const page = (await import("./page")).default;
    const element = await page({ params: Promise.resolve({ id: "7" }) });

    expect(element.props.id).toBe("7");
  });
});
