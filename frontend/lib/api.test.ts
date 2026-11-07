import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, apiUrl } from "./api";

describe("apiUrl", () => {
  it("defaults to localhost:8000", () => {
    expect(apiUrl()).toBe("http://localhost:8000");
  });
});

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed JSON body on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ hello: "world" }),
      }),
    );

    const result = await apiFetch<{ hello: string }>("/modules");
    expect(result).toEqual({ hello: "world" });
  });

  it("surfaces the backend's own error detail when present", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: "module not found" }),
      }),
    );

    await expect(apiFetch("/modules/999")).rejects.toThrow("module not found");
  });

  it("falls back to a generic message when the body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error("not json");
        },
      }),
    );

    await expect(apiFetch("/modules")).rejects.toThrow("API responded with 500");
  });
});
