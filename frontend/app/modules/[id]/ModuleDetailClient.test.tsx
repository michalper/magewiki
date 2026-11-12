import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../../test-utils";
import ModuleDetailClient from "./ModuleDetailClient";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiUrl: () => "http://localhost:8000" }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function moduleDetail(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    name: "Vendor_Module",
    repo_root: "/sites/store-a",
    enabled: true,
    state: "up_to_date",
    has_readme: true,
    has_tests: true,
    tags: [],
    composer_name: "vendor/module",
    setup_version: "1.0.0",
    license: null,
    homepage: null,
    authors: [],
    php_extensions: [],
    composer_scripts: [],
    composer_autoload_psr4: {},
    composer_allow_plugins: {},
    dependencies: [],
    last_scanned_at: "2026-01-01T00:00:00Z",
    plugins: [],
    observers: [],
    config_fields: [],
    quality_findings: [],
    ...overrides,
  };
}

function mockApis({
  module = moduleDetail(),
  readme,
  modules = [],
  history = [],
}: {
  module?: ReturnType<typeof moduleDetail>;
  readme?: string | Error;
  modules?: unknown[];
  history?: unknown[];
} = {}) {
  fetchMock.mockImplementation(async (path: string) => {
    if (path === "/modules") return modules;
    if (path.endsWith("/graph")) return {};
    if (path.endsWith("/history")) return history;
    return module;
  });
  const readmeBody = readme === undefined ? "" : readme instanceof Error ? "" : readme;
  const readmeStatus = readme === undefined ? 404 : readme instanceof Error ? 500 : 200;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      status: readmeStatus,
      ok: readmeStatus === 200,
      text: async () => readmeBody,
    }),
  );
}

