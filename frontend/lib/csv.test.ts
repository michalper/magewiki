import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadCsv, escapeCsvField, toCsv } from "./csv";

describe("escapeCsvField", () => {
  it("passes plain text through unchanged", () => {
    expect(escapeCsvField("Vendor_Module")).toBe("Vendor_Module");
  });

  it("returns an empty string for null/undefined", () => {
    expect(escapeCsvField(null)).toBe("");
    expect(escapeCsvField(undefined)).toBe("");
  });

  it("quotes a field containing a comma, quote, or newline", () => {
    expect(escapeCsvField("a,b")).toBe('"a,b"');
    expect(escapeCsvField('a"b')).toBe('"a""b"');
    expect(escapeCsvField("a\nb")).toBe('"a\nb"');
  });

  it.each(["=HYPERLINK(http://evil)", "+1+1", "-1+1", "@SUM(A1)"])(
    "neutralizes a leading formula-trigger character: %s",
    (value) => {
      expect(escapeCsvField(value).startsWith("'")).toBe(true);
    },
  );

  it("still neutralizes a formula when the value also needs quoting for a comma/quote", () => {
    expect(escapeCsvField('=HYPERLINK("http://evil")')).toBe('"\'=HYPERLINK(""http://evil"")"');
  });

  it("does not mangle a value that merely contains, but doesn't start with, those characters", () => {
    expect(escapeCsvField("a=b")).toBe("a=b");
  });
});

describe("toCsv", () => {
  it("joins headers and rows with commas and newlines", () => {
    expect(toCsv(["a", "b"], [[1, "x"], [2, "y,z"]])).toBe('a,b\n1,x\n2,"y,z"');
  });
});

describe("downloadCsv", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates an object URL, clicks a download link, then revokes the URL", () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:fake-url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    downloadCsv("modules.csv", "a,b\n1,2");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");

    vi.unstubAllGlobals();
  });
});
