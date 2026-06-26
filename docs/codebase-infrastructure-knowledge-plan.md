# Codebase and Infrastructure Knowledge Plan

## Purpose

This plan describes how to improve the Bisq Support Agent by adding grounded information from:

- The Bisq2 product codebase.
- The support-agent codebase itself.
- Runtime infrastructure state such as Bisq2 API readiness, seed-node status, Prometheus alerts, and related service health.

The goal is better support quality without turning raw implementation details into unreviewed customer-facing claims.

## Recommendation

Start with staff-only grounding, not automatic customer-facing answers from raw code.

The current RAG system already has a good authority model:

- Public wiki and verified FAQs are indexed as normal support sources.
- Internal LLM Wiki pages are indexed only when reviewed or active and source-backed.
- Live Bisq2 data is handled as runtime tool/context data rather than static documentation.
- Staff-assist payloads already provide a place for internal support context.

The first implementation should therefore add a staff-only "grounding brief" that helps human support admins understand what the code and infrastructure indicate. Reusable facts can later be promoted into reviewed LLM Wiki pages.

## Relevant Current System

Key integration points:

- `api/app/services/simplified_rag_service.py`
  - Loads wiki, FAQ, and LLM Wiki sources.
  - Combines documents before Qdrant indexing.
  - Extracts source metadata for responses.
- `api/app/services/rag/llm_wiki_loader.py`
  - Loads only reviewed or active LLM Wiki pages.
  - Requires source refs for indexable pages.
- `api/app/services/rag/qdrant_index_manager.py`
  - Tracks source freshness.
  - Creates Qdrant payload indexes for `protocol` and `type`.
- `api/app/channels/staff_assist/service.py`
  - Publishes staff-side draft answers and knowledge sources.
  - Best first place to add a grounding brief.
- `api/app/prompts/runtime_policy.py`
  - Already enforces evidence discipline and live-data precedence.
- `api/app/services/bisq_mcp_service.py`
  - Provides live Bisq2 market, offerbook, reputation, markets, and transaction data.
- `api/app/metrics/task_metrics.py`
  - Tracks Bisq2 API readiness and probe status.
- `docker/prometheus/alert_rules.yml`
  - Contains alert rules for RAG, containers, Bisq API readiness, and training sync.

## Why Not Raw-Code RAG First

Indexing raw code directly into the public RAG context is risky:

- Raw implementation chunks are noisy for support questions.
- Main-branch code may not match the user's installed release.
- Code comments and config defaults can be misleading outside deployment context.
- Internal endpoints, stack traces, and operational details may not be appropriate for users.
- Source-weighting raw code too highly could make confidence scoring over-trust implementation details.

Raw code is still valuable as evidence. It should first be transformed into structured, cited facts for staff.

## Code Knowledge Scope

High-value code-derived support facts:

- Trade-state transitions and dispute/mediation rules.
- Validation rules and user-visible limits.
- Error categories and likely causes.
- API endpoint behavior, timeouts, and permission boundaries.
- UI workflow labels and navigation targets when they are stable.
- Config defaults that affect network behavior, pairing, transport, and startup.
- Existing technical specifications already written as markdown in the Bisq2 repo.

Initial Bisq2 source areas to prioritize:

- `bisq-easy/src/main/java/bisq/bisq_easy/`
- `trade/src/main/java/bisq/trade/bisq_easy/`
- `trade/src/main/java/bisq/trade/mu_sig/`
- `offer/src/main/java/bisq/offer/`
- `user/src/main/java/bisq/user/reputation/`
- `api/src/main/java/bisq/api/rest_api/endpoints/`
- `api/src/main/java/bisq/api/access/permissions/`
- `apps/api-app/src/main/resources/api_app.conf`
- `apps/seed-node-app/src/main/resources/seed_node.conf`
- Relevant markdown specs under `trade/src/main/java/.../specification.md`

Exclude by default:

- Secrets, keys, wallets, local runtime data, generated files, caches, logs, and build output.
- Tests unless a test is the only available durable description of expected behavior.
- Developer-only comments that conflict with production configuration.

## Code Evidence Data Model

Add a generated source file such as:

`api/data/code_knowledge/code_evidence.jsonl`

Each record should be structured:

```json
{
  "id": "bisq2:0d45cd7aa8:BisqEasyTradeAmountLimits:getMaxUsdTradeAmount",
  "type": "code_fact",
  "repo": "bisq2",
  "commit": "0d45cd7aa8",
  "path": "bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java",
  "line_start": 77,
  "line_end": 84,
  "symbol": "BisqEasyTradeAmountLimits.getMaxUsdTradeAmount",
  "protocol": "bisq_easy",
  "audience": "staff_only",
  "freshness_class": "main_branch",
  "risk_level": "medium",
  "claim": "Bisq Easy caps reputation-based trade amount at 600 USD and derives the amount from reputation score.",
  "support_use": "Use as staff evidence when investigating trade-size or seller-reputation questions. Do not expose the raw formula unless reviewed for user-facing guidance.",
  "source_refs": [
    "code:bisq2@0d45cd7aa8:bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java:77-84"
  ]
}
```

Audience values:

- `staff_only`: may be used in grounding briefs only.
- `public_review_candidate`: suitable for admin review and possible LLM Wiki promotion.
- `public_reviewed`: safe for customer-facing retrieval after human approval.

Freshness values:

- `release_bound`: tied to a released Bisq version.
- `main_branch`: current code, useful but may not match installed user versions.
- `generated`: generated from specs or docs rather than source code.

