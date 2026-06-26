# Code Evidence Schema

Code evidence is structured implementation knowledge for human support staff. It is not public RAG content.

The first implementation reads:

`{DATA_DIR}/code_knowledge/code_evidence.jsonl`

Each line is one JSON object:

```json
{
  "id": "bisq2:abc123:BisqEasyTradeAmountLimits:getMaxUsdTradeAmount",
  "type": "code_fact",
  "repo": "bisq2",
  "commit": "abc123",
  "path": "bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java",
  "line_start": 77,
  "line_end": 84,
  "symbol": "BisqEasyTradeAmountLimits.getMaxUsdTradeAmount",
  "protocol": "bisq_easy",
  "audience": "staff_only",
  "freshness_class": "main_branch",
  "risk_level": "medium",
  "claim": "Bisq Easy caps reputation-based trade amount at 600 USD.",
  "support_use": "Use for staff investigation of trade-size limits.",
  "source_refs": [
    "code:bisq2@abc123:bisq-easy/src/main/java/bisq/bisq_easy/BisqEasyTradeAmountLimits.java:77-84"
  ]
}
```

Allowed values:

- `type`: `code_fact`
- `audience`: `staff_only`, `public_review_candidate`, `public_reviewed`
- `freshness_class`: `release_bound`, `main_branch`, `generated`
- `risk_level`: `low`, `medium`, `high`
- `protocol`: `bisq_easy`, `multisig_v1`, `musig`, `all`

Current behavior:

- Only `audience=staff_only` records are retrieved by `StaffCodeEvidenceRetriever`.
- Code evidence is attached only to staff-only metadata: `staff_grounding_brief` and `staff_enriched_answer`.
- Matrix/Bisq2 channel responses with code evidence are forced into human review and posted to the configured staff room.
- Code evidence is not loaded into the public Qdrant collection.
- Code evidence is not included in public `knowledge_sources`.
- Code-enriched staff context is not sent by Matrix reactions or `/send`; those actions send only the copy-ready draft unless staff supplies edited text.
- Obvious secret/token/password text is redacted during loading.

Promotion path:

1. Use code evidence for staff investigation only.
2. Convert durable facts into LLM Wiki proposals with `code:` source refs.
3. Require human review before the fact can become customer-facing guidance.
4. Keep raw file paths, class names, stack traces, and line numbers out of customer-facing answers unless explicitly reviewed.
