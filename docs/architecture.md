# Architecture notes: RAG, cost control, and anti-hallucination

This is the "why", not the "what" — for the implementation itself, read the code;
for the full, dated decision log (including every production bug found along the
way), read `CLAUDE.md`. This document pulls out the pieces most relevant to how
the retrieval and agent layer is actually built, for anyone evaluating the design
rather than just running the app.

## Why hybrid retrieval, not pure vector RAG

A single embedding model misses things a human expects to find instantly:

- **Exact identifiers.** A query like `Vendor_Module` or a config key
  (`payment/klaviyo/api_key`) should match on the literal string, not on semantic
  similarity — embeddings are often *worse* at this than a trigram index, because
  identifiers compress poorly into the same vector space as natural-language
  prose.
- **Keywords with low semantic signal.** `klaviyo.com` as a literal substring in a
  config value is a strong signal a pure embedding can dilute into the rest of
  the chunk's meaning.
- **Typos and fragments.** `Vendr_Modul` should still find `Vendor_Module`.

So retrieval runs three independent signals — pgvector/HNSW (semantic), Postgres
`tsvector` (keyword/full-text), and `pg_trgm` (identifiers, typo-tolerant) — and
fuses them with **Reciprocal Rank Fusion** (k=60): each signal's *rank*, not its
raw score, which sidesteps the usual RAG-fusion headache of normalizing
incomparable score scales (cosine distance vs. a BM25-like FTS score vs. trigram
similarity) onto one axis.

The evaluation suite (see the README's Evaluation section) exists specifically
to check this wasn't a solution in search of a problem: hybrid matches-or-beats
vector-only at every k and clearly beats FTS-only, on real natural-language
questions against a real module. If it hadn't, the honest move would have been
to simplify back to vector-only — complexity has to earn its keep.

**Also deliberately not chosen:** a separate vector database (Qdrant, Milvus).
Relational data, full-text, trigram, and vectors all live in one Postgres
instance. For a single-tenant, budget-capped tool, running two databases to get
one extra index type isn't a trade worth making — and it means a single
transaction can commit module metadata and its embeddings atomically, which a
split architecture would have to reconcile some other way (an event, a
two-phase commit, eventual consistency).

## Why no LangChain

The agent loop is tool-calling via LiteLLM in a few dozen lines: build a tool
schema, call the model, dispatch whichever tool it picked, feed the result back,
repeat until it answers or hits a call-count ceiling. A framework earns its
keep when it's abstracting away real incidental complexity (retries, backoff,
provider-specific request shaping) — LiteLLM already does that one layer down.
Above that, this agent's actual logic (seven tools, a system prompt, a loop) is
small enough that a framework would be abstracting over *itself*, not over
complexity that was actually there.

## Anti-hallucination: facts come from parsers, interpretation comes from AI

The single rule this project is built around: **the LLM never invents a fact it
could instead be handed.** Concretely:

- Every structural fact — events a module listens to, plugins it declares,
  cron jobs, REST routes, `db_schema.xml` tables/columns, dependency edges — is
  extracted by a parser (`tree-sitter-php` for PHP, `lxml` for XML) and inserted
  into the synthesis prompt as ground truth. The LLM's job for these is to write
  *prose about facts already on the page*, not to recall or guess them.