## Retrieval and Indexing Design

Preferred first implementation:

1. Keep code evidence in a separate JSONL artifact.
2. Index `code_fact` documents into Qdrant only for staff-assist retrieval.
3. Add strict metadata filters for `audience`, `type`, `protocol`, and `repo`.
4. Do not allow `staff_only` code facts into normal customer-facing RAG context.
5. Promote durable facts into LLM Wiki pages after review.

Possible storage options:

- Separate Qdrant collection: strongest safety boundary for staff-only code evidence.
- Same Qdrant collection with strict filters: simpler, but requires careful tests to prevent source leakage.

If using the existing collection, add payload indexes for:

- `type`
- `protocol`
- `audience`
- `repo`
- Possibly `freshness_class`

## Staff Grounding Brief

Add a `GroundingBriefService` that runs for support-admin contexts and produces a compact staff-only payload.

Inputs:

- Original user question.
- Channel/thread metadata.
- Conversation history.
- Existing RAG result and sources.
- Retrieved code facts.
- Optional live infrastructure snapshot.

Output:

```json
{
  "summary": "User appears to ask why a Bisq Easy sell offer cannot be created.",
  "likely_protocol": "bisq_easy",
  "likely_issue": "seller_reputation_limit",
  "evidence": [
    {
      "kind": "code_fact",
      "claim": "Creating a Bisq Easy sell offer requires reputation score >= 1200.",
      "source_ref": "code:bisq2@0d45cd7aa8:bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java:135-139",
      "audience": "staff_only"
    }
  ],
  "safe_customer_guidance": [
    "Explain that Bisq Easy sell offers can depend on seller reputation.",
    "Ask for the user's Bisq version and exact error text before giving a specific limit."
  ],
  "uncertainties": [
    "Main-branch code may not match the user's installed release.",
    "No screenshot or exact error was provided."
  ],
  "do_not_say": [
    "Do not claim this is the only possible cause.",
    "Do not expose stack traces or internal class names to the user."
  ]
}
```

Where to attach it:

- Extend `StaffAssistPayload` with `grounding_brief`.
- Keep `knowledge_sources` unchanged for backward compatibility.
- Add a staff UI rendering section that separates public sources from internal evidence.

## Infrastructure State

Infrastructure and seed-node state should be live context, not static RAG.

Reasons:

- Runtime state changes quickly.
- Static embeddings would become stale.
- Support needs timestamps, freshness, and degradation status.
- Operational status should override static docs when diagnosing incidents.

Add an `InfrastructureStateService` that can gather:

- Current Bisq2 API readiness.
- Prometheus alert states.
- Container/service health.
- Qdrant readiness.
- Matrix channel readiness.
- Nginx/API routing health.
- Seed-node reachability and peer-count signals when available.

Initial output shape:

```json
{
  "timestamp": "2026-06-22T10:15:00Z",
  "freshness_seconds": 20,
  "overall": "degraded",
  "components": [
    {
      "name": "bisq2_api_offerbook",
      "status": "unhealthy",
      "last_check": "2026-06-22T10:14:45Z",
      "source": "prometheus:bisq2_api_offerbook_readiness_status"
    }
  ],
  "support_note": "Live offerbook lookups are degraded; do not answer current offer availability from static docs."
}
```

Seed-node plan:

1. Inventory configured seed addresses from release-bound config.
2. Add probe metrics for reachability, latency, peer count, and bootstrap success.
3. Expose status through Prometheus and the infrastructure-state service.
4. Include seed-node state only for network/startup/connectivity questions.
5. Show exact timestamp and probe source in staff grounding briefs.

## Authority and Conflict Rules

Use this precedence:

1. Live tool/infrastructure data with a fresh timestamp.
2. Release-matched code evidence.
3. Reviewed or active LLM Wiki pages.
4. Canonical public wiki and verified FAQs.
5. Main-branch code evidence.
6. Raw support conversation evidence.

Conflict behavior:

- If live data conflicts with static docs, staff brief should show the conflict.
- If main-branch code conflicts with reviewed docs, do not auto-answer; route to staff.
- If code evidence is unreviewed, keep it staff-only.
- If release version is unknown, avoid version-specific claims unless the user provides enough detail.

## Support-Admin Conversation Analysis

The support-admin exchange reveals a process gap more than a model-quality gap.

Conversation signals:

- The admin asked whether `Review Notes` and `Last Change Summary` should be edited "where applicable".
- The maintainer said `Review Notes` would be useful for improving future LLM Wiki generation prompts.
- The admin asked for a made-up example of a great review note.
- The admin continued reviewing pages and planned to fix notes later.
- Early page quality felt better than previous attempts, but production answer quality was still uncertain.

Interpretation:

- The generated page structure is close enough for real admin review, but section ownership is unclear.
- `Review Notes` currently has two possible meanings: an internal caveat inside the LLM Wiki page, and feedback from the human reviewer to improve the generator.
- `Last Change Summary` is also ambiguous unless reviewers know it is a maintenance log, not a prompt-feedback channel.
- The review workflow needs examples in the product, not only in chat.
- "Fix the notes later" is a warning that review-note capture must be lightweight. If it feels like a second task, it will lag behind content review.
- "Decent enough" is useful reviewer sentiment, but not enough to trust production behavior. Page approval still needs retrieval/generation evaluation before activation.

Current workflow findings:

