import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../../../test-utils";
import GraphClient from "./GraphClient";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function node(overrides: Partial<Record<string, unknown>> = {}) {
  return { id: "module:2", label: "Vendor_Dep", kind: "module", module_id: 2, ...overrides };
}

function graph(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    center_module_id: 1,
    center_label: "Vendor_Center",
    nodes: [{ id: "module:1", label: "Vendor_Center", kind: "module", module_id: 1 }, node()],
    edges: [{ source: "module:1", target: "module:2", relation: "depends_on" }],
    ...overrides,
  };
}

describe("GraphClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    pushMock.mockReset();
  });

  it("shows a loading state", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithQueryClient(<GraphClient id="1" />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    renderWithQueryClient(<GraphClient id="1" />);
    await waitFor(() => expect(screen.getByText("Failed to load dependency graph.")).toBeInTheDocument());
  });

  it("renders the center label and a link back to module details", async () => {
    fetchMock.mockResolvedValue(graph());
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Center — dependency graph")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "← Module details" })).toHaveAttribute("href", "/modules/1");
  });

  it("navigates to a clickable module node's own graph on click", async () => {
    fetchMock.mockResolvedValue(graph());
    const user = userEvent.setup();
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Go to Vendor_Dep's dependency graph" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Go to Vendor_Dep's dependency graph" }));

    expect(pushMock).toHaveBeenCalledWith("/modules/2/graph");
  });

  it("navigates on Enter and Space keydown", async () => {
    fetchMock.mockResolvedValue(graph());
    const user = userEvent.setup();
    renderWithQueryClient(<GraphClient id="1" />);

    const nodeButton = await screen.findByRole("button", { name: "Go to Vendor_Dep's dependency graph" });
    nodeButton.focus();
    await user.keyboard("{Enter}");
    expect(pushMock).toHaveBeenCalledWith("/modules/2/graph");

    pushMock.mockReset();
    await user.keyboard(" ");
    expect(pushMock).toHaveBeenCalledWith("/modules/2/graph");
  });

  it("ignores an unrelated keydown on a graph node", async () => {
    fetchMock.mockResolvedValue(graph());
    const user = userEvent.setup();
    renderWithQueryClient(<GraphClient id="1" />);

    const nodeButton = await screen.findByRole("button", { name: "Go to Vendor_Dep's dependency graph" });
    nodeButton.focus();
    await user.keyboard("a");

    expect(pushMock).not.toHaveBeenCalled();
  });

  it("does not make an external node clickable", async () => {
    fetchMock.mockResolvedValue(
      graph({
        nodes: [
          { id: "module:1", label: "Vendor_Center", kind: "module", module_id: 1 },
          { id: "external:guzzle", label: "guzzlehttp/guzzle", kind: "external", module_id: null },
        ],
        edges: [{ source: "module:1", target: "external:guzzle", relation: "depends_on" }],
      }),
    );
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("guzzlehttp/guzzle")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /guzzlehttp/ })).not.toBeInTheDocument();
  });

  it("falls back to a neutral color for an unknown edge relation", async () => {
    fetchMock.mockResolvedValue(graph({ edges: [{ source: "module:1", target: "module:2", relation: "unknown_relation" }] }));
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Center — dependency graph")).toBeInTheDocument());
    const line = document.querySelector("line");
    expect(line).toHaveAttribute("stroke", "#71717a");
  });

  it("skips an edge referencing a node with no on-graph position", async () => {
    fetchMock.mockResolvedValue(
      graph({ edges: [{ source: "module:1", target: "module:does-not-exist", relation: "depends_on" }] }),
    );
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Center — dependency graph")).toBeInTheDocument());
    expect(document.querySelector("line")).not.toBeInTheDocument();
  });

  it("shows an overflow list beyond 16 neighbors, toggleable, mixing module and external nodes", async () => {
    const neighbors: Record<string, unknown>[] = Array.from({ length: 18 }, (_, i) =>
      node({ id: `module:${i + 2}`, label: `Dep${i}`, module_id: i + 2 }),
    );
    neighbors[17] = { id: "external:last", label: "ExternalLast", kind: "external", module_id: null };
    fetchMock.mockResolvedValue(
      graph({ nodes: [{ id: "module:1", label: "Vendor_Center", kind: "module", module_id: 1 }, ...neighbors], edges: [] }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<GraphClient id="1" />);

    const toggle = await screen.findByText(/more dependencies \(too many to fit on the graph\)/);
    expect(toggle.textContent).toContain("Show 2 more");
    expect(screen.queryByText("Dep16")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(screen.getByText("Dep16")).toBeInTheDocument();
    const overflowLink = screen.getByRole("link", { name: "Dep16" });
    expect(overflowLink).toHaveAttribute("href", "/modules/18/graph");
    expect(screen.getByText("ExternalLast")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "ExternalLast" })).not.toBeInTheDocument();

    expect(toggle.textContent).toContain("Hide");
    await user.click(toggle);
    expect(screen.queryByText("Dep16")).not.toBeInTheDocument();
  });

  it("singularizes the overflow count for exactly one extra dependency", async () => {
    const neighbors = Array.from({ length: 17 }, (_, i) => node({ id: `module:${i + 2}`, label: `Dep${i}`, module_id: i + 2 }));
    fetchMock.mockResolvedValue(
      graph({ nodes: [{ id: "module:1", label: "Vendor_Center", kind: "module", module_id: 1 }, ...neighbors], edges: [] }),
    );
    renderWithQueryClient(<GraphClient id="1" />);

    const toggle = await screen.findByText(/more dependency \(too many to fit on the graph\)/);
    expect(toggle.textContent).toContain("Show 1 more");
  });
});
