"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Info } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiUrl } from "@/lib/api";
import type { Audience, ChatEvent, Source } from "@/lib/chat-types";
import { streamSse } from "@/lib/sse";
import { useDocumentTitle } from "@/lib/use-document-title";

// Assistant replies are prompted to use markdown (tables, bold, code spans) --
// rendered with remark-gfm for pipe-table support, since a table otherwise
// shows its raw "| a | b |" syntax as plain text.
const CHAT_MARKDOWN_COMPONENTS: Components = {
  p: (props) => <p className="mb-2 last:mb-0 leading-relaxed" {...props} />,
  ul: (props) => <ul className="list-disc pl-5 mb-2 space-y-1" {...props} />,
  ol: (props) => <ol className="list-decimal pl-5 mb-2 space-y-1" {...props} />,
  a: (props) => <a className="text-primary hover:underline" {...props} />,
  code: (props) => <code className="bg-background/60 rounded px-1 py-0.5 font-mono text-xs" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
  table: (props) => (
    <div className="overflow-x-auto mb-2">
      <table className="text-sm border-collapse" {...props} />
    </div>
  ),
  th: (props) => (
    <th className="border border-border px-2 py-1 text-left font-semibold bg-background/40" {...props} />
  ),
  td: (props) => <td className="border border-border px-2 py-1 align-top" {...props} />,
};

type DisplayMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  error?: string;
};

async function streamChat(
  messages: { role: string; content: string }[],
  audience: Audience,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSse<ChatEvent>(`${apiUrl()}/chat`, { messages, audience }, onEvent, signal);
}

// How a source was actually found, per signal -- only ever set for a source
// that came from the hybrid-search tool (get_module/find_by_class/etc. have
// no ranking signal of their own, so this is null for those, and no icon
// renders at all).
function retrievalDebugText(s: Source): string | null {
  if (s.score === null && s.semantic_rank === null && s.keyword_rank === null && s.identifier_rank === null) {
    return null;
  }
  const rank = (label: string, r: number | null) => `${label} ${r === null ? "not found" : `#${r}`}`;
  const parts = [
    rank("Semantic", s.semantic_rank),
    rank("Keyword", s.keyword_rank),
    rank("Identifier", s.identifier_rank),
  ];
  if (s.score !== null) parts.push(`RRF score ${s.score.toFixed(4)}`);
  return parts.join(" · ");
}

function SourceChips({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {sources.map((s, i) => {
        const debugText = retrievalDebugText(s);
        return (
          <span key={`${s.module_id}-${s.relative_path ?? ""}-${i}`} className="inline-flex items-center gap-1">
            <Link href={`/modules/${s.module_id}`}>
              <Badge variant="outline" className="cursor-pointer hover:bg-accent">
                {s.module_name}
                {s.relative_path ? `:${s.relative_path}` : ""}
              </Badge>
            </Link>
            {debugText && (
              <Tooltip>
                <TooltipTrigger
                  className="inline-flex text-muted-foreground/70 hover:text-foreground"
                  aria-label={`How "${s.module_name}" was found`}
                >
                  <Info className="size-3" />
                </TooltipTrigger>
                <TooltipContent>{debugText}</TooltipContent>
              </Tooltip>
            )}
          </span>
        );
      })}
    </div>
  );
}

export default function ChatPage() {
  useDocumentTitle("Chat");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [audience, setAudience] = useState<Audience>("dev");
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Navigating away mid-answer must not leave the backend's LLM call still
    // running (and still billing) after the page that was listening for its
    // tokens is gone.
    return () => abortControllerRef.current?.abort();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || isStreaming) return;

    const history = [...messages, { role: "user" as const, content: question }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setIsStreaming(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await streamChat(
        history,
        audience,
        (event) => {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (event.event === "token") {
              next[next.length - 1] = { ...last, content: last.content + event.text };
            } else if (event.event === "sources") {
              next[next.length - 1] = { ...last, sources: event.sources };
            } else if (event.event === "error") {
              next[next.length - 1] = { ...last, error: event.detail };
            }
            return next;
          });
        },
        controller.signal,
      );
    } catch (err) {
      // An intentional abort (navigating away) isn't a failure worth showing —
      // the message list it would update may not even be mounted anymore.
      if ((err as Error).name !== "AbortError") {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], error: "Failed to reach the API." };
          return next;
        });
      }
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <TooltipProvider>
    {/* suppressHydrationWarning: see app/modules/page.tsx's own top-level
        div for the full explanation -- the onboarding wizard's first-visit
        dialog marks this div inert via a direct DOM write Next's
        hydration-diff otherwise flags as a false mismatch. */}
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-4xl mx-auto w-full" suppressHydrationWarning>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        <div className="flex gap-1">
          <Button
            type="button"
            size="sm"
            variant={audience === "pm" ? "default" : "outline"}
            onClick={() => setAudience("pm")}
          >
            PM
          </Button>
          <Button
            type="button"
            size="sm"
            variant={audience === "dev" ? "default" : "outline"}
            onClick={() => setAudience("dev")}
          >
            Dev
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-4 flex-1">
        {messages.length === 0 && (
          <p className="text-muted-foreground text-sm">
            Ask about scanned modules, e.g. &ldquo;Do we have a Klaviyo integration?&rdquo;
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user"
                ? "self-end bg-primary text-primary-foreground rounded-2xl px-4 py-2 max-w-[80%]"
                : "self-start bg-muted text-foreground rounded-2xl px-4 py-2 max-w-full"
            }
          >
            {m.role === "assistant" ? (
              <div className="text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={CHAT_MARKDOWN_COMPONENTS}>
                  {m.content}
                </ReactMarkdown>
              </div>
            ) : (
              <p className="whitespace-pre-wrap text-sm">{m.content}</p>
            )}
            {m.error && <p className="text-destructive text-sm mt-1">{m.error}</p>}
            {m.sources && <SourceChips sources={m.sources} />}
          </div>
        ))}
      </div>

      <form className="flex gap-2" onSubmit={handleSubmit}>
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about the scanned modules..."
          aria-label="Chat message"
          disabled={isStreaming}
        />
        <Button type="submit" disabled={isStreaming || !input.trim()}>
          {isStreaming ? "Thinking..." : "Send"}
        </Button>
      </form>
    </div>
    </TooltipProvider>
  );
}