- The backend already treats `Review Notes` and `Last Change Summary` as first-class LLM Wiki sections.
- Generated proposals currently add cluster notes into `Review Notes` and maintenance text into `Last Change Summary`.
- The admin UI review guide focuses on approving reusable pages and checking sources.
- The admin UI currently describes `review-note` as "usually no manual edit needed" and `last-change` as "usually no manual edit needed".
- Supporting fields are hidden under an advanced section, while the support-admin discussion suggests `Review Notes` should become an expected feedback channel when the reviewer changes or rejects generator behavior.

Recommended product change:

- Reframe `Review Notes` as "admin review feedback and unresolved reviewer caveats".
- Reframe `Last Change Summary` as "what changed in the page".
- Surface this distinction in the review UI near the diff, not only in docs.
- Exclude both `Review Notes` and `Last Change Summary` from RAG-indexed page content.
- Move any caveat that should affect answers into a RAG-visible section such as `Canonical Support Answer`, `Do Not Say`, `Applies When`, or `Evidence / Sources`.
- Keep review notes optional for clean approvals, but expected when:
  - the reviewer corrected a factual claim,
  - narrowed over-broad guidance,
  - removed unsupported advice,
  - changed protocol/version scope,
  - moved information from canonical guidance into a caveat,
  - rejected or skipped a generated proposal,
  - noticed a recurring generator weakness.

Review-note decision rule:

```text
If the final page differs materially from the generated draft, add a Review Notes bullet explaining what was corrected and why.
If the correction should influence future answers, also put the answer-facing rule in a RAG-visible section such as Do Not Say or Canonical Support Answer.
If the final page only had wording cleanup, update Last Change Summary only.
If no meaningful edit was needed, leave Review Notes as-is or add a short positive signal such as "Generated structure matched the source-backed support answer; no prompt issue found."
```

## Historical Code Behavior of Review Notes Before Phase A

Before Phase A, the codebase gave `Review Notes` real RAG impact, but no automatic prompt-learning impact. That RAG impact was accidental and has been removed by the Phase A implementation.

What happened before Phase A:

- `Review Notes` and `Last Change Summary` are normal LLM Wiki body sections.
- The LLM Wiki loader converts the entire page body into `page_content`; it does not strip or separately tag review sections.
- Reviewed or active pages are split into chunks and indexed in Qdrant with the same `llm_wiki` metadata as the rest of the page.
- When an LLM Wiki chunk is retrieved, the response source content can include text from these sections.
- Therefore, these sections can influence generated support answers if retrieved.

What Phase A changed:

- `Review Notes` and `Last Change Summary` are stripped before LLM Wiki content is indexed for RAG.
- `Review Notes`, `Last Change Summary`, section diffs, feedback tags, generator version, prompt version, and future-generator notes are captured as proposal metadata.
- Future LLM Wiki proposal creation can include prior matching generator feedback as guidance.

Implication:

`Review Notes` and `Last Change Summary` are now admin/process metadata, not answerable knowledge. Admins can use them for generator-quality feedback, while answer-facing constraints should live in canonical RAG-visible sections such as `Canonical Support Answer`, `Do Not Say`, `Applies When`, or `Evidence / Sources`.

Phase A implementation:

- `Review Notes` and `Last Change Summary` are stripped from the LLM Wiki body before creating the LangChain `Document`.
- Admin feedback is captured in structured proposal metadata instead of only inside the markdown page body.
- Keep `Review Notes` in the markdown file for reviewer continuity, but not in the vector index.
- Keep `Last Change Summary` in the markdown file for maintenance history, but not in the vector index.
- Regression tests prove admin-only feedback is not present in public RAG context.

This gives the team both things it wants:

- Cleaner RAG behavior from answer-facing sections only.
- Better future generation prompts from admin feedback that is not mixed into customer-facing context.

## Direct Answers for Support Admins

Question: Should I edit `Review Notes`?

Answer: Yes, when the generated page needed a meaningful correction, when a caveat matters for safe answers, or when there is an unresolved point that future reviewers should know. After Phase A, review notes are kept out of indexed RAG content, but answer-facing rules still belong in RAG-visible sections.

Question: Will editing `Review Notes` automatically improve future generated LLM Wiki changes?

Answer: It now improves the next proposal flow indirectly: review notes and feedback metadata are stored and can be surfaced as prior generator feedback for similar future proposals. It does not automatically rewrite prompts or generator code; recurring feedback still needs human review before becoming prompt rules, validators, heuristics, or golden tests.

Question: Can `Review Notes` affect production bot answers?

Answer: No, not after Phase A. The loader strips `Review Notes` and `Last Change Summary` from LLM Wiki RAG content. They should affect humans and prompt-improvement workflows, not production answers directly.

Question: Should I edit `Last Change Summary`?

Answer: Yes, when the page content materially changed. Use it as a maintenance log for future reviewers, not as a feedback note for the generator.

## LLM Wiki Review Notes Feedback Loop

The support-admin discussion raised an important process requirement:

> Review notes should help improve the prompt that generates future LLM Wiki changes.

So `Review Notes` should not be treated as a filler section. They should capture reviewer caveats and corrections for humans. After Phase A, they are not part of RAG-indexed content.

Good review notes should be:

- Specific enough to improve generation prompts.
- About reusable generation behavior, not one-off editing noise.
- Clear about whether the issue is factual, tone, scope, source support, risk, or missing nuance.
- Separated from canonical user guidance.
- Short enough that support admins will actually write them.

Recommended review-note fields:

