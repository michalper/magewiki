import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccessTokenRequiredError } from "@/lib/access-token";
import type { ChatEvent } from "@/lib/chat-types";
import ChatPage from "./page";

vi.mock("@/lib/sse", () => ({ streamSse: vi.fn() }));

import { streamSse } from "@/lib/sse";

const streamSseMock = vi.mocked(streamSse);

describe("ChatPage", () => {
  beforeEach(() => {
    streamSseMock.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("shows the empty-state prompt before any message is sent", () => {
    render(<ChatPage />);
    expect(screen.getByText(/Ask about scanned modules/)).toBeInTheDocument();
  });

  it("sends a question and renders streamed tokens as markdown", async () => {
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({ event: "token", text: "**bold** answer" });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "Do we have a Klaviyo integration?");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(screen.getByText("Do we have a Klaviyo integration?")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("bold")).toBeInTheDocument());
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });

  it("renders lists, links, code, and gfm tables in markdown", async () => {
    const markdown = [
      "- one",
      "- two",
      "",
      "1. first",
      "",
      "[docs](https://example.com)",
      "",
      "`inline code`",
      "",
      "| Mode | Recall |",
      "| --- | --- |",
      "| hybrid | 0.9 |",
    ].join("\n");
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({ event: "token", text: markdown });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "give me everything");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("one").tagName).toBe("LI"));
    expect(screen.getByText("first").closest("ol")).not.toBeNull();
    expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("href", "https://example.com");
    expect(screen.getByText("inline code").tagName).toBe("CODE");
    expect(screen.getByText("Mode").tagName).toBe("TH");
    expect(screen.getByText("hybrid").tagName).toBe("TD");
  });

  it("renders source chips linking to the cited module", async () => {
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({
        event: "sources",
        sources: [
          {
            module_id: 7,
            module_name: "Vendor_Module",
            relative_path: "Plugin/Foo.php",
            score: null,
            semantic_rank: null,
            keyword_rank: null,
            identifier_rank: null,
          },
        ],
      });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("Vendor_Module:Plugin/Foo.php")).toBeInTheDocument());
    const link = screen.getByRole("link", { name: "Vendor_Module:Plugin/Foo.php" });
    expect(link).toHaveAttribute("href", "/modules/7");
    // No retrieval-debug info was sent for this source (every field null) -- no icon.
    expect(screen.queryByLabelText(/How "Vendor_Module" was found/)).not.toBeInTheDocument();
  });

  it("renders a source chip without a relative_path suffix", async () => {
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({
        event: "sources",
        sources: [
          {
            module_id: 3,
            module_name: "Vendor_Other",
            relative_path: null,
            score: null,
            semantic_rank: null,
            keyword_rank: null,
            identifier_rank: null,
          },
        ],
      });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("Vendor_Other")).toBeInTheDocument());
  });

  it("shows a retrieval-debug info trigger for a source with per-signal rank data", async () => {
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({
        event: "sources",
        sources: [
          {
            module_id: 9,
            module_name: "Vendor_Ranked",
            relative_path: null,
            score: 0.03284,
            semantic_rank: 2,
            keyword_rank: null,
            identifier_rank: null,
          },
        ],
      });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(screen.getByLabelText('How "Vendor_Ranked" was found')).toBeInTheDocument(),
    );
  });

  it("omits the RRF score from the retrieval-debug text when it is null", async () => {
    // A source can have real per-signal ranks with no fused RRF score of its
    // own (e.g. a result that only matched one signal) -- every other test
    // here with score: null also has every rank null (skipping this text
    // entirely), so this is the only case that reaches the RRF-score line
    // with score actually null.
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({
        event: "sources",
        sources: [
          {
            module_id: 11,
            module_name: "Vendor_NoScore",
            relative_path: null,
            score: null,
            semantic_rank: 4,
            keyword_rank: null,
            identifier_rank: null,
          },
        ],
      });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(screen.getByLabelText('How "Vendor_NoScore" was found')).toBeInTheDocument(),
    );
  });

  it("renders no source chips for an empty sources list", async () => {
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({ event: "sources", sources: [] });
      onEvent({ event: "token", text: "answer" });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("answer")).toBeInTheDocument());
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a backend error event inline", async () => {
    streamSseMock.mockImplementation(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({ event: "error", detail: "Monthly LLM budget exceeded." });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("Monthly LLM budget exceeded.")).toBeInTheDocument());
  });

  it("shows a generic failure message when the stream rejects", async () => {
    streamSseMock.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByText("Failed to reach the API.")).toBeInTheDocument());
  });

  it("does not show a failure message when the stream is aborted", async () => {
    streamSseMock.mockImplementation(async () => {
      const err = new Error("aborted");
      err.name = "AbortError";
      throw err;
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByLabelText("Chat message")).toBeEnabled());
    expect(screen.queryByText("Failed to reach the API.")).not.toBeInTheDocument();
  });

  it("aborts the in-flight stream on unmount", async () => {
    let capturedSignal: AbortSignal | undefined;
    streamSseMock.mockImplementation(async (_url, _body, _onEvent, signal?: AbortSignal) => {
      capturedSignal = signal;
      await new Promise(() => {});
    });
    const user = userEvent.setup();
    const { unmount } = render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(capturedSignal).toBeDefined());
    unmount();

    expect(capturedSignal?.aborted).toBe(true);
  });

  it("ignores a second submit while already streaming", async () => {
    streamSseMock.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "first");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(streamSseMock).toHaveBeenCalledTimes(1);

    // The input is disabled while streaming, so submit the form directly
    // rather than via a (blocked) user click.
    const form = screen.getByRole("button", { name: "Thinking..." }).closest("form")!;
    fireEvent.submit(form);

    expect(streamSseMock).toHaveBeenCalledTimes(1);
  });

  it("does not submit a blank question", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(streamSseMock).not.toHaveBeenCalled();
  });

  it("switches the audience between pm and dev", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const devButton = screen.getByRole("button", { name: "Dev" });
    const pmButton = screen.getByRole("button", { name: "PM" });
    expect(devButton).toHaveClass("bg-primary");

    await user.click(pmButton);

    expect(pmButton).toHaveClass("bg-primary");
    expect(devButton).not.toHaveClass("bg-primary");

    await user.click(devButton);

    expect(devButton).toHaveClass("bg-primary");
    expect(pmButton).not.toHaveClass("bg-primary");
  });

  it("shows an access-token prompt on a 401 and retries after unlocking", async () => {
    streamSseMock.mockRejectedValueOnce(new AccessTokenRequiredError());
    streamSseMock.mockImplementationOnce(async (_url, _body, onEvent: (e: ChatEvent) => void) => {
      onEvent({ event: "token", text: "answer" });
      onEvent({ event: "done", tokens_in: 1, tokens_out: 1, cost_usd: "0" });
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByLabelText("Access token")).toBeInTheDocument());
    expect(streamSseMock).toHaveBeenCalledTimes(1);

    await user.type(screen.getByLabelText("Access token"), "secret-token");
    await user.click(screen.getByRole("button", { name: "Unlock" }));

    expect(localStorage.getItem("magewiki-access-token")).toBe("secret-token");
    await waitFor(() => expect(screen.getByText("answer")).toBeInTheDocument());
    expect(streamSseMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByLabelText("Access token")).not.toBeInTheDocument();
  });

  it("disables the input and shows a thinking state while streaming", async () => {
    streamSseMock.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText("Chat message"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(screen.getByLabelText("Chat message")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Thinking..." })).toBeDisabled();
  });
});
