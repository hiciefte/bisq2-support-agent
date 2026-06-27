# LLM Wiki Human Review Analysis - 2026-06-27

## Scope

Input reviewed batch:

- reviewed batch zip file provided by the support admin
- 20 markdown pages under `llm-wiki-pages.new/`

Compared against generated originals:

- `api/data/knowledge/llm_wiki/pages/*.md`

Human reviewer signal:

- The reviewer mostly corrected the wiki content itself.
- Review notes and last-change summaries were not maintained consistently.
- The reviewer stopped paying attention to `risk_level`.
- One initially weak page, `bisq2-overview-trade-totals`, was rescued by making it more purposeful.

## Loader Validation

The reviewed files still have:

- `status: proposed`
- `reviewed_by: null`
- `reviewed_at: null`

Direct loader result:

- `LLMWikiLoader.load_documents(reviewed_zip_dir)` returns `0` documents.

After normalizing the temp copy to `status: reviewed`, `reviewed_by: suddenwhipvapor`, and `reviewed_at: 2026-06-27`:

- 20 of 20 documents load.
- No document is missing `source_refs`.
- `Review Notes` and `Last Change Summary` do not leak into `Document.page_content`.

Conclusion: these pages must be imported through an approval/import workflow or explicitly normalized before they can become customer-facing RAG content. Manual file copying as-is would not activate them.

## Quantitative Diff Summary

- Files reviewed: 20.
- Average full-file similarity: 0.854.
- Total word delta: +312 words.
- `Canonical Support Answer` changed in 20 of 20 pages.
- `Do Not Say` changed in 8 of 20 pages.
- `Applies When` changed in 4 of 20 pages.
- `Review Notes` changed in 6 of 20 pages.
- `Last Change Summary` changed in 8 of 20 pages.
- `risk_level` changed in 1 of 20 pages.

Most changed pages by full-file similarity:

| Page | Main change |
|---|---|
| `bisq2-btc-only-altcoin-path` | Clarified Bisq Easy as BTC-focused and Bisq 1 as the normal path for non-BTC markets. |
| `bisq1-bsq-fee-payment` | Added BSQ colored-bitcoin behavior and tightened dust/change-threshold handling. |
| `bisq2-overview-trade-totals` | Corrected overview totals from vague history/accounting guidance to current offer-book totals. |
| `bisq1-offer-fee-tx-not-found` | Replaced generic recovery advice with a transaction-state decision tree. |
| `bisq1-fiat-stablecoin-routing` | Tightened fiat-to-altcoin/stablecoin route wording. |
| `bisq1-sepa-payment-name-proof` | Added SEPA name-mismatch and payment-reference operational rules. |
| `bisq2-profile-data-recovery` | Added default data-directory locations and backups-folder guidance. |

## What The Reviewer Improved

### 1. Generic Answers Became Operational Decision Trees

The generator often produced correct but generic support advice. The reviewer converted several articles into concrete decision logic.

Examples:

- Offer-fee transaction issue:
  - Generated: verify fee mode, check txid, maybe SPV resync, maybe recreate offer.
  - Reviewed: if maker fee tx exists and is unconfirmed, wait; if it does not exist, no fee was paid and SPV resync may fix wallet state; if confirmed but offer still disables, manually re-enable and restart.
- SEPA name/payment reference:
  - Generated: do not invent a reference requirement and involve mediation for material changes.
  - Reviewed: payment reference should normally be blank or buyer name; custom references are not allowed; marginal name variations may be acceptable; non-agreed references should go to mediation.
- Bisq 2 overview totals:
  - Generated: incomplete totals/history may be profile/history scope.
  - Reviewed: overview totals represent current offer-book amounts, not historical bought/sold totals.

Learning: the generator needs a "decision tree first" mode for troubleshooting pages. A page is only high quality when it tells support what to ask/check next and how each branch changes the answer.

### 2. Human Support Added Missing Domain Invariants

Recurring added or tightened rules:

- Bisq does not receive fiat and does not custody user assets.
- Bisq Easy is BTC-focused; Bisq 1 is the current normal route for many non-BTC/altcoin market needs.
- Bisq 1 wallet/SPV advice must not be applied to Bisq 2.
- Wallet seed recovery is funds recovery, not full Bisq application-state recovery.
- Data-directory backup must come before restore/delete/protobuf/database work.
- Stale UI state must be separated from actual on-chain transaction state.
- Mediation is needed before releasing BTC when payment details are materially wrong.