- `Reviewer correction`: what the reviewer changed.
- `Answer-facing change`: where the reviewer moved the actual user-facing rule, for example `Do Not Say` or `Canonical Support Answer`.
- `Future prompt guidance`: what future generated drafts should do differently.
- `Risk`: why the issue matters.

Made-up example:

Article topic: "Bisq Easy offer disappeared after another user took it"

```markdown
## Review Notes

- Reviewer correction: Reframed the answer around the normal Bisq Easy flow: an offer can disappear because it was taken or removed.
- Answer-facing change: Added the actual support rule to `Canonical Support Answer`: treat "offer disappeared" as a normal offer-lifecycle case first and ask whether the user still sees the offer in the offerbook before suggesting restart or network troubleshooting.
- Future prompt guidance: Future drafts should explain the expected lifecycle before generic troubleshooting when the sources support a normal state transition.
- Risk: Calling a normal taken-offer case a sync failure can make users waste time troubleshooting instead of choosing another offer.
```

Weak review note:

```markdown
## Review Notes

- Edited wording.
```

Why weak:

- It does not say what was wrong.
- It cannot improve the generation prompt.
- It does not tell future reviewers whether the issue was factual, tone, scope, or source coverage.

## Last Change Summary Guidance

`Last Change Summary` should describe the actual document change, not prompt feedback.

Good examples:

```markdown
## Last Change Summary

Clarified that a Bisq Easy offer may disappear because it was taken or removed, and moved generic restart advice out of the canonical first response.
```

```markdown
## Last Change Summary

Added a staff-facing caution that main-branch code evidence must not be used as release-specific user guidance unless the user's version is known.
```

Weak example:

```markdown
## Last Change Summary

Updated article.
```

## Review Notes Versus Last Change Summary

Use `Review Notes` for admin reviewer feedback, unresolved caveats, and future-generator guidance. Do not rely on this section for answer generation.

Use `Last Change Summary` for the factual maintenance log of the page. Do not rely on this section for answer generation.

Examples:

| Situation | Edit Review Notes? | Edit Last Change Summary? |
|---|---:|---:|
| Fixed a hallucinated workflow step | Yes | Yes |
| Removed an unsupported exact UI label | Yes | Yes |
| Reworded for clarity only | Usually no | Yes |
| Approved without changes | Optional positive note | No or minimal |
| Rejected as non-durable | Yes, in proposal/rejection metadata | Not applicable |
| Split a broad generated page into separate topics | Yes | Yes |
| Left an unresolved caveat for future review | Yes | Yes |

Great review-note shape:

```markdown
## Review Notes

- Reviewer correction: Kept the canonical answer general and moved the workaround into a release-verification caveat.
- Answer-facing change: Added the durability rule to `Do Not Say`: do not treat incident-specific workarounds as durable support guidance unless durable wiki, FAQ, code, or release evidence supports them.
- Future prompt guidance: Future drafts should keep temporary workarounds out of the canonical answer unless the evidence shows they are stable.
- Risk: Static workaround advice can become stale and cause users to take unnecessary recovery steps.
```

Great last-change summary shape:

```markdown
## Last Change Summary

Removed incident-specific workaround language, narrowed the canonical answer to source-backed recovery guidance, and added a release-verification caveat.
```

Bad pairing:

```markdown
## Review Notes

- Looks okay.

## Last Change Summary

Updated.
```

Why bad:

- It cannot improve the generator.
- It does not explain the reviewed content change.
- It gives no signal about whether quality was good, merely acceptable, or manually repaired.

## Admin Workflow Improvements

To make review notes useful, add lightweight structure in the admin UI:

- Keep `Review Notes` editable.
- Add a small prompt: "What should future generation do differently?"
- Add optional tags:
  - `factual_correction`
  - `scope_narrowing`
  - `tone`
  - `source_support`
  - `risk_guardrail`
  - `missing_context`
  - `good_generation`
- Store review-note diffs in the knowledge update proposal record.
- Periodically summarize review notes into prompt-improvement candidates.

Potential later automation:

- Mine approved/rejected review notes.
- Cluster recurring prompt issues.
- Generate proposed changes to the LLM Wiki proposal prompt.
- Require human approval before prompt changes.

## Prompt-Improvement Loop From Reviews

The review-note loop should become measurable. This is a proposed future improvement; the current code does not perform this extraction or prompt update automatically.

1. Admin reviews a generated LLM Wiki page.
2. Admin edits canonical content and, when meaningful, `Review Notes`.
3. Approval stores the final markdown and reviewed proposal metadata.
4. A periodic job extracts review-note bullets from approved and rejected proposals.
5. The job clusters notes by issue type:
   - unsupported claim,
   - over-broad scope,
   - wrong protocol,
   - wrong UI specificity,
   - missing caveat,
   - stale or incident-specific guidance,
   - good generation.
6. A human maintainer reviews the clustered notes.
7. Approved prompt changes update the proposal-generation prompt.
8. The next review batch checks whether the same issue rate drops.

The system should not automatically rewrite prompts from review notes. Review notes are evidence for prompt changes, not instructions to apply blindly.

### Generator Feedback Implementation

Human review text can improve LLM Wiki generation if it is captured as training and evaluation data, not if it is merely embedded into the knowledgebase.

Current code gap:

- `KnowledgeUpdateService._build_operations()` creates the generated section edits.
- `KnowledgeUpdateService.update_document_markdown()` stores the admin-edited markdown as both `preview_markdown` and `document_markdown_override`.
- Approval records only a coarse learning event such as approved or rejected.
- The original generated draft, final edited draft, extracted review-note text, and last-change text are not stored as a structured generator-feedback record.

