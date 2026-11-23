# Assurance case

Why this project's security requirements are believed to be met: the threat
model, the trust boundaries, the design principles actually applied, and the
implementation weaknesses actually countered — not a checklist, an argument.
Written for the OpenSSF Best Practices Badge's `assurance_case` criterion,
but meant to be read and kept honest, not just satisfy a form field.

## What this software does

MageWiki-AI scans Magento 2 codebases (`app/code`, `vendor`, Composer
`path`-type repositories), parses their declarative XML and PHP source with
`tree-sitter-php`/`lxml`, has an LLM produce a structured description of
each module, stores both the parser-derived facts and the LLM output in
Postgres, and serves a RAG chat agent that answers questions about the
scanned fleet, citing module and file. See `CLAUDE.md` for the full
architecture.

## Threat model and trust boundaries

**The scanned repository's content is the primary untrusted input.**
MageWiki is explicitly designed to be pointed at third-party Magento
modules it has never seen before — a module's own `etc/module.xml`,
`etc/di.xml`, PHP source, `composer.json`, and every other file it ships
are all attacker-controllable from MageWiki's point of view, even though
the module itself is never executed. This is the boundary most of this
project's own real security fixes have been about:

- A scanned module's file can be a symlink pointing outside the module
  root (or at a host file like `/etc/passwd` or a mounted `.env`) —
  `is_safe_to_read()` (`backend/app/scanner/discovery.py`) is the one
  checkpoint every file read in the scanner goes through, applied at
  discovery, hashing, every declarative-XML parser, `composer.json`/
  `config.php`/GraphQL-schema parsing, and the two task functions that
  independently re-read files from disk.
- A scanned module's XML can carry a malformed encoding declaration or an
  XXE payload — `HARDENED_XML_PARSER`
  (`backend/app/scanner/xml_parse_utils.py`) disables entity resolution
  explicitly (checked directly against the pinned lxml/libxml2: this
  specific payload shape was never actually exploitable against that
  version, but the parser is hardened anyway rather than relying on a
  dependency's own default never changing).
- A scanned module's PHP can be arbitrary, malformed, or adversarially
  constructed to stress the parser — covered by ClusterFuzzLite fuzzing
  (`.clusterfuzzlite/fuzz_*.py`) over the XML/PHP/GraphQL parsing surface,
  which has already found and fixed one real bug (an uncaught `OSError`
  from a malformed encoding declaration).

**The LLM's output is also untrusted, not a second source of facts.**
CLAUDE.md's own anti-hallucination rules exist because the model can
produce plausible-looking but false structured output: events, plugins,
crons, endpoints, tables, and dependencies are inserted by parser code and
the AI never invents them; a tag's `source` field distinguishing
deterministic-parser-derived from AI-guessed is enforced in code
(`filter_tags` in `backend/app/analyzer/tags.py` forces `source="ai"` on
every tag that reaches it, regardless of what the model itself claims —
found and closed after a code review showed the function's own docstring
promised this but the code didn't enforce it).

**The API surface has two trust levels.** Read-only browsing (the module
catalog, stats, chat) is open by default — this is a self-hosted,
single-operator tool, not a multi-tenant SaaS (see `CLAUDE.md`'s "Goal and
scope"). Endpoints that cost money or mutate shared state (`POST /chat`,
`PATCH /settings/llm`, `POST /scan[/stream]`) are gated behind
`WRITE_ACCESS_TOKEN` when configured, so an operator can expose read access
publicly without exposing their LLM budget. The webhook scan trigger
(`POST /webhooks/scan`) is HMAC-SHA256 authenticated
(`hmac.compare_digest`, constant-time) and its `path` field — coming from
untrusted JSON, not a validated API schema — is checked against
`is_within_scan_roots()` before anything touches the filesystem, failing
closed (not raising) for a malformed or wrong-typed value.

## Secure design principles applied

- **Fail-safe defaults**: every optional secret (`webhook_hmac_secret`,
  `write_access_token`) defaults to empty, meaning the feature it gates is
  *disabled*, not open with a guessable default. `is_within_scan_roots()`
  with no configured scan roots allows nothing, not everything the
  container can see.
- **Complete mediation**: `is_safe_to_read()` and `is_within_scan_roots()`
  are each a single checkpoint every relevant code path goes through, not
  duplicated and allowed to drift (a past incident — see the
  `project-decision-log` skill — was exactly two independent copies of a
  path-validation check diverging).
- **Least privilege**: CI workflow tokens are scoped per-job, not
  per-workflow (fixed this session after OpenSSF Scorecard flagged a
  workflow-level grant); `dependabot-auto-merge.yml` only auto-merges
  patch/minor bumps once required status checks are green.
- **Economy of mechanism / input validation with allowlists**: tag
  vocabulary is a closed, explicit set (`ALLOWED_TAGS`); license-risk
  checking matches against an explicit prefix list, not a denylist.

## Common implementation weaknesses countered

- **XXE**: see "Threat model" above.
- **Path traversal / arbitrary file read**: `is_safe_to_read()` and
  `is_within_scan_roots()`, both fail-closed, both covered by real
  (non-mocked) symlink and non-string-input regression tests.
- **SQL injection**: all database access goes through SQLAlchemy's ORM/Core
  with parameterized queries — no raw string-interpolated SQL anywhere in
  the scanner or API layers.
- **Weak secrets**: a configured `webhook_hmac_secret`/`write_access_token`
  must be empty (disabled) or at least 16 characters (128 bits) —
  `backend/app/config.py`'s `_secret_meets_minimum_length` validator.
- **Supply chain**: every GitHub Action is pinned to a commit SHA
  (not a mutable tag); Dependabot runs weekly across pip/npm/
  github-actions; `pip-audit`/`npm audit`/`dependency-review-action` run in
  CI; releases are signed keylessly with cosign (Sigstore) and the
  signature/attestation is verifiable without a long-lived private key —
  see "Verifying a release" in `SECURITY.md`.
- **Hallucinated/spoofed AI output treated as fact**: see "Threat model"
  above (tag `source` enforcement, parser-vs-AI fact separation).

## What this does not protect against (residual risk, stated plainly)

- **Scanned code is parsed, not executed** — the scanner never runs a
  scanned module's PHP. `php-analyzer`'s static-analysis sidecar
  (PHPStan/PHPMD/phpcs/Rector) analyzes code statically; it does not
  execute the scanned module's own runtime logic. If real PHPUnit
  execution of scanned/third-party code is ever added, that is a
  materially different risk class (running untrusted code, not just
  parsing it) and would need its own sandboxing design — explicitly not
  something this assurance case covers today.
- **No sandboxing of the LLM provider itself** — MageWiki trusts the
  configured LLM provider (DeepSeek by default, BYOK otherwise) not to be
  actively malicious; prompt injection via scanned-module content
  influencing the model's own behavior (as opposed to its *output* being
  distrusted, which is handled) is a known, generally-unsolved class of
  risk for any LLM-backed tool and isn't specifically mitigated beyond the
  anti-hallucination/fact-separation design above.
- **Decision authority is still solo** — see `GOVERNANCE.md`. A second
  collaborator has write access and can keep PRs/issues/releases moving if
  the maintainer is unavailable, but has no admin access to CI
  secrets/repository settings and no say over project direction; a
  security *fix* for anything beyond the publicly documented process still
  depends on the maintainer being available.

## How this is kept current

Real security-relevant changes are recorded with their actual reasoning in
the `project-decision-log` skill as they happen, not retrofitted here after
the fact — this document is a summary of that history, and should be
re-read (and updated) whenever a new entry there changes the picture above.
