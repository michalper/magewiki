import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQueryClient } from "../../test-utils";
import SettingsPage from "./page";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/lib/api";

const fetchMock = vi.mocked(apiFetch);

function settings(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    llm_model: "anthropic/claude-haiku-5-5",
    llm_key_configured: false,
    llm_api_base: null,
    embedding_model: "openai/text-embedding-3-small",
    embedding_key_configured: true,
    embedding_api_base: null,
    ...overrides,
  };
}

describe("SettingsPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("shows a loading state", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithQueryClient(<SettingsPage />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    renderWithQueryClient(<SettingsPage />);
    await waitFor(() => expect(screen.getByText("Failed to load settings.")).toBeInTheDocument());
  });

  it("shows the current model, a custom-key badge, and an api_base when set", async () => {
    fetchMock.mockResolvedValue(settings({ llm_api_base: "http://host.docker.internal:11434" }));
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("anthropic/claude-haiku-5-5")).toBeInTheDocument());
    expect(screen.getByText("http://host.docker.internal:11434")).toBeInTheDocument();
    expect(screen.getByText("using .env default")).toBeInTheDocument();
    expect(screen.getByText("custom key set")).toBeInTheDocument();
  });

  it("saves only the non-blank LLM fields", async () => {
    fetchMock.mockResolvedValue(settings());
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("anthropic/claude-haiku-5-5")).toBeInTheDocument());
    await user.type(screen.getByLabelText("LLM model"), "anthropic/claude-sonnet-5-5");
    await user.type(screen.getByLabelText("LLM API key"), "sk-new-key");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/settings/llm",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            llm_model: "anthropic/claude-sonnet-5-5",
            llm_api_key: "sk-new-key",
          }),
        }),
      ),
    );
  });

  it("does not call the API when saving with every LLM field blank", async () => {
    fetchMock.mockResolvedValue(settings());
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("anthropic/claude-haiku-5-5")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);

    expect(fetchMock).toHaveBeenCalledTimes(1); // only the initial GET
  });

  it("does not call the API when saving with every embedding field blank", async () => {
    fetchMock.mockResolvedValue(settings());
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("openai/text-embedding-3-small")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "Save" })[1]);

    expect(fetchMock).toHaveBeenCalledTimes(1); // only the initial GET
  });

  it("shows the embedding api_base when set", async () => {
    fetchMock.mockResolvedValue(settings({ embedding_api_base: "http://host.docker.internal:11434" }));
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("http://host.docker.internal:11434")).toBeInTheDocument());
  });

  it("falls back to a generic message when the save fails with a non-Error value", async () => {
    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") throw "not an Error instance";
      return settings();
    });
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("anthropic/claude-haiku-5-5")).toBeInTheDocument());
    await user.type(screen.getByLabelText("LLM model"), "anthropic/claude-sonnet-5-5");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() => expect(screen.getByText("Failed to save settings.")).toBeInTheDocument());
  });

  it("resets the LLM settings to the .env default", async () => {
    fetchMock.mockResolvedValue(settings());
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("anthropic/claude-haiku-5-5")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "Reset to .env default" })[0]);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/settings/llm",
        expect.objectContaining({
          body: JSON.stringify({ llm_model: null, llm_api_key: null, llm_api_base: null }),
        }),
      ),
    );
  });

  it("saves only the non-blank embedding fields", async () => {
    fetchMock.mockResolvedValue(settings());
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("openai/text-embedding-3-small")).toBeInTheDocument());
    await user.type(screen.getByLabelText("Embedding model"), "ollama/bge-m3");
    await user.type(screen.getByLabelText("Embedding API key"), "sk-real-secret");
    await user.type(screen.getByLabelText("Embedding API base URL"), "http://host.docker.internal:11434");
    await user.click(screen.getAllByRole("button", { name: "Save" })[1]);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/settings/llm",
        expect.objectContaining({
          body: JSON.stringify({
            embedding_model: "ollama/bge-m3",
            embedding_api_key: "sk-real-secret",
            embedding_api_base: "http://host.docker.internal:11434",
          }),
        }),
      ),
    );
  });

  it("resets the embedding settings to the .env default", async () => {
    fetchMock.mockResolvedValue(settings());
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("openai/text-embedding-3-small")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "Reset to .env default" })[1]);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/settings/llm",
        expect.objectContaining({
          body: JSON.stringify({
            embedding_model: null,
            embedding_api_key: null,
            embedding_api_base: null,
          }),
        }),
      ),
    );
  });

  it("shows the backend's own error message on a failed save", async () => {
    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        throw new Error("changing llm_api_base requires providing llm_api_key again");
      }
      return settings();
    });
    const user = userEvent.setup();
    renderWithQueryClient(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("anthropic/claude-haiku-5-5")).toBeInTheDocument());
    await user.type(screen.getByLabelText("LLM API base URL"), "https://attacker.example");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() =>
      expect(
        screen.getByText("changing llm_api_base requires providing llm_api_key again"),
      ).toBeInTheDocument(),
    );
  });
});