Recommended data capture:

- Preserve the original generated markdown before any manual edit, for example `generated_markdown`.
- Preserve the final approved markdown, for example `approved_markdown`.
- Extract `Review Notes` and `Last Change Summary` from the approved markdown.
- Store an explicit `generation_review_feedback_json` record with:
  - `candidate_id`
  - `proposal_id`
  - `target_page_id`
  - `reviewer`
  - `generated_markdown`
  - `approved_markdown`
  - `review_notes`
  - `last_change_summary`
  - `section_diff_summary`
  - `feedback_tags`
  - `generator_version`
  - `prompt_version`
  - `created_at`

Use `Review Notes` as the main generator-quality signal:

- Extract what was wrong in the generated draft.
- Classify the issue as factual correction, scope narrowing, wrong protocol, weak source support, tone issue, missing caveat, wrong section placement, or good generation.
- Cluster recurring issues across reviewed proposals.
- Convert recurring clusters into proposed generator changes.
- Require maintainer approval before updating prompts, validators, or generator heuristics.

Use `Last Change Summary` as supporting audit data:

- Treat it as a concise label for what changed in the page.
- Use it to validate or summarize diffs between generated and approved markdown.
- Do not treat it as prompt guidance by itself.
- Do not feed it into RAG.

How feedback should improve the generator code:

- Prompt guidance: add reviewed, recurring rules to the LLM Wiki proposal prompt when an LLM prompt is used for generation.
- Few-shot examples: build examples of `candidate + generated draft + review note -> approved section edits`.
- Validators: add `_build_checks()` warnings for repeated failure modes, such as unsupported exact UI labels, over-specific temporary workarounds, or protocol mismatch.
- Heuristics: tune `_build_operations()` defaults, target-page matching, cluster synthesis, and default `Do Not Say` content based on repeated review patterns.
- Evaluation: create golden cases from reviewed proposals and require them to pass before changing generation logic.

Example feedback-to-code path:

```markdown
## Review Notes

- Reviewer correction: The generated draft treated "temporarily locked" as an account ban.
- Answer-facing change: Added a `Do Not Say` guardrail: do not call a temporary lock a ban unless the source evidence uses that wording.
- Future prompt guidance: Future drafts should preserve the user's state wording and ask for the exact lock message before escalating to account-status explanations.
- Risk: Calling a temporary lock a ban can cause unnecessary escalation and confuse the user.

## Last Change Summary

Narrowed the canonical answer to temporary-lock guidance and added a guardrail against unsupported ban language.
```

Generator improvement from that record:

- Add feedback tags: `scope_narrowing`, `terminology_precision`, `risk_guardrail`.
- Add a validator warning when a generated draft introduces `ban` or `banned` but source text only says `locked` or `temporarily locked`.
- Add a prompt rule: "Do not upgrade a user's state wording into a stronger account-status claim unless the source evidence supports that exact claim."
- Add a golden test where a temporary-lock candidate must not generate ban language.

Suggested metrics:

- Percentage of approved pages with material manual edits.
- Percentage of material edits with a review note.
- Common review-note tags by week.
- Repeated generator issue count after prompt changes.
- RAGAS or golden-case pass rate before and after prompt changes.
- Production feedback rate on answers backed by newly approved LLM Wiki pages.

## Critical Review of the Next Implementation Phase

The original first ticket, "create a manually curated code evidence fixture and staff-only retriever", is directionally correct for codebase grounding, but it should not be the immediate next implementation phase.

Reason at the time of review: the LLM Wiki pipeline still had an authority-boundary bug. `Review Notes` and `Last Change Summary` are admin/process sections, but the loader indexed the full page body. Adding more knowledge sources before fixing that boundary would have increased the chance that process metadata, internal critique, or maintenance text influenced customer-facing support answers.

Current status: this boundary bug is fixed by Phase A. The next implementation phase can move to staff-only code evidence and infrastructure grounding, provided the same leakage tests and audience filters are applied.

At the time of that review, the next implementation phase was:

**Phase A: Feedback-Safe LLM Wiki**

This phase created the clean boundary needed for later codebase and infrastructure grounding.

Goals:

- Public/customer RAG sees only answer-facing LLM Wiki sections.
- Admin review feedback is retained for humans and generator improvement.
- The generator-feedback loop has enough structured data to learn from human edits later.
- The implementation is small enough to test thoroughly in one pass.

Non-goals:

- Do not add codebase extraction yet.
- Do not add seed-node or Prometheus live state yet.
- Do not auto-update prompts from review notes.
- Do not create a new vector collection yet.
- Do not redesign the admin UI beyond wording and minimal fields needed for feedback capture.

Recommended sequence:

1. Strip admin-only sections from LLM Wiki RAG documents.
2. Add tests proving `Review Notes` and `Last Change Summary` are absent from `Document.page_content`.
3. Preserve generated-versus-edited proposal state so future analysis can compare before and after.
4. Extract review notes and last-change summaries into structured proposal metadata on approval.
5. Add a minimal admin `Review outcome` flow that captures feedback tags without turning review into a form-filling task.
6. Add a small report or export endpoint for generator feedback records.
7. Rebuild the vector store after deployment because existing vectors may already contain the admin-only sections.

Suggested backend details:

