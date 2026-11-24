# Roadmap

## What's next (next ~12 months)

This project's working method (see `CLAUDE.md`'s "Working method" section)
is to plan and scope one phase at a time, not commit to a long fixed list
up front — so this is a direction, not a numbered list of promised phases:

- **Continued phase-based feature development** in the same shape as the
  phases below: more rounds of cross-module conflict detection as new
  Magento declarative-XML surfaces get covered, deeper structural fact
  extraction, and RAG/agent quality work.
- **CI/security hardening** in the style of this project's OpenSSF
  Scorecard work and OpenSSF Best Practices Badge self-assessment —
  ongoing, not a one-time pass.
- **Evaluation and quality**: keeping the retrieval evaluation suite
  (Phase 7) meaningful as the agent's tool surface grows.

**Explicitly not planned:** turning this into a multi-tenant SaaS product
(it's built and licensed as a self-hosted, single-operator tool — see
`CLAUDE.md`'s "Goal and scope"), and supporting ecosystems other than
Magento 2 (the scanner, data model, and RAG design are Magento-specific by
design, not a generic "scan any PHP codebase" tool).

## Per-phase changelog

Full detail (done-criteria, data model, RAG design, and the decision recorded behind each phase): see `CLAUDE.md`.

- [x] **Phase 0** — Repo skeleton, docker-compose, migrations
- [x] **Phase 1** — Scanner: module discovery, XML/composer/PHP parsers, saved to the DB
- [x] **Phase 2** — Per-file hash, diff, module state machine, ARQ+Redis queue
- [x] **Phase 3** — AI analysis: JSON schema, tag dictionary, cache, cost tracking, budget, README from the DB
- [x] **Phase 4** — Embeddings and hybrid retriever (vector + FTS + trigram, RRF)
- [x] **Phase 5** — Agent with tools, SSE chat, citations, pm/dev modes
- [x] **Phase 6** — Cron, HMAC webhook, BYOK in the UI, Ollama, dependency graph
- [x] **Phase 7** — Evaluation suite (hit_rate@k, MRR, negative/enumeration questions)
- [x] **Phase 7b** — CI/CD (GitHub Actions): lint, tests, Docker build, and the PR-comment RAG eval all verified green
- [x] **Phase 8** — Kubernetes: Kustomize manifests, scan CronJob, verified end-to-end on a local `kind` cluster
- [x] **Phase 9** — Parser-only quality checks (composer completeness, `@deprecated`, hardcoded secrets, test presence) + badge/KPI-ring UI foundation
- [x] **Phase 10** — Dependency intelligence: CVE/security-advisory check + abandoned/outdated check
- [x] **Phase 11** — Multi-repo fleet view
- [x] **Phase 12** — PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/Rector/PhpMetrics)
- [x] **Phase 12b** — Magento upgrade readiness: PHP-version and `magento/*` dependency compatibility against the latest Magento release, refreshed via a daily cron
- [x] **Phase 13** — Public demo deployment: Fly.io + Neon (not the originally planned GCP/Azure/Terraform — no budget for that, see `CLAUDE.md`); decommissioned 2026-11-17 after the deployment stopped serving — see the decision log
- [x] **Phase 14** — Deeper structural facts: `webapi.xml`, `crontab.xml`, `db_schema.xml`, `system.xml`, `di.xml` `virtualType`, and message-queue topology (`communication.xml`/`queue_topology.xml`/`queue_consumer.xml`)
- [x] **Phase 15** — Cross-module conflict detection, round 2: `di.xml` `<preference>` conflicts, `crontab.xml` job-code conflicts, GraphQL field conflicts
- [x] **Phase 16** — Module history: a per-scan-change snapshot table and a "what changed since last scan" view on every module page
- [x] **Phase 17** — RAG query rewriting, opt-in (mirrors how reranking shipped — a second, independently budget-gated LLM call)
- [x] **Phase 18** — Alerting: one webhook POST per scan when a secret/CVE count goes up for any module — works directly with a Slack or Google Chat webhook URL, off by default
- [x] **Phase 19** — Cross-module conflict detection, round 3: `acl.xml` admin-ACL resource facts, a duplicate-ACL-resource-id conflict check, and a new unprotected-admin-controller check (`Controller/Adminhtml/*` with no resolvable `ADMIN_RESOURCE`)
- [x] **Phase 20** — Cross-module conflict detection, round 4: `indexer.xml`/`mview.xml` facts, a duplicate-indexer-id check, and a duplicate-mview-id check
- [x] **Phase 21** — Semantic duplicate/overlap detection (reusing Phase 4's existing module-level embeddings, no new scan or API call) plus a side-by-side module comparison page
- [x] **Phase 22** — Cross-module conflict detection, round 5: `routes.xml` facts, a route-id conflict check, and a frontName conflict check, both scoped per area
- [x] **Phase 23** — Cross-module conflict detection, round 6: `widget.xml` facts (no area column -- widget ids are a single global namespace) and a duplicate-widget-id conflict check
- [x] **Phase 24** — Lightweight access gate (shared token) on write/cost-incurring endpoints (`POST /chat`, `PATCH /settings/llm`, `POST /scan[/stream]`) — lets an operator safely enable a real LLM key on the public demo without open budget exposure; read-only browsing stays open
- [x] **Phase 25** — Cross-module conflict detection, round 7: `menu.xml` admin-menu-item-id conflicts (a confirmed hard Magento error, kept the same severity as the rest of this family) and `cache.xml` type conflicts (only when the backing `instance` disagrees)
- [x] **Phase 26** — PR gate: a `GET /modules/findings-by-path` lookup, a standalone `pr_gate.py` CLI (stdlib + httpx only, no backend dependency), and a composite GitHub Action consumers drop into their own Magento store's CI — fails a pull request's check and posts a sticky comment when it touches a module with an existing blocking finding. Reads the already-scanned state of the target repo; does not scan the PR branch itself.
- [x] **Phase 27** — Upgrade impact: an on-demand "what if I upgrade to Magento X" query (`GET /repos/upgrade-impact` + a Repos-page-linked UI page), extending Phase 12b's `magento_github.py`/`check_magento_upgrade_readiness` with a new pure `compare_against_release()` so an arbitrary chosen version can be checked against every already-scanned module in one fetch, without writing to `ModuleQualityFinding` or rescanning the repo.
- [x] **Phase 28** — Repo health report: a one-click shareable Markdown summary (module counts/percentages, a KPI-tile-grouped findings breakdown, top-5 riskiest modules) for a whole repo, built as a pure frontend feature from the already-available `GET /modules?repo_root=...` response — no new backend endpoint needed. Hoisted the Stats page's `KPI_TILES`/`prettifyCheckType` into a shared `lib/kpi-tiles.ts` so both pages use identical labels.
