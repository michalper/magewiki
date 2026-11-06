"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type { Audience, ChatEvent, Source } from "@/lib/chat-types";

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type DisplayMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  error?: string;
};

function parseSseBlock(block: string): ChatEvent | null {
  const lines = block.split("\n");
  const eventLine = lines.find((l) => l.startsWith("event: "));
  const dataLine = lines.find((l) => l.startsWith("data: "));
  if (!eventLine || !dataLine) return null;
  const event = eventLine.slice("event: ".length);
  const data = JSON.parse(dataLine.slice("data: ".length));
  return { event, ...data } as ChatEvent;
}

async function streamChat(
  messages: { role: string; content: string }[],
  audience: Audience,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const res = await fetch(`${apiUrl()}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, audience }),
  });
  if (!res.ok || !res.body) {
    throw new Error(`API responded with ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex: number;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const event = parseSseBlock(block);
      if (event) onEvent(event);
    }
  }
}

function SourceChips({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {sources.map((s, i) => (
        <Link key={`${s.module_id}-${s.relative_path ?? ""}-${i}`} href={`/modules/${s.module_id}`}>
          <Badge variant="outline" className="cursor-pointer hover:bg-accent">
            {s.module_name}
            {s.relative_path ? `:${s.relative_path}` : ""}
          </Badge>
        </Link>
      ))}
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [audience, setAudience] = useState<Audience>("dev");
  const [isStreaming, setIsStreaming] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || isStreaming) return;

    const history = [...messages, { role: "user" as const, content: question }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setIsStreaming(true);

    try {
      await streamChat(history, audience, (event) => {
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
      });
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], error: "Failed to reach the API." };
        return next;
      });
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-3xl mx-auto w-full">
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
                : "self-start bg-muted text-foreground rounded-2xl px-4 py-2 max-w-[80%]"
            }
          >
            <p className="whitespace-pre-wrap text-sm">{m.content}</p>
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
          disabled={isStreaming}
        />
        <Button type="submit" disabled={isStreaming || !input.trim()}>
          {isStreaming ? "Thinking..." : "Send"}
        </Button>
      </form>
    </div>
  );
}