- `features[].source` is a required field with its own validation: if the
  model claims a feature lives in a file or class that isn't actually part of
  the module (checked against the real class/file list, not trusted from the
  model's own claim), that feature is rejected rather than silently kept. A
  model confidently citing a file that doesn't exist is a worse failure mode
  than it saying nothing.
- `unknown` is a valid, accepted value wherever the model doesn't have grounds
  to say otherwise — the system prompt and schema both treat "I don't know" as
  a correct answer, not a failure to coerce away.
- The chat agent's system prompt enforces answering **only** from tool results,
  with every claim traceable to a `module_id`/`file_path`. No results means
  "not found" — confirmed in the evaluation suite by a negative-question test
  (asking about an integration the module provably doesn't have) that the agent
  has to pass, not just a hope.

This is also why the retrieval-debugging feature exists: `search_modules`
results carry their per-signal rank (`semantic_rank` / `keyword_rank` /
`identifier_rank`, each `null` if that signal didn't surface the chunk at all)
all the way through to the chat UI's source citations, not just a final fused
score. A black-box "trust the embedding" retriever makes "why didn't it find X"
undebuggable; surfacing *which* signal found a result (or didn't) turns that
into a one-glance answer instead of a guessing game.

## Cost control is a first-class concern, not an afterthought

This is a single-user tool with a real monthly budget cap
(`LLM_MONTHLY_BUDGET_USD`), so the cost model had to be designed in, not bolted
on:

- **Hash-based re-analysis.** Every file's SHA256 is diffed against the last
  scan; only added/changed files trigger a new `analyze_file` job, and a
  no-op rescan costs exactly $0 in LLM calls. The same hash gates several
  *parser-only* quality checks too (PHPStan, hardcoded-secret scanning, etc.) —
  their output is a pure function of file content, so re-running them against
  unchanged bytes is wasted compute even though it costs no LLM budget. On a
  real 751-module store, that optimization took a no-op rescan from 1518s to
  170s.
- **A real cache**, not just a hash gate: `analysis_cache` is keyed by
  `(content_hash, model, prompt_version)`. Reverting a file to a previous
  version costs nothing; changing the prompt template invalidates exactly the
  entries it should, and no others.
- **Two models, deliberately split.** `analyze_file` (hundreds of calls per
  scan) runs on a cheap model; `synthesize_module` (one map-reduce call per
  module) can be configured to a stronger one via a separate `SYNTHESIS_MODEL`
  setting. This mattered in practice, not just in theory: the cheap model alone
  failed `ModuleDoc` schema validation on ~45% of modules in a real 760-module
  fleet, even after corrective-reprompt retries. Moving only the synthesis step
  to a stronger model fixed the real failure pattern for about 3x the per-call
  cost on the cheap step that still dominates call volume — checked against
  real `analysis_cache` token averages before deciding, not guessed.
- **An honestly-documented soft limit.** The budget check (`is_budget_exceeded`)
  reads current spend with no locking, which means several concurrent jobs can
  each observe "under budget" before any of them commits its own cost — real
  spend can briefly overshoot by roughly `concurrent_jobs × per_call_cost`
  before the next check catches it. This was flagged in a full-repo review and
  deliberately left as a soft limit rather than built out into real reservation
  accounting, which would be a materially bigger architectural change than a
  single-user, $20/month-capped tool currently needs. Recorded as a known,
  accepted tradeoff rather than silently shipped — the kind of thing worth
  surfacing in a design review even when the fix isn't worth making yet.

## Making structured LLM output actually reliable

Forced tool-use (Anthropic/OpenAI-style function calling) biases a model
strongly toward a JSON Schema but doesn't *guarantee* every required field
survives — confirmed in production, not assumed: `ModuleDoc`'s required
`pm_text`/`dev_text`/`description` fields were occasionally missing even with
schema-constrained output. Both the tool-use and plain-JSON code paths now
validate every attempt with Pydantic (not just check that it parses as JSON)
and retry once with the actual validation error appended to the prompt —
the same corrective-reprompt shape already used for malformed JSON, extended to
cover schema violations too. A second, narrower failure mode (the model
returning a bare string for a `Tag` instead of the required
`{name, source, confidence}` object) gets a `model_validator` that coerces the
bare string into a well-formed tag rather than spending a retry on a shape the
model kept not producing on its own — fixing what's correctable cheaply, and
reserving retries for failures that are actually worth another round trip.

## What this doesn't do (yet), and why

Reranking and query rewriting are both explicitly deferred, not forgotten: each
adds a real per-query LLM cost decision against a hard budget cap that hasn't
been made yet for this project. The multi-level index (module → file → code
fragment) and the retrieval-debugging panel were the priorities that directly
served "can the agent find the right thing and can a developer tell why" —
reranking optimizes an already-working retriever rather than fixing a gap, so
it waited.
