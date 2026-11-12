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

  it("defaults to depth 1 and refetches with a new depth when switched", async () => {
    fetchMock.mockResolvedValue(graph());
    const user = userEvent.setup();
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Center — dependency graph")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/modules/1/graph?depth=1");
    expect(screen.getByRole("button", { name: "1" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "2" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/modules/1/graph?depth=2"));
    expect(screen.getByRole("button", { name: "2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "1" })).toHaveAttribute("aria-pressed", "false");
  });

  it("shows a note when the backend truncated the graph", async () => {
    fetchMock.mockResolvedValue(graph({ truncated: true }));
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText(/hit the size limit for one graph/)).toBeInTheDocument());
  });

  it("shows no truncation note when the graph is complete", async () => {
    fetchMock.mockResolvedValue(graph({ truncated: false }));
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Center — dependency graph")).toBeInTheDocument());
    expect(screen.queryByText(/hit the size limit/)).not.toBeInTheDocument();
  });

  it("always shows a live node count, regardless of truncation", async () => {
    fetchMock.mockResolvedValue(graph());
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("2 nodes shown")).toBeInTheDocument());
  });

  it("does not crash and drops the edge when it references an unknown node id", async () => {
    // d3-force's forceLink throws on a dangling link -- the layout step must
    // filter these out itself rather than relying on the render-time
    // from/to lookup that used to be the only guard against this.
    fetchMock.mockResolvedValue(
      graph({ edges: [{ source: "module:1", target: "module:does-not-exist", relation: "depends_on" }] }),
    );
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor_Center — dependency graph")).toBeInTheDocument());
    expect(document.querySelector("line")).not.toBeInTheDocument();
  });

  it("shows a node's full label text rather than truncating it, even when long", async () => {
    const longLabel = "MerchantPanel_OfferReportMaterializedView";
    fetchMock.mockResolvedValue(
      graph({
        nodes: [
          { id: "module:1", label: "Vendor_Center", kind: "module", module_id: 1 },
          node({ label: longLabel }),
        ],
      }),
    );
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText(longLabel)).toBeInTheDocument());
    // Previously a single-line `truncate` box hid most of a long label, only
    // showing it in full on hover via the title attribute -- the node's own
    // rendered text content must now carry the whole name.
    expect(screen.getByText(longLabel).textContent).toBe(longLabel);
  });

  it("renders every node from a large response -- capping the graph is the backend's job now, not the frontend's", async () => {
    const neighbors = Array.from({ length: 30 }, (_, i) =>
      node({ id: `module:${i + 2}`, label: `Dep${i}`, module_id: i + 2 }),
    );
    fetchMock.mockResolvedValue(
      graph({ nodes: [{ id: "module:1", label: "Vendor_Center", kind: "module", module_id: 1 }, ...neighbors], edges: [] }),
    );
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("Dep29")).toBeInTheDocument());
    expect(screen.getByText("Dep0")).toBeInTheDocument();
  });

  it("handles an empty graph (no nodes at all) without crashing", async () => {
    // Also exercises the center-module-not-found case (layoutNodes' own
    // simNodes.find(...) can't find a center in an empty list either) and
    // computeCanvas's !Number.isFinite(minX) fallback (the for-loop over
    // nodes never runs at all, so minX/minY/maxX/maxY all stay at their
    // initial Infinity/-Infinity).
    fetchMock.mockResolvedValue(graph({ nodes: [], edges: [] }));
    renderWithQueryClient(<GraphClient id="1" />);

    await waitFor(() => expect(screen.getByText("0 nodes shown")).toBeInTheDocument());
  });

  it("shows a scroll hint once the canvas is measured wider than its container", async () => {
    // jsdom never measures real layout (scrollWidth/clientWidth are always
    // 0), so canScroll's own effect never naturally sees a canvas wider
    // than its box here -- overriding the two getters on the prototype
    // (rather than one specific DOM node, which React may replace across
    // a refetch) makes every element report "wider than its visible box"
    // regardless of which node the effect ends up reading from.
    const scrollWidthDesc = Object.getOwnPropertyDescriptor(Element.prototype, "scrollWidth")!;
    const clientWidthDesc = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth")!;
    Object.defineProperty(Element.prototype, "scrollWidth", { configurable: true, get: () => 2000 });
    Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => 500 });

    try {
      fetchMock.mockResolvedValue(graph());
      renderWithQueryClient(<GraphClient id="1" />);

      await waitFor(() =>
        expect(screen.getByText("· scroll/drag inside the graph to see the rest")).toBeInTheDocument(),
      );
    } finally {
      Object.defineProperty(Element.prototype, "scrollWidth", scrollWidthDesc);
      Object.defineProperty(Element.prototype, "clientWidth", clientWidthDesc);
    }
  });
});
