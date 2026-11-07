import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SEVERITY_ORDER, SeverityBadge } from "./severity-badge";

describe("SeverityBadge", () => {
  it.each(["blocking", "warning", "info", "ok", "none"] as const)("renders children for severity %s", (severity) => {
    render(<SeverityBadge severity={severity}>label</SeverityBadge>);
    expect(screen.getByText("label")).toBeInTheDocument();
  });
});

describe("SEVERITY_ORDER", () => {
  it("ranks blocking first and none last", () => {
    expect(SEVERITY_ORDER.blocking).toBeLessThan(SEVERITY_ORDER.warning);
    expect(SEVERITY_ORDER.warning).toBeLessThan(SEVERITY_ORDER.info);
    expect(SEVERITY_ORDER.info).toBeLessThan(SEVERITY_ORDER.ok);
    expect(SEVERITY_ORDER.ok).toBeLessThan(SEVERITY_ORDER.none);
  });
});