- Add a local helper in `llm_wiki_loader.py`, or a small shared markdown-section utility, that removes sections whose level-2 heading is exactly `Review Notes` or `Last Change Summary`.
- Avoid importing `llm_wiki_update_service.py` from the loader, because that service already imports the loader and a reverse import would create a cycle.
- Keep `source_refs` in `Document.page_content` and metadata.
- Keep frontmatter status/source validation unchanged.
- Add a database migration path for new proposal fields rather than replacing existing columns.

Suggested proposal fields:

- `generated_markdown`: first generated draft before manual full-document edits.
- `approved_markdown`: final markdown written at approval time.
- `review_notes`: extracted text from the final `Review Notes` section.
- `last_change_summary`: extracted text from the final `Last Change Summary` section.
- `section_diff_summary`: deterministic summary of changed sections, initially computed without an LLM.
- `feedback_tags_json`: optional reviewer or system tags.
- `generator_version`: static version for the current generator implementation.
- `prompt_version`: static version if the generation path starts using an LLM prompt later.

Suggested tests:

- `LLMWikiLoader` includes `Canonical Support Answer`, `Applies When`, `Do Not Say`, and `Evidence / Sources`.
- `LLMWikiLoader` excludes review-note and last-change text.
- A reviewed page with only admin-only sections and no answer-facing content should fail validation or produce no indexable body.
- `KnowledgeUpdateService.update_document_markdown()` preserves the original generated draft when a full-document edit is saved.
- `KnowledgeUpdateService.approve()` stores final approved markdown and extracted feedback fields.
- Approval still writes the same reviewed markdown file.
- Existing source-ref checks still pass when feedback fields are present.

Success criteria:

- No admin-only review text can appear in customer-facing retrieved context.
- A human can still see and edit review notes in the markdown/admin workflow.
- A maintainer can export at least a minimal set of generator-feedback examples.
- Existing knowledge-update approval tests continue to pass.
- The implementation touches only the LLM Wiki loader, knowledge-update service, knowledge-update route/schema, minimal review-outcome UI, targeted admin UI copy, and focused tests.

Failure modes to guard against:

- Accidentally stripping similarly named user-facing sections.
- Stripping nested headings inside an answer-facing section.
- Losing source refs during normalization.
- Overwriting the generated draft before feedback capture.
- Treating last-change summaries as prompt instructions.
- Adding broad abstractions for future codebase/infrastructure work before the feedback boundary is proven.

## Support-Admin UX Review for Phase A

The current admin workflow has a strong foundation: queue lanes, a review guide, a full-file diff editor, source badges, generated-answer rating, and a sticky decision panel. A deterministic UI scan of `web/src/app/admin/knowledge-updates/page.tsx` returned no generic design anti-pattern findings.

The main UX risk is not visual quality. It is workflow friction. If review notes feel like a second writing task after the admin has already fixed the page, they will be skipped or deferred. That weakens the long-term goal of a self-improving system.

Design principle for Phase A:

```text
Capture learning signals passively from the admin's normal review actions.
Ask for explicit text only when the system cannot infer the reason for a meaningful edit.
```

Recommended support-admin flow:

1. Admin opens the highest-risk queue lane.
2. Admin reads the final LLM Wiki draft in the existing diff editor.
3. Admin edits answer-facing sections directly when the generated page is wrong.
4. The UI automatically detects changed sections and proposes a compact review outcome.
5. Admin confirms or adjusts one or two feedback tags.
6. Admin optionally adds one short "future generator note" only when the edit was material.
7. Admin approves, rejects, or skips from the sticky decision panel.
8. The system stores both the page change and the generator-feedback event.

This keeps the primary task as "approve a reusable page", not "fill out a feedback form".

Recommended UI changes:

- Add a compact `Review outcome` block inside the sticky `Decision` panel.
- Show it only after the page is dirty, after the generated answer is marked `Needs work`, or when the admin clicks reject/skip.
- Auto-fill the outcome from deterministic signals:
  - changed sections,
  - removed text,
  - added `Do Not Say` guardrails,
  - source-ref changes,
  - protocol changes,
  - answer rating.
- Use selectable feedback chips rather than a required textarea:
  - `Good generation`
  - `Factual correction`
  - `Scope narrowed`
  - `Source support`
  - `Protocol/version`
  - `Tone/wording`
  - `Wrong section`
  - `Missing caveat`
- Keep the text note optional, with a short label such as `Future generator note`.
- Auto-generate `Last Change Summary` from changed sections and let the admin edit it inline only when needed.
- Keep `Review Notes` out of the default markdown-edit path; expose the same feedback in admin UI as structured review metadata.
- Add a small inline reminder near the editor:
  - `Answer-facing sections are used for retrieval. Review notes and last-change summaries are saved for review history and generator feedback, not RAG.`
- Avoid a blocking modal when feedback is missing. Use an inline nudge:
  - `You changed the canonical answer. Add a feedback tag so future drafts can improve.`
  - Actions: `Add tag`, `No generator issue`.

Self-learning implications:

- Every approval should create a feedback event, even when the admin made no edits.
- Clean approvals should record `good_generation` automatically.
- Material edits should record section-level diffs and feedback tags.
- Rejections should require a reason tag, because rejected examples are high-value training data.
- The system should use feedback records for evaluation, prompt proposals, validators, and heuristics, not direct automatic prompt rewrites.
- A later admin report should show recurring generator issues and whether their rate drops after generator changes.

Suggested UI acceptance tests:

- Editing `Canonical Support Answer` reveals the `Review outcome` block.
- Approving an unchanged draft records `good_generation` without requiring text entry.
- Approving a dirty draft with no feedback tag shows an inline nudge, not a modal.
- Selecting feedback tags stores them in the approval request.
- Rejecting requires a reason tag or short reason.
- The inline reminder distinguishes RAG-visible sections from admin-only feedback.
- Keyboard flow remains efficient: save, tag, approve should be reachable without leaving the main review surface.

UX success criteria:

- Clean approvals add no extra mandatory steps.
- Material edits require at most one extra click for a feedback tag.
- The admin never has to manually duplicate the same explanation into both `Review Notes` and `Last Change Summary`.
- The page remains stable while saving or approving; no layout shift around the decision controls.
- The review workflow produces enough structured data to improve generation without making the admin feel like they are training the model.

## Implementation Phases

### Phase A: Feedback-Safe LLM Wiki

Implement the critical boundary and feedback capture described above before adding new knowledge sources.

This phase is the recommended next ticket.

### Phase 0: Evaluation Baseline

Create a small evaluation set before implementation.

Suggested cases:

- Reputation limit prevents sell-offer creation.
- Offer disappears after being taken.
- Mediator mismatch or mediation state confusion.
- Current offer availability versus stale docs.
- Market price unavailable.
- Seed-node or startup/network degradation.
- Bisq2 API support export failing.
- User asks for exact UI path without providing version.

Success criteria:

- Staff brief cites correct evidence.
- Customer-facing answer does not expose staff-only facts.
- Live-state questions include timestamps.
- Ambiguous release-version cases remain cautious.

### Phase 1: Code Evidence Extractor

Build a conservative extractor that creates structured JSONL evidence.

Initial extraction can be pattern-based:

- Java constants.
- Enums.
- REST annotations.
- Exception messages and failure categories.
- Config keys and timeouts.
- Existing markdown specs.

Parser-based extraction can come later. If adding a Java parser dependency, update `api/requirements.in` and regenerate `api/requirements.txt` using the documented Docker workflow.

### Phase 2: Staff-Only Retrieval

Index code evidence for staff-assist only.

Tasks:

- Add loader for `code_evidence.jsonl`.
- Add metadata fields and payload indexes.
- Add retrieval filters for `audience=staff_only`.
- Extend staff-assist payload with `grounding_brief`.
- Add tests proving staff-only evidence does not appear in public chat responses.

### Phase 3: LLM Wiki Promotion

Allow code facts to become LLM Wiki source refs.

Tasks:

- Add `code:` refs to allowed source-ref formats.
- Add page types if needed:
  - `implementation_note`
  - `support_diagnostic`
  - `infra_runbook`
- Add review checks for code source refs.
- Require reviewer approval before customer-facing use.

### Phase 4: Live Infrastructure Context

Add infrastructure state as a live context provider.

Tasks:

- Wrap existing Bisq2 readiness snapshot.
- Query Prometheus for selected alert/health signals.
- Add seed-node probes when stable.
- Add TTL and timestamp enforcement.
- Add prompt policy stating live infrastructure status beats static docs for current outages.

### Phase 5: Limited Customer-Facing Use

Only after evaluation passes:

- Allow `public_reviewed` code-derived LLM Wiki pages into normal RAG.
- Keep raw `code_fact` evidence out of customer responses.
- Add monitoring for hallucination, unsupported claims, and source leakage.

## Testing Requirements

Minimum tests:

- Code evidence loader validates required fields.
- Staff retrieval includes `staff_only` evidence.
- Public chat retrieval excludes `staff_only` evidence.
- LLM Wiki pages with `code:` refs require review before indexing.
- Infrastructure context is omitted when stale.
- Live state includes timestamps and source names.
- Source extraction and response models do not leak internal paths to public users.

Evaluation:

- Run existing retrieval benchmark harness before and after.
- Add targeted golden cases for code/infrastructure topics.
- Track whether generated answers cite reviewed sources instead of raw code.

## Security and Privacy Controls

- Never index secrets, private keys, wallet data, local profiles, logs, or runtime caches.
- Do not expose raw file paths, class names, stack traces, or internal endpoint details to users unless reviewed as public guidance.
- Redact sensitive config values before indexing.
- Tie code facts to commit hashes.
- Prefer release-bound evidence for customer guidance.
- Mark main-branch-only facts as staff-only unless reviewed.

## Open Decisions

- Use a separate Qdrant collection for staff-only code evidence, or the existing collection with strict filters?
- Which Bisq2 release/version metadata can be reliably attached to support conversations?
- Should staff grounding briefs be generated for every escalated case or only when confidence is low?
- How should seed-node probes run in production without creating noisy network load?
- Should review notes be stored only in markdown, or also normalized into proposal metadata for prompt improvement?
- Should the first implementation store generator-feedback fields in `knowledge_update_proposals`, or in a separate `knowledge_update_feedback` table?
- Should feedback tags be manually selected in the admin UI, inferred from review-note text, or both?

## Proposed First Ticket

Implement Phase A as the smallest safe version:

1. Strip `Review Notes` and `Last Change Summary` from LLM Wiki RAG documents.
2. Add loader tests that prove admin-only sections are excluded from `Document.page_content`.
3. Preserve the original generated proposal markdown before admin full-document edits.
4. Store final approved markdown plus extracted review-note and last-change text on approval.
5. Add focused service tests for before/after feedback capture.
6. Add the minimal `Review outcome` UI in the sticky decision panel:
   - auto-detect changed sections,
   - default unchanged approvals to `good_generation`,
   - show feedback chips only when they are useful,
   - collect an optional future-generator note.