Learning: these should become generator policy rules, not rediscovered per article.

### 3. Exact Values Need Source-Backed Freshness Checks

The original `bisq1-bsq-fee-payment` page explicitly warned not to quote exact dust thresholds unless verified. The reviewer added a concrete `5.46 BSQ` threshold, but local source validation did not establish that value as durable fee-payment guidance. The activated page therefore keeps the support meaning while avoiding a hard-coded unverified value.

Learning: the correct rule is not "avoid exact values" or "accept exact values because a reviewer typed them." The correct rule is:

- exact values are allowed when source-backed and version-scoped;
- exact values should trigger a source/freshness check;
- unverified exact values should remain a review blocker or staff-only caveat.

### 4. Scope And Negative Constraints Matter

`Do Not Say` changed in 8 pages. This is a strong signal that the generator should extract negative constraints as first-class output, not merely append a generic "do not extrapolate" bullet.

Common negative constraints:

- Do not say funds are lost before on-chain state is checked.
- Do not advise clearing stale UI state when the underlying trade is unresolved.
- Do not present Bisq as custodian or broker.
- Do not use Bisq 1 SPV/DAO advice for Bisq 2-only issues.
- Do not tell users to use the same data directory on multiple active installs.

### 5. Risk Level Is Not A Human Review Control

Only one `risk_level` changed, and the reviewer explicitly stopped paying attention to it.

Learning:

- Keep `risk_level` system-derived.
- Show it only when it changes behavior, for example blocks auto-activation, requires source coverage, or flags high-risk instructions.
- Replace the raw flag in the admin workflow with specific reasons: "funds-at-risk", "version-sensitive", "requires mediator", "exact value added", "data deletion/restoration".

### 6. Review Notes Are Useful But Not Reliable Enough

The reviewer did add some review notes, but the most valuable feedback is in the content diff itself. Relying on `Review Notes` would miss the strongest signal: every page changed its canonical answer.

Learning:

- Use review notes as optional explanatory metadata.
- Treat section diffs as the primary self-learning signal.
- Auto-generate reviewer feedback from changed sections so the admin does not have to duplicate effort.

### 7. Human Edits Need A Light Cleanup Pass

The reviewed content is semantically valuable but contains some copy-editing issues, such as `tablooks`, `Ficed`, `custory`, `sellinig`, `walle`, and inconsistent `MacOS` spelling.

Learning: add a non-semantic prose cleanup check after human edits and before activation. It should suggest spelling/grammar fixes without changing support meaning. The imported batch was cleaned for these issues before activation.

## Product And System Improvements

### A. Add A Batch Review Importer

Build a small import path for externally reviewed markdown batches.

Inputs:

- reviewed zip/directory;
- original generated page directory;
- reviewer id;
- review date.

Importer responsibilities:

1. Match reviewed pages to generated originals by `id`/filename.
2. Normalize frontmatter: `status: reviewed`, `reviewed_by`, `reviewed_at`.
3. Preserve original generated markdown.
4. Compute section-level diffs.
5. Infer feedback tags from section diffs and textual cues.
6. Extract `Review Notes` and `Last Change Summary` when present.
7. Run `LLMWikiLoader` validation and leakage checks.
8. Flag prose issues and source-coverage gaps before activation.
9. Write feedback records so future proposals can learn from this batch.
10. Only then replace/approve the pages and rebuild the vector store.

This is the most important next step because it converts the human review batch into structured learning data.

Implementation status:

- Added `ReviewedLLMWikiBatchImporter` in `api/app/services/knowledge_updates/llm_wiki_review_importer.py`.
- Added `api/app/scripts/import_reviewed_llm_wiki_batch.py` for zip/directory imports.
- Added `llm_wiki_review_feedback` SQLite records so externally reviewed batches feed the existing generator-feedback context.
- Reused the existing `/admin/knowledge-updates/generator-feedback` path and proposal generator feedback card instead of adding a parallel feedback system.
- Verified the provided batch in report-only mode: 20/20 pages matched originals, 20/20 normalized pages loaded through `LLMWikiLoader`, no admin-section leakage, no missing originals, no invalid pages.
- Cleaned the reviewed batch before activation, including obvious typos and source-sensitive evidence notes.
- Applied the normalized reviewed pages to `api/data/knowledge/llm_wiki/pages`: all 20 pages are now `status: reviewed`, `reviewed_by: suddenwhipvapor`, and `reviewed_at: 2026-06-27`.
- Recorded 20 external review-feedback rows locally so future page-generation proposals can learn from the human deltas.

