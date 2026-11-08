export type Audience = "pm" | "dev";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type Source = {
  module_id: number;
  module_name: string;
  relative_path: string | null;
  // Retrieval-debugging detail -- only set for a source that came from the
  // hybrid-search tool; every other tool (get_module, find_by_class, ...) has
  // no ranking signal of its own, so these are null for those.
  score: number | null;
  semantic_rank: number | null;
  keyword_rank: number | null;
  identifier_rank: number | null;
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
