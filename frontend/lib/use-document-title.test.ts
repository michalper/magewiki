import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useDocumentTitle } from "./use-document-title";

describe("useDocumentTitle", () => {
  it("sets document.title with the shared suffix", () => {
    renderHook(() => useDocumentTitle("Modules"));
    expect(document.title).toBe("Modules · MageWiki-AI");
  });

  it("updates the title when the value changes", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "First" },
    });
    expect(document.title).toBe("First · MageWiki-AI");

    rerender({ title: "Second" });
    expect(document.title).toBe("Second · MageWiki-AI");
  });
});