### B. Add Diff-Derived Generator Feedback

Current feedback extraction is too dependent on explicit future-generator notes. Add a diff analyzer that produces durable learning records from edited sections.

Recommended tags:

- `canonical_answer_rewrite`
- `decision_tree_missing`
- `missing_domain_invariant`
- `missing_exact_value`
- `exact_value_added`
- `scope_too_broad`
- `do_not_say_missing`
- `source_coverage_needed`
- `copy_edit_needed`
- `metadata_not_reviewed`

Example derived feedback:

```json
{
  "page_id": "bisq2-overview-trade-totals",
  "changed_sections": ["Canonical Support Answer", "Review Notes", "Last Change Summary"],
  "feedback_tags": ["canonical_answer_rewrite", "decision_tree_missing", "source_coverage_needed"],
  "future_generator_note": "For UI totals/history topics, distinguish current offer-book totals from historical trade volume before writing accounting or profile-history guidance."
}
```

### C. Improve The Generation Prompt

Add these rules to the proposal generator:

1. Write the canonical answer as a support decision tree when the topic involves troubleshooting, funds, data recovery, trade state, payment mismatch, or network state.
2. Include the first check support should ask for, the branch outcomes, and the safe next action.
3. Extract at least 3 topic-specific `Do Not Say` bullets. Avoid generic filler.
4. Separate UI state, local wallet/app state, and on-chain state.
5. Do not mix Bisq 1 wallet/SPV/DAO advice into Bisq 2 articles.
6. For exact thresholds, paths, fees, or version-sensitive facts, include them only when the source is durable and mark them for freshness/source validation.
7. If evidence does not support a concrete answer, skip the page or label it as needing source support instead of creating a weak "nothing burger" page.

### D. Add A Usefulness Gate

Before showing a generated wiki proposal to support staff, require:

- a concrete user question or symptom;
- a canonical answer with at least one branch, exception, or next-step check;
- topic-specific `Do Not Say` constraints;
- durable source refs;
- no unsupported exact values;
- no obvious cross-protocol mixup.

If this gate fails, hold the candidate as "needs more evidence" instead of asking the admin to rescue it manually.

### E. Make Risk Human-Meaningful

Replace the visible raw `risk_level` review affordance with reason chips:

- Funds at risk
- Data deletion/restoration
- Mediation/arbitration
- Version-sensitive
- Exact value/path
- Protocol boundary

The system can still store `risk_level`, but the support admin should not have to reason about an abstract flag.

### F. Add Source Coverage Checks For Added Claims

When a reviewer adds content containing any of these patterns, require source confirmation or reviewer acknowledgment:

- exact numbers, thresholds, dates, fees, or limits;
- OS paths, file paths, protobuf/database filenames;
- strong modal claims: `must`, `never`, `not allowed`, `is not recoverable`;
- current UI labels;
- version-specific behavior.

This prevents semantically valuable but unsourced edits from becoming brittle RAG facts.

### G. Add A Non-Semantic Copy-Edit Check

Before activation, run a spelling/grammar pass that:

- flags obvious typos;
- does not rewrite product meaning;
- presents suggestions as one-click fixes;
- keeps the final support admin in control.

## Completed Implementation Ticket

Implemented a "Reviewed LLM Wiki batch importer and feedback miner".

Acceptance criteria:

1. Given the reviewed zip and original generated directory, the importer reports all 20 matched pages.
2. It produces normalized reviewed markdown with `reviewed_by` and `reviewed_at`.
3. It verifies 20/20 pages load through `LLMWikiLoader` and that admin-only sections do not index.
4. It computes section-level diffs and feedback tags.
5. It flags copy-edit issues and source-coverage-sensitive additions before activation.
6. It stores/imports feedback so future proposals can surface prior human corrections.
7. It does not require manually maintained `Review Notes` to learn from the batch.

Next generator-quality work should focus on the usefulness gate, stronger source-coverage checks for exact values, and prompt changes that produce decision-tree-style support pages by default.
