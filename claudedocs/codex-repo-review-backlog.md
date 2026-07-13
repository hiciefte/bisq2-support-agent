# Repository review follow-up backlog

This is the Phase 3 backlog for the MEDIUM/LOW hypotheses in
`repo-review-findings-2026-07-12.md`. Items remain hypotheses until re-verified
against the then-current branch. They are ordered by risk and dependency, not
by the automated report's numbering.

## P0 — correctness, security, and availability

- [ ] **Add a durable Bisq live-channel inbox/ack contract.** The H5 replay fix
  intentionally provides durable at-most-once deduplication: polling records a
  user message before RAG/dispatch completes. Design an inbox/outbox or explicit
  ack after terminal `SENT`/`QUEUED`, then test a crash between poll and dispatch
  without reintroducing full-history replay.
- [ ] **Persist and reconcile actual LLM usage across processes.** The H2 circuit
  breaker is a documented single-process, fixed worst-case admission reservation,
  not provider billing accounting. Add atomic shared-day persistence plus actual
  usage reconciliation for rewrite, translation, tool, embedding, and answer calls
  before describing it as an exact application-wide token cap.
- [ ] **Make alert relay delivery idempotent across ambiguous Matrix outcomes.**
  Webhook groups are now sent as one event to avoid partial-batch retries. Persist
  Alertmanager fingerprints/Matrix transaction IDs so a timeout after a successful
  homeserver write cannot duplicate the whole group on retry.
- [ ] **M1 — move synchronous SQLite work off async request paths.** Inventory
  feedback, FAQ admin, and Matrix handler writes; use the repository's existing
  thread-offload pattern; add a lock-holder test proving the event loop remains
  responsive.
- [ ] **M12 — release inbound dedup reservations when dispatch is not accepted.**
  Cover zero-delay dispatch and coordinator-overflow failure, then prove a later
  retry can process the same external message exactly once.
- [ ] **M2 — design a fail-closed fresh-install FAQ bootstrap.** Do not restore
  the removed migration script by itself. First choose a trusted canonical
  source, require an integrity check, refuse to replace a non-empty `faqs.db`,
  and test preservation of `verified` state. Update `update.sh` and deployment
  documentation only after that source is approved.
- [ ] **M4 — reject client-supplied system turns in query rewriting.** Normalize
  history once for both the main prompt and rewriter; add injection regressions
  for ordinary and streaming chat.
- [ ] **M5 — bound primary LLM calls.** Add explicit provider timeouts, narrowly
  scoped retries for transient failures, and a circuit breaker with metrics;
  test timeout, half-open recovery, and non-retryable errors.
- [ ] **M6 — bound NLI input to the selected model.** Re-verify the model's token
  limit, configure truncation/max length, and add an oversized-context test that
  returns a stable confidence result rather than raising.

## P1 — RAG quality and regression detection

- [ ] **Version sparse vocabulary with each physical Qdrant collection.** The H4
  rebuild now stages vocabulary, reconciles ambiguous alias swaps, and rolls back
  the alias when promotion fails. A collection-keyed vocabulary/retriever contract
  would remove the remaining brief cross-resource commit window entirely.
- [ ] **M3 — calibrate a minimum retrieval similarity threshold.** Measure it on
  the gated evaluation set, route off-topic queries to the honest no-document
  fallback, and record missing-FAQ signals without lowering safety recall.
- [ ] **M8 — reuse each query embedding within one request.** Introduce a
  request-scoped memo only; verify dense/absolute-score stages receive the same
  vector and concurrent requests never share user data.
- [ ] **M7 — schedule the existing gated retrieval benchmark.** Add a nightly or
  manually dispatched workflow with pinned data/model inputs, artifacted
  results, a documented threshold, and no production credentials.
- [ ] **Coverage floor — make coverage loss visible.** Establish the current
  reproducible baseline, enable `--cov=app`, and ratchet the threshold upward by
  owned subsystem rather than selecting an aspirational number.

## P1 — configuration, dependencies, and documentation

- [ ] **Type-check tests and standalone scripts incrementally.** The enforced C3
  CI gate covers `api/app/`; `mypy .` exposes a large pre-existing test/script
  baseline. Establish per-directory ownership and ratchet those files into the
  gate rather than masking new application errors.
- [ ] **M13 — remove or wire no-op settings.** Generate a settings-to-read-site
  inventory, re-verify every candidate, remove only unused fields, and publish a
  table of live feature flags and their owners.
- [ ] **M16 — slim runtime dependencies.** Confirm direct and transitive imports,
  move test/dev tooling out of the production image, remove unused heavy
  packages in small groups, and compare image size plus the full test gate.
- [ ] **M17 — correct agent-facing architecture docs.** Replace stale vector-store
  and service descriptions with the current Qdrant/channel architecture and add
  a lightweight doc check for renamed core components.
- [ ] **M18 — regenerate API/reference material.** Refresh OpenAPI from the live
  app, replace fragile source line anchors with stable symbols/paths, and verify
  streaming, escalation, public FAQ, and admin surfaces are represented.

## P2 — structural work

- [ ] **M15 — converge the two RAG-to-channel response pipelines.** Characterize
  both paths with parity tests first, select one shared response builder, then
  migrate one channel at a time while preserving staff grounding and metadata.
- [ ] **M14 — decompose oversized composition/services/UI modules.** Start with
  characterization tests and ownership boundaries for the lifespan root,
  `simplified_rag_service.query`, the largest update service, and the largest
  admin pages. Keep each extraction behavior-preserving and independently
  reviewable.

## Completed as converged work in this branch

- [x] **M9 — repair the user-satisfaction alert metric and percentage threshold.**
- [x] **M10 — make the deployment health timeout fail closed.** Production drill
  remains human-gated.
- [x] **M11 — add Grafana, node-exporter, scheduler, and relay healthchecks.**
  Scheduler health covers both the cron process and heartbeat freshness.

## LOW — security hardening

- [ ] Move admin authentication values out of process arguments in polling
  scripts; pass them through a protected file descriptor/config mechanism and
  add a process-list regression.
- [ ] Correct the monitoring API-key file guidance and generated permissions so
  only the service account can read it.
- [ ] Enforce the configured minimum API-key length in production instead of
  warning; retain explicit test/development behavior.
- [ ] Create Tor backup/vanity-key temporary files with restrictive permissions
  from the first write and test cleanup on interruption.
- [ ] Remove CSP `script-src 'unsafe-inline'` after inventorying required inline
  scripts; use nonces or hashes and add a browser smoke test.
- [ ] Rotate the committed external healthcheck capability and read it from an
  environment/secret file; ensure the repository contains no replacement value.

## LOW — tests, ownership, and cleanup

- [ ] Add authorized/unauthorized tests for the vectorstore rebuild admin action.
- [ ] Decide ownership of `db/escalation_migrations/`: delete it if orphaned or
  add schema-equivalence coverage if it is an intended artifact.
- [ ] Add route smoke tests for metrics update, onion verification, and admin
  analytics, including authentication invariants.
- [ ] Add React Testing Library coverage for feedback submission success,
  validation, and failure in the chat UI.
- [ ] Remove remaining public JSONL compatibility properties and migration paths
  only after a repository-wide reader/writer inventory and fixture migration.
- [ ] Inventory dead singletons and the three script trees; publish a short
  caller/owner map, then remove orphaned entrypoints in separate commits.
- [ ] Replace manually maintained line-count/route-list documentation with
  generated checks where practical.
- [ ] Classify root screenshots and scratch artifacts: add intentional local
  outputs to `.gitignore`; archive or delete only with owner confirmation.