describe("ModuleDetailClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the module loads", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    renderWithQueryClient(<ModuleDetailClient id="1" />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows an error state when the module fails to load", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 404, ok: false, text: async () => "" }));
    renderWithQueryClient(<ModuleDetailClient id="1" />);
    await waitFor(() => expect(screen.getByText("Failed to load module.")).toBeInTheDocument());
  });

  it("renders the header card's badges, tags, and dl fields", async () => {
    mockApis({
      module: moduleDetail({
        tags: ["payments", "checkout"],
        license: ["MIT", "OSL-3.0"],
        authors: ["Jane Doe <jane@example.com>"],
        php_extensions: ["soap", "curl"],
      }),
    });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Vendor_Module" })).toBeInTheDocument());
    expect(screen.getByText("Enabled: yes")).toBeInTheDocument();
    expect(screen.getByText("State: up_to_date")).toBeInTheDocument();
    expect(screen.getByText("README")).toBeInTheDocument();
    expect(screen.getByText("tests")).toBeInTheDocument();
    expect(screen.getByText("payments")).toBeInTheDocument();
    expect(screen.getByText("checkout")).toBeInTheDocument();
    expect(screen.getByText("vendor/module")).toBeInTheDocument();
    expect(screen.getByText("1.0.0")).toBeInTheDocument();
    expect(screen.getByText("MIT, OSL-3.0")).toBeInTheDocument();
    expect(screen.getByText("Jane Doe <jane@example.com>")).toBeInTheDocument();
    expect(screen.getByText("soap, curl")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View dependency graph →" })).toHaveAttribute(
      "href",
      "/modules/1/graph",
    );
  });

  it("shows a passing PHPUnit badge with coverage when phpunit was executed", async () => {
    mockApis({
      module: moduleDetail({ phpunit_tests_run: 42, phpunit_tests_failed: 0, phpunit_coverage_percent: 87.5 }),
    });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByText("42 tests passed · 87.5% coverage")).toBeInTheDocument());
  });

  it("shows a failing PHPUnit badge when some tests failed", async () => {
    mockApis({
      module: moduleDetail({ phpunit_tests_run: 10, phpunit_tests_failed: 2, phpunit_coverage_percent: 60 }),
    });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByText("2/10 tests failed · 60% coverage")).toBeInTheDocument());
  });

  it("omits the PHPUnit badge entirely when it was never executed", async () => {
    mockApis({ module: moduleDetail() });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Vendor_Module" })).toBeInTheDocument());
    expect(screen.queryByText(/tests passed|tests failed/)).not.toBeInTheDocument();
  });

  it("shows em-dashes and singular badges for a minimal module", async () => {
    mockApis({ module: moduleDetail({ enabled: null, has_readme: false, has_tests: false, composer_name: null, setup_version: null }) });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByText("Enabled: unknown")).toBeInTheDocument());
    expect(screen.getByText("no README")).toBeInTheDocument();
    expect(screen.getByText("no tests")).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(2); // composer + version
  });

  it("links the homepage only when it is http(s)", async () => {
    mockApis({ module: moduleDetail({ homepage: "https://example.com" }) });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByRole("link", { name: "https://example.com" })).toBeInTheDocument());
  });

  it("renders a javascript: homepage as plain text, not a link", async () => {
    mockApis({ module: moduleDetail({ homepage: "javascript:alert(1)" }) });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "javascript:alert(1)" })).not.toBeInTheDocument();
  });

  it('shows "Author" singular for one author', async () => {
    mockApis({ module: moduleDetail({ authors: ["Solo Dev"] }) });
    renderWithQueryClient(<ModuleDetailClient id="1" />);
    await waitFor(() => expect(screen.getByText("Author")).toBeInTheDocument());
  });

  it('shows "Authors" plural for several authors', async () => {
    mockApis({ module: moduleDetail({ authors: ["Dev One", "Dev Two"] }) });
    renderWithQueryClient(<ModuleDetailClient id="1" />);
    await waitFor(() => expect(screen.getByText("Authors")).toBeInTheDocument());
  });

  it("renders composer scripts, autoload psr-4 paths, and allow-plugins", async () => {
    mockApis({
      module: moduleDetail({
        composer_scripts: ["cs-fix", "test"],
        composer_autoload_psr4: { "Vendor\\Module\\": "src/" },
        composer_allow_plugins: { "dealerdirect/phpcodesniffer-composer-installer": true, "some/plugin": false },
      }),
    });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByText("Composer scripts")).toBeInTheDocument());
    expect(screen.getByText("cs-fix, test")).toBeInTheDocument();
    expect(screen.getByText("Autoload (PSR-4)")).toBeInTheDocument();
    expect(screen.getByText("Vendor\\Module\\ → src/")).toBeInTheDocument();
    expect(screen.getByText("Allow-plugins")).toBeInTheDocument();
    expect(
      screen.getByText("dealerdirect/phpcodesniffer-composer-installer: allowed, some/plugin: denied"),
    ).toBeInTheDocument();
  });

  it("falls back to '.' for an empty autoload psr-4 path (package root)", async () => {
    mockApis({
      module: moduleDetail({ composer_autoload_psr4: { "Vendor\\Module\\": "" } }),
    });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByText("Vendor\\Module\\ → .")).toBeInTheDocument());
  });

  it("omits the composer-scripts/autoload/allow-plugins rows entirely when none are present", async () => {
    mockApis({ module: moduleDetail() });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Vendor_Module" })).toBeInTheDocument());
    expect(screen.queryByText("Composer scripts")).not.toBeInTheDocument();
    expect(screen.queryByText("Autoload (PSR-4)")).not.toBeInTheDocument();
    expect(screen.queryByText("Allow-plugins")).not.toBeInTheDocument();
  });

  it("links a dependency that resolves to a module in the same repo, plain text otherwise", async () => {
    mockApis({
      module: moduleDetail({ dependencies: ["Magento_Sales", "Vendor_Unscanned"] }),
      modules: [
        { id: 5, name: "Magento_Sales", repo_root: "/sites/store-a" },
        { id: 6, name: "Magento_Sales", repo_root: "/sites/store-b" },
      ],
    });
    renderWithQueryClient(<ModuleDetailClient id="1" />);

    await waitFor(() => expect(screen.getByRole("link", { name: "Magento_Sales" })).toHaveAttribute("href", "/modules/5"));
    expect(screen.getByText("Vendor_Unscanned")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Vendor_Unscanned" })).not.toBeInTheDocument();
  });

  describe("README", () => {
    it("shows a loading placeholder while the README fetches", () => {
      fetchMock.mockImplementation(async (path: string) => (path === "/modules" ? [] : moduleDetail()));
      vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      return waitFor(() =>
        expect(screen.getByText("Loading...", { selector: "p" })).toBeInTheDocument(),
      );
    });

    it("shows a not-analyzed placeholder on a 404", async () => {
      mockApis(); // readme undefined -> 404
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() =>
        expect(screen.getByText("This module has not been analyzed yet.")).toBeInTheDocument(),
      );
    });

    it("splits the README into section cards, drops the duplicate Tags section, and links a dependency mention", async () => {
      const readme = [
        "# Vendor_Module (vendor/module)",
        "",
        "Summary line.",
        "",
        "## Description",
        "",
        "Full description.",
        "",
        "## Tags",
        "",
        "`payments`",
        "",
        "## Risks",
        "",
        "- **[high]** Something risky.",
        "",
        "## Dependencies",
        "",
        "- Magento_Sales",
      ].join("\n");
      mockApis({
        module: moduleDetail({ dependencies: ["Magento_Sales"] }),
        readme,
        modules: [{ id: 5, name: "Magento_Sales", repo_root: "/sites/store-a" }],
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByRole("heading", { name: "Description" })).toBeInTheDocument());
      expect(screen.queryByRole("heading", { name: "Tags" })).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Risks" })).toBeInTheDocument();
      expect(screen.getByText("high")).toBeInTheDocument(); // risk severity badge
      // Appears twice: once in the header's "Depends on" row, once in the
      // README's own "Dependencies" list item (linked via the same idByName map).
      for (const link of screen.getAllByRole("link", { name: "Magento_Sales" })) {
        expect(link).toHaveAttribute("href", "/modules/5");
      }
      // Section nav chips (more than one section)
      expect(screen.getByRole("link", { name: "Description" })).toHaveAttribute("href", "#readme-description");
    });

    it("renders ordinary bold text as plain <strong>, not a risk-severity badge, when it has nested markup", async () => {
      // "**bold _and_ text**" gives react-markdown's strong renderer an array
      // of children (text + an <em> element), not a single string -- distinct
      // from the "[high]"-style risk tag case above, which is always a lone
      // string child.
      mockApis({ readme: "A paragraph with **bold _and_ text** in it." });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("and", { exact: false })).toBeInTheDocument());
      const strongEl = screen.getByText("bold", { exact: false }).closest("strong");
      expect(strongEl).toBeInTheDocument();
      expect(strongEl).toHaveClass("font-semibold");
    });

    it("hides the section nav chips when there is only one section", async () => {
      mockApis({ readme: "Just one paragraph, no headings." });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("Just one paragraph, no headings.")).toBeInTheDocument());
      expect(screen.queryByRole("link", { name: "Overview" })).not.toBeInTheDocument();
    });

    it("renders Plugins/Observers/Configuration from structured data instead of the raw markdown prose", async () => {
      const readme = [
        "## Plugins",
        "",
        "SamplePlugin intercepts Foo via Bar (raw prose, should not render)",
        "",
        "## Observers",
        "",
        "SampleObserver listens for baz (raw prose, should not render)",
        "",
        "## Configuration",
        "",
        "some/raw/path (raw prose, should not render)",
      ].join("\n");
      mockApis({
        module: moduleDetail({
          plugins: [{ plugin_name: "SamplePlugin", intercepted_type: "Vendor\\Foo", plugin_class: "Vendor\\Plugin\\Sample" }],
          observers: [{ observer_name: "SampleObserver", event_name: "sales_order_save_after", observer_class: "Vendor\\Observer\\Sample" }],
          config_fields: [{ section_id: "vendor_module", group_id: "general", field_id: "enabled", label: "Enabled", field_type: "select" }],
        }),
        readme,
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("SamplePlugin")).toBeInTheDocument());
      expect(screen.getByText("Vendor\\Foo")).toBeInTheDocument();
      expect(screen.getByText("SampleObserver")).toBeInTheDocument();
      expect(screen.getByText("sales_order_save_after")).toBeInTheDocument();
      expect(screen.getByText("vendor_module")).toBeInTheDocument();
      expect(screen.getByText("Enabled")).toBeInTheDocument();
      expect(screen.queryByText(/raw prose, should not render/)).not.toBeInTheDocument();
    });

    it("falls back to the field_id when a config field has no label, and omits the type suffix when unset", async () => {
      mockApis({
        module: moduleDetail({
          // A second field in the exact same section+group -- exercises the
          // "this section/group was already seen" branch of the grouping
          // loop, not just "first field creates a new section and group."
          config_fields: [
            { section_id: "vendor_module", group_id: "general", field_id: "raw_field", label: null, field_type: null },
            { section_id: "vendor_module", group_id: "general", field_id: "second_field", label: "Second", field_type: "text" },
          ],
        }),
        readme: "## Configuration\n\nraw",
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("raw_field")).toBeInTheDocument());
      expect(screen.getByTitle("vendor_module/general/raw_field")).toBeInTheDocument();
      expect(screen.getByText("Second")).toBeInTheDocument();
    });

    it("falls back to the raw markdown for Plugins/Observers/Configuration when there is no structured data", async () => {
      mockApis({ readme: "## Plugins\n\nNo structured plugins exist for this module." });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() =>
        expect(screen.getByText("No structured plugins exist for this module.")).toBeInTheDocument(),
      );
    });

    it("collapses a long section behind a Show more/Show less toggle", async () => {
      const longBody = "x".repeat(700);
      mockApis({ readme: `## Long section\n\n${longBody}` });
      const user = userEvent.setup();
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      const toggle = await screen.findByRole("button", { name: "Show more" });
      await user.click(toggle);
      expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
    });

    it("does not show a toggle for a short section", async () => {
      mockApis({ readme: "## Short section\n\nJust a little text." });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("Just a little text.")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
    });

    it("renders an h3 sub-heading, an ordered list, a gfm table, and plain bold text in a section body", async () => {
      const readme = [
        "## For developers",
        "",
        "### Sub-heading",
        "",
        "1. First step",
        "2. Second step",
        "",
        "Some **plain bold** text.",
        "",
        "See the [docs](https://example.com) and `inline code`.",
        "",
        "| Mode | Recall |",
        "| --- | --- |",
        "| hybrid | 0.9 |",
      ].join("\n");
      mockApis({ readme });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("Sub-heading")).toBeInTheDocument());
      expect(screen.getByText("Sub-heading").tagName).toBe("H4");
      expect(screen.getByText("First step").closest("ol")).not.toBeNull();
      expect(screen.getByText("plain bold").tagName).toBe("STRONG");
      expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("href", "https://example.com");
      expect(screen.getByText("inline code").tagName).toBe("CODE");
      expect(screen.getByText("Mode").tagName).toBe("TH");
      expect(screen.getByText("hybrid").tagName).toBe("TD");
    });

    it("surfaces a real fetch error (not 404) as the module-level error state", async () => {
      fetchMock.mockImplementation(async (path: string) => (path === "/modules" ? [] : moduleDetail()));
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ status: 500, ok: false, text: async () => "" }),
      );
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByRole("heading", { name: "Vendor_Module" })).toBeInTheDocument());
      // The README query fails independently of the module query -- it just
      // never renders a README section, no page-level crash.
      expect(screen.queryByText("This module has not been analyzed yet.")).not.toBeInTheDocument();
    });

    it("collapses Plugins/Observers/Configuration cards past their own item-count thresholds", async () => {
      const plugins = Array.from({ length: 6 }, (_, i) => ({
        plugin_name: `Plugin${i}`,
        intercepted_type: "Vendor\\X",
        plugin_class: "Vendor\\Plugin\\X",
      }));
      mockApis({ module: moduleDetail({ plugins }), readme: "## Plugins\n\nraw" });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await screen.findByText("Plugin0");
      expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
    });
  });

  describe("quality findings", () => {
    function finding(overrides: Partial<Record<string, unknown>> = {}) {
      return { check_type: "hardcoded_secret", severity: "blocking", file_path: "Model/Foo.php", line: 10, message: "hardcoded secret found", ...overrides };
    }

    it("hides the quality findings card entirely when there are none", async () => {
      mockApis();
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByRole("heading", { name: "Vendor_Module" })).toBeInTheDocument());
      expect(screen.queryByText(/Quality findings/)).not.toBeInTheDocument();
    });

    it("sorts findings by severity and shows a preview count", async () => {
      mockApis({
        module: moduleDetail({
          quality_findings: [
            finding({ severity: "warning", message: "a warning" }),
            finding({ severity: "blocking", message: "a blocker" }),
          ],
        }),
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText(/most severe 2 of 2/)).toBeInTheDocument());
      const items = screen.getAllByText(/^(a blocker|a warning)$/);
      expect(items[0]).toHaveTextContent("a blocker"); // blocking sorts before warning
    });

    it('shows a file_path without a line suffix when line is null', async () => {
      mockApis({ module: moduleDetail({ quality_findings: [finding({ line: null, file_path: "composer.json" })] }) });
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText("composer.json")).toBeInTheDocument());
    });

    it("shows a +N more line beyond the preview count and lets CSV export be triggered", async () => {
      const findings = Array.from({ length: 12 }, (_, i) => finding({ message: `finding ${i}`, file_path: `F${i}.php` }));
      mockApis({ module: moduleDetail({ quality_findings: findings }) });
      const user = userEvent.setup();
      renderWithQueryClient(<ModuleDetailClient id="1" />);

      await waitFor(() => expect(screen.getByText(/\+2 more/)).toBeInTheDocument());

      const createObjectURL = vi.fn().mockReturnValue("blob:fake");
      vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      await user.click(screen.getByRole("button", { name: "Export findings CSV" }));

      expect(clickSpy).toHaveBeenCalled();
      clickSpy.mockRestore();
    });
  });

  describe("History", () => {
    it("renders nothing when there are no snapshots yet", async () => {
      mockApis({ history: [] });
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByRole("heading", { name: "Vendor_Module" })).toBeInTheDocument());
      expect(screen.queryByText("History")).not.toBeInTheDocument();
    });

    it("shows a single baseline entry as such, with no delta", async () => {
      mockApis({
        history: [
          {
            scanned_at: "2026-01-01T00:00:00Z",
            current_hash: "hash-a",
            state: "up_to_date",
            enabled: true,
            finding_counts: { phpstan_error: 3 },
          },
        ],
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByText("History")).toBeInTheDocument());
      expect(screen.getByText("First recorded scan — baseline.")).toBeInTheDocument();
    });

    it("shows hash/state/enabled changes and per-check-type deltas between consecutive entries", async () => {
      mockApis({
        history: [
          {
            scanned_at: "2026-02-01T00:00:00Z",
            current_hash: "hash-b",
            state: "failed",
            enabled: false,
            finding_counts: { phpstan_error: 5, security_advisory: 1 },
          },
          {
            scanned_at: "2026-01-01T00:00:00Z",
            current_hash: "hash-a",
            state: "up_to_date",
            enabled: true,
            // graphql_field_conflict only ever appears here, on the older
            // entry -- exercises current.finding_counts[checkType] ?? 0's
            // own fallback (a check_type fully resolved away, not merely
            // decreased), the mirror case of security_advisory appearing
            // only on the newer entry below.
            finding_counts: { phpstan_error: 2, graphql_field_conflict: 1 },
          },
        ],
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByText("History")).toBeInTheDocument());

      expect(screen.getByText("Code changed (new hash).")).toBeInTheDocument();
      expect(screen.getByText("State changed to “failed”.")).toBeInTheDocument();
      expect(screen.getByText("Enabled status changed to false.")).toBeInTheDocument();
      expect(screen.getByText(/▲ phpstan_error \+3/)).toBeInTheDocument();
      expect(screen.getByText(/▲ security_advisory \+1/)).toBeInTheDocument();
      expect(screen.getByText(/▼ graphql_field_conflict -1/)).toBeInTheDocument();
    });

    it("shows an unknown enabled status change and reports no change when nothing differs", async () => {
      mockApis({
        history: [
          {
            scanned_at: "2026-03-01T00:00:00Z",
            current_hash: "hash-c",
            state: "up_to_date",
            enabled: null,
            finding_counts: {},
          },
          {
            scanned_at: "2026-02-01T00:00:00Z",
            current_hash: "hash-c",
            state: "up_to_date",
            enabled: true,
            finding_counts: {},
          },
          {
            scanned_at: "2026-01-01T00:00:00Z",
            current_hash: "hash-c",
            state: "up_to_date",
            enabled: true,
            finding_counts: {},
          },
        ],
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByText("History")).toBeInTheDocument());

      expect(screen.getByText("Enabled status changed to unknown.")).toBeInTheDocument();
      expect(screen.getByText("No change.")).toBeInTheDocument();
    });

    it("shows a resolved finding as a decreasing delta and reports no change when nothing differs", async () => {
      mockApis({
        history: [
          {
            scanned_at: "2026-02-01T00:00:00Z",
            current_hash: "hash-a",
            state: "up_to_date",
            enabled: true,
            finding_counts: { phpstan_error: 1 },
          },
          {
            scanned_at: "2026-01-01T00:00:00Z",
            current_hash: "hash-a",
            state: "up_to_date",
            enabled: true,
            finding_counts: { phpstan_error: 4 },
          },
        ],
      });
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByText("History")).toBeInTheDocument());

      expect(screen.getByText(/▼ phpstan_error -3/)).toBeInTheDocument();
    });

    it("truncates to the preview count and says so when there are more entries", async () => {
      const history = Array.from({ length: 25 }, (_, i) => ({
        scanned_at: `2026-01-${String(i + 1).padStart(2, "0")}T00:00:00Z`,
        current_hash: `hash-${i}`,
        state: "up_to_date",
        enabled: true,
        finding_counts: {},
      }));
      mockApis({ history });
      renderWithQueryClient(<ModuleDetailClient id="1" />);
      await waitFor(() => expect(screen.getByText(/most recent 20 of 25/)).toBeInTheDocument());
    });
  });
});
