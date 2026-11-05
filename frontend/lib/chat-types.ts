export type Audience = "pm" | "dev";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type Source = {
  module_id: number;
  module_name: string;
  relative_path: string | null;
};

export type SourcesEvent = { event: "sources"; sources: Source[] };
export type TokenEvent = { event: "token"; text: string };
export type DoneEvent = {
  event: "done";
  tokens_in: number;
  tokens_out: number;
  cost_usd: string;
};
export type ErrorEvent = { event: "error"; detail: string };

export type ChatEvent = SourcesEvent | TokenEvent | DoneEvent | ErrorEvent;
