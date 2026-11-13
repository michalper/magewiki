"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AccessTokenPrompt } from "@/components/access-token-gate";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import { AccessTokenRequiredError } from "@/lib/access-token";
import type { components } from "@/lib/api-types";
import { useDocumentTitle } from "@/lib/use-document-title";

type LlmSettingsResponse = components["schemas"]["LlmSettingsResponse"];
type LlmSettingsUpdate = components["schemas"]["LlmSettingsUpdate"];

async function fetchSettings(): Promise<LlmSettingsResponse> {
  return apiFetch("/settings/llm");
}

async function patchSettings(update: LlmSettingsUpdate): Promise<LlmSettingsResponse> {
  // The backend's 400s here are actionable (e.g. "re-enter the key to change the
  // host" from the api_base/api_key coupling security check) — apiFetch already
  // surfaces the real message instead of a generic "failed to save".
  return apiFetch("/settings/llm", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
}

function KeyBadge({ configured }: { configured: boolean }) {
  return configured ? (
    <Badge variant="default">custom key set</Badge>
  ) : (
    <Badge variant="outline">using .env default</Badge>
  );
}

export default function SettingsPage() {
  useDocumentTitle("Settings");
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["llm-settings"], queryFn: fetchSettings });

  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmApiBase, setLlmApiBase] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingApiKey, setEmbeddingApiKey] = useState("");
  const [embeddingApiBase, setEmbeddingApiBase] = useState("");

  const [pendingEmbeddingUpdate, setPendingEmbeddingUpdate] = useState<LlmSettingsUpdate | null>(null);

  const patchMutation = useMutation({
    mutationFn: patchSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-settings"] });
      setLlmApiKey("");
      setEmbeddingApiKey("");
      setPendingEmbeddingUpdate(null);
    },
  });

  function saveLlm() {
    const update: Partial<LlmSettingsUpdate> = {};
    if (llmModel.trim()) update.llm_model = llmModel.trim();
    if (llmApiKey.trim()) update.llm_api_key = llmApiKey.trim();
    if (llmApiBase.trim()) update.llm_api_base = llmApiBase.trim();
    if (Object.keys(update).length > 0) patchMutation.mutate({ ...update, confirm_reembed: false });
  }

  // embedding_model changes alone can require confirm_reembed (see
  // CLAUDE.md's "Re-embed workflow on embedding-model change") — the backend
  // 400s with an actionable message instead of silently re-embedding a
  // potentially large, billable fleet. Remember the attempted update so a
  // "Confirm re-embed" button can resend it with confirm_reembed: true
  // rather than making the user retype everything.
  function saveEmbedding(confirmReembed = false) {
    const update: Partial<LlmSettingsUpdate> = {};
    if (embeddingModel.trim()) update.embedding_model = embeddingModel.trim();
    if (embeddingApiKey.trim()) update.embedding_api_key = embeddingApiKey.trim();
    if (embeddingApiBase.trim()) update.embedding_api_base = embeddingApiBase.trim();
    if (Object.keys(update).length === 0) return;
    const full: LlmSettingsUpdate = { ...update, confirm_reembed: confirmReembed };
    setPendingEmbeddingUpdate(full);
    patchMutation.mutate(full);
  }

  const needsToken = patchMutation.isError && patchMutation.error instanceof AccessTokenRequiredError;

  const reembedConfirmMessage =
    patchMutation.isError &&
    patchMutation.error instanceof Error &&
    patchMutation.error.message.includes("confirm_reembed: true")
      ? patchMutation.error.message
      : null;

  return (
    <div className="flex flex-col flex-1 gap-8 p-8 max-w-2xl mx-auto w-full" suppressHydrationWarning>
      {/* suppressHydrationWarning above: see app/modules/page.tsx's own
          top-level div for the full explanation -- the onboarding wizard's
          first-visit dialog marks this div inert via a direct DOM write
          Next's hydration-diff otherwise flags as a false mismatch. */}
      <h1 className="text-2xl font-semibold tracking-tight">Settings — BYOK</h1>
      <p className="text-sm text-muted-foreground">
        Override the model and API key used for chat/analysis and embeddings, without editing{" "}
        <code>.env</code> or restarting containers. Leaving a field blank keeps the current value;
        use &ldquo;Reset to .env default&rdquo; to clear an override.
      </p>

      {settingsQuery.isLoading && <p>Loading...</p>}
      {settingsQuery.isError && <p className="text-destructive">Failed to load settings.</p>}

      {settingsQuery.data && (
        <>
          <section className="flex flex-col gap-3 rounded-2xl bg-card p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">LLM (chat / analysis)</h2>
              <KeyBadge configured={settingsQuery.data.llm_key_configured} />
            </div>
            <p className="text-sm text-muted-foreground">
              Current: <span className="font-mono">{settingsQuery.data.llm_model}</span>
              {settingsQuery.data.llm_api_base && (
                <>
                  {" "}
                  @ <span className="font-mono">{settingsQuery.data.llm_api_base}</span>
                </>
              )}
            </p>
            <Input
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              placeholder="e.g. anthropic/claude-haiku-5-5, or ollama_chat/llama3.1"
              aria-label="LLM model"
              className="font-mono"
            />
            <Input
              type="password"
              value={llmApiKey}
              onChange={(e) => setLlmApiKey(e.target.value)}
              placeholder="API key — leave blank to keep current key"
              aria-label="LLM API key"
            />
            <Input
              value={llmApiBase}
              onChange={(e) => setLlmApiBase(e.target.value)}
              placeholder="API base URL (optional — for Ollama, e.g. http://host.docker.internal:11434)"
              aria-label="LLM API base URL"
              className="font-mono"
            />
            <div className="flex gap-2">
              <Button onClick={saveLlm} disabled={patchMutation.isPending}>
                Save
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  patchMutation.mutate({
                    llm_model: null,
                    llm_api_key: null,
                    llm_api_base: null,
                    confirm_reembed: false,
                  })
                }
                disabled={patchMutation.isPending}
              >
                Reset to .env default
              </Button>
            </div>
          </section>

          <section className="flex flex-col gap-3 rounded-2xl bg-card p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">Embeddings</h2>
              <KeyBadge configured={settingsQuery.data.embedding_key_configured} />
            </div>
            <p className="text-sm text-muted-foreground">
              Current: <span className="font-mono">{settingsQuery.data.embedding_model}</span>
              {settingsQuery.data.embedding_api_base && (
                <>
                  {" "}
                  @ <span className="font-mono">{settingsQuery.data.embedding_api_base}</span>
                </>
              )}
            </p>
            <Input
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder="e.g. openai/text-embedding-3-small"
              aria-label="Embedding model"
              className="font-mono"
            />
            <Input
              type="password"
              value={embeddingApiKey}
              onChange={(e) => setEmbeddingApiKey(e.target.value)}
              placeholder="API key — leave blank to keep current key"
              aria-label="Embedding API key"
            />
            <Input
              value={embeddingApiBase}
              onChange={(e) => setEmbeddingApiBase(e.target.value)}
              placeholder="API base URL (optional — for Ollama)"
              aria-label="Embedding API base URL"
              className="font-mono"
            />
            <div className="flex gap-2">
              <Button onClick={() => saveEmbedding()} disabled={patchMutation.isPending}>
                Save
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  const full: LlmSettingsUpdate = {
                    embedding_model: null,
                    embedding_api_key: null,
                    embedding_api_base: null,
                    confirm_reembed: false,
                  };
                  setPendingEmbeddingUpdate(full);
                  patchMutation.mutate(full);
                }}
                disabled={patchMutation.isPending}
              >
                Reset to .env default
              </Button>
            </div>
          </section>

          {needsToken && (
            <AccessTokenPrompt
              onUnlock={() => {
                if (patchMutation.variables) patchMutation.mutate(patchMutation.variables);
              }}
            />
          )}

          {reembedConfirmMessage && pendingEmbeddingUpdate && (
            <div className="flex flex-col gap-2 rounded-2xl bg-card p-5 shadow-sm">
              <p className="text-destructive text-sm">{reembedConfirmMessage}</p>
              <Button
                variant="destructive"
                size="sm"
                className="self-start"
                onClick={() => patchMutation.mutate({ ...pendingEmbeddingUpdate, confirm_reembed: true })}
                disabled={patchMutation.isPending}
              >
                Confirm re-embed
              </Button>
            </div>
          )}

          {patchMutation.isError && !reembedConfirmMessage && !needsToken && (
            <p className="text-destructive text-sm">
              {patchMutation.error instanceof Error ? patchMutation.error.message : "Failed to save settings."}
            </p>
          )}
        </>
      )}
    </div>
  );
}