7. Update admin UI hints so support admins know that answer-facing rules belong in canonical sections, while review notes are generator feedback.
8. Rebuild the vector store after deployment.

Defer code evidence, staff grounding briefs, and infrastructure state until this boundary is verified.

## Implementation Status - 2026-06-26

Phase A is mostly implemented and deployed.

Completed:

1. `Review Notes` and `Last Change Summary` are stripped from LLM Wiki RAG documents by `api/app/services/rag/llm_wiki_loader.py`.
2. Loader tests prove admin-only sections are absent from `Document.page_content`, while answer-facing sections and `source_refs` remain.
3. The knowledge update service preserves generated markdown before full-document edits.
4. Approval stores final approved markdown, extracted review notes, extracted last-change summary, section diff summary, feedback tags, generator version, and optional future-generator notes.
5. Admin routes expose a generator-feedback export endpoint.
6. The admin UI has review-outcome feedback chips, inferred feedback tags, optional future-generator note capture, and copy that separates generator feedback from customer-facing RAG.
7. Future LLM Wiki proposals can surface prior matching generator feedback, which is the first lightweight self-learning loop.
8. Production was deployed after Phase A and the vector store was rebuilt/restarted through the normal update flow.

Additional follow-up implemented after the nginx incident:

- Public `/api/health` should now be a minimal health payload, not the detailed internal `/health` diagnostics.
- CI should validate nginx config syntax for both local and production nginx configs.
- Deployment change detection should not restart API for `api/tests/`-only changes, avoiding confusing stale API build metadata after non-runtime PRs.

Pending items identified before the staff-only code-evidence slice:

1. Add retrieval/generation evaluation cases that prove review-note leakage remains impossible after future changes.
2. Decide whether code-derived facts use a separate staff-only collection or strict metadata filters.
3. Define the code-evidence schema and redaction rules, including commit hash, release/version applicability, source visibility, and customer-safe status. Implemented in the first staff-only slice.
4. Prototype a staff-only grounding brief that augments support-admin review, not customer-facing RAG. Implemented as a staff-assist payload field in the first staff-only slice.
5. Add infrastructure/seed-node state as timestamped live context only after freshness and noise controls are defined.

## Implementation Status - Staff-Only Code Evidence Slice

Implemented locally after Phase A:

1. Added a strict `code_fact` JSONL schema at `{DATA_DIR}/code_knowledge/code_evidence.jsonl`.
2. Added `CodeEvidenceLoader` and `StaffCodeEvidenceRetriever` for file-backed, staff-only code evidence retrieval.
3. Added redaction for obvious secret, token, password, and API-key text during loading.
4. Added a minimum relevance gate so incidental metadata matches do not create noisy staff briefs.
5. Added `GroundingBriefService` and wired it into `StaffAssistService` through channel bootstrap.
6. Staff-only evidence is attached to `StaffAssistPayload.grounding_brief`; public `knowledge_sources` remain unchanged.
7. Code evidence is not indexed into the public Qdrant collection in this slice.

Still pending after this slice:

1. Build the actual Bisq2/support-agent code extractor that emits the JSONL records.
2. Decide whether the next retrieval implementation should use a separate staff-only Qdrant collection or keep file-backed retrieval until volume requires indexing.
3. Add a staff-admin UI rendering section for `grounding_brief` if the current sink/UI does not expose it yet.
4. Add `code:` source-ref promotion checks for reviewed LLM Wiki pages.
5. Add live infrastructure and seed-node state as timestamped context, not static RAG.

Current answer to "how far are we with codebase knowledgebase integration":

We are not ingesting raw codebase facts into the customer-facing knowledgebase yet. That is intentional. The prerequisite feedback boundary is in place, and the first staff-only code-evidence pilot now exists as file-backed retrieval feeding `StaffAssistPayload.grounding_brief`. The next safe phases are the actual code extractor, visible staff-admin rendering, `code:` source-ref promotion checks, and live infrastructure context.

## Skills Review

Skills used for this plan review:

- `karpathy-guidelines`: kept the next phase surgical, testable, and constrained to the real defect.
- `prompt-engineer`: shaped the review-note loop into structured feedback that can later improve generator prompts without blindly applying reviewer text.
- `find-skills`: searched the public skill ecosystem for additional review support.
- `skill-installer`: installed the selected review/evaluation skills.
- `ui-design-principles`: applied speed-through-subtraction, progressive disclosure, stable decision placement, and feedback immediacy to the support-admin flow.
- `impeccable`: loaded the product/design context and reviewed the knowledge-update UI as an operator-grade product workflow.
- `code-review-testing`: reinforced that Phase A needs integration-style tests around user-facing behavior, not only isolated helpers.
- `evaluate-rag`: reinforced separating retrieval leakage tests from generation-quality evaluation.

Potential skills to install before implementation:

- Installed: `hamelsmu/evals-skills@evaluate-rag`, useful for RAG evaluation design once we add golden cases and retrieval checks.
- Installed: `openai/codex@code-review-testing`, useful for stricter implementation review and test planning around the next PR.
- `bagelhole/devops-security-agent-skills@rag-observability-evals`: potentially useful later when infrastructure state and observability enter the RAG/support workflow.

Do not install more RAG implementation skills yet. The current repo already has a concrete RAG architecture, and generic RAG-builder skills are less valuable than focused evaluation and review skills for this phase.
