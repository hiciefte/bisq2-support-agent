# Code Evidence Schema

Code evidence is structured implementation knowledge for human support staff. Raw
`code_fact` records are not public RAG content. Durable code-derived support
facts can become customer-facing only after promotion into a reviewed LLM Wiki
page with customer-safe wording and pinned `code:` source references.

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
  "public_guidance": "Explain that Bisq Easy trade limits can depend on seller reputation and ask the user for their Bisq version before giving version-specific limits.",
  "applies_to_versions": ["2.1.0"],
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
- `public_guidance`: optional for `staff_only`; required for `public_review_candidate` and `public_reviewed`
- `applies_to_versions`: optional list of release/version labels

Current behavior:

- Only `audience=staff_only` records are retrieved by `StaffCodeEvidenceRetriever`.
- Code evidence is attached only to staff-only metadata: `staff_grounding_brief` and `staff_enriched_answer`.
- Matrix/Bisq2 channel responses with code evidence are forced into human review and posted to the configured staff room.
- Code evidence is not loaded into the public Qdrant collection.
- Code evidence is not included in public `knowledge_sources`.
- Code-enriched staff context is not sent by Matrix reactions or `/send`; those actions send only the copy-ready draft unless staff supplies edited text.
- Obvious secret/token/password text is redacted during loading.
- Admins can promote selected code evidence into the normal LLM Wiki review queue.
- Promotion requires a precise `code:<repo>@<commit>:<path>:<line_start>-<line_end>` source ref that matches the structured evidence metadata.
- Reviewed or active LLM Wiki pages with `code:` refs are rejected by the loader unless all code refs are pinned and line-specific.
- Approved code-derived guidance enters customer-facing RAG as reviewed LLM Wiki content, not as raw code evidence.

## Generation

Code evidence can be generated deterministically from a source checkout:

```bash
python -m app.scripts.generate_code_evidence \
  --repo-path /path/to/bisq2 \
  --repo bisq2 \
  --output api/data/code_knowledge/code_evidence.jsonl
```

The generator currently extracts conservative staff-only facts from:

- Java constants.
- Java enum states.
- Java REST annotations.
- Java exception messages from static `throw new ...("message")` expressions.
- FastAPI `HTTPException(detail="...")` responses.
- `.conf` and `.properties` defaults, excluding sensitive keys.
- Markdown specification sections.

Generation validates every row through the same `CodeEvidenceRecord` schema used by
runtime loading. The command also runs a freshness check and exits non-zero if a
generated record points at a missing file or invalid line range.

Exception/error-message records are always staff-only and high risk. They are useful
for matching a user-provided error text to a likely code path, but staff should not
paste raw class names, stack traces, internal file paths, or route names to customers
unless that wording has been promoted into reviewed support guidance.

## Evaluation

Staff-only code evidence retrieval can be checked without Qdrant or an LLM:

```bash
python -m app.scripts.evaluate_code_evidence \
  --evidence api/data/code_knowledge/code_evidence.jsonl \
  --cases api/data/evaluation/code_evidence_cases.json \
  --output api/data/evaluation/code_evidence_eval.json
```

Evaluation cases are JSON or JSONL records:

```json
{
  "question": "Why can I not create a Bisq Easy sell offer?",
  "protocol": "bisq_easy",
  "expected_ids": [
    "bisq2:abc123:BisqEasyTradeAmountLimits.MAX_SELL_OFFERS:77"
  ]
}
```

The evaluator reports `recall_at_k`, MRR, and missing expected IDs. This keeps
retrieval quality separate from answer generation quality.

Promotion path:

1. Use code evidence for staff investigation only.
2. Convert durable facts into LLM Wiki proposals with customer-safe `public_guidance`.
3. Cite precise `code:` source refs pinned to commits and line ranges.
4. Require human review before the fact can become customer-facing guidance.
5. Keep raw file paths, class names, stack traces, and line numbers out of customer-facing answers unless explicitly reviewed.


### Release-bound evidence for the staff experiment

Generate evidence from a clean, isolated Git checkout whose HEAD is the exact full
commit verified for an official release tag. Pass `--release-tag vX.Y.Z` together
with `--freshness-class release_bound`; write output outside the source checkout.
The generator rejects mismatched HEAD/tag identity, dirty source, and committed
source files whose bytes differ even when Git index flags hide the change.
An EOL-normalization status is accepted only when the file bytes exactly equal
its HEAD blob. Generation runs a final freshness check before writing output.

Release records require `release_tag`, a full `source_sha256` for the referenced
file, a full commit SHA and `applies_to_versions: ["X.Y.Z"]`. The source checker
compares file content as well as source-reference bounds. Official remote tag
verification remains a commissioning step: a locally created tag alone does not
prove that upstream published that release. A source release also does not prove
that a user's client or the live network has that version or feature activated.

Staff retrieval accepts an optional `user_version`. A known version returns only
release-bound records for that exact version. Grounding also recognizes explicit
version wording in the current user question and verifies the version filter again
before formatting. With no confirmed version, release facts remain visibly labeled
as investigation context and the brief warns that the installed version is unknown.
This does not infer installed versions from retrieved documents or cover versions
mentioned only in older conversation turns.

The bounded experiment data belongs at
`{DATA_DIR}/code_knowledge/code_evidence.jsonl`, outside the public Qdrant index.
The loader reads this file on each staff-grounding request, so an atomic data-file
replacement needs no index rebuild or service restart after the code is deployed.
Keep its provenance manifest with the deployment evidence. No source fact becomes
public knowledge without the separate reviewed LLM Wiki promotion process.

### Product and release selection

The staff resolver derives product and explicit version from accumulated user
incident text, not a retrieved article's release. Repository filtering is
independent of protocol: a Bisq 2 `protocol=all` Tor fact cannot become Bisq 1
implementation evidence. Exact error phrases (`match_terms`) and complete code
identifiers rank ahead of whole-token lexical matches.

A supplied version requires an exact release match. Without one, code and release
notes use the latest available stable source release for that product and state
that the installed version is unconfirmed. Older snapshots remain available for
users who identify an older version. One response does not combine code snapshots
from multiple releases of the same product. A source match does not establish the
cause of an individual trade failure.

### Recent release snapshots and upkeep

`app.scripts.refresh_release_evidence` uses the existing deterministic extractor.
It discovers the latest three stable official GitHub releases for both products,
verifies each remote tag's full commit, checks out that tag in dedicated clean
source mirrors, and prepares a new artifact directory. It makes no model calls
and never writes production data. Run it from `api/`:

```bash
python -m app.scripts.refresh_release_evidence \
  --bisq-checkout /isolated/bisq \
  --bisq2-checkout /isolated/bisq2 \
  --previous-code /reviewed/code_evidence.jsonl \
  --previous-notes /reviewed/release_notes.jsonl \
  --output /new/release-evidence
```

For initial preparation, omit absent `--previous-*` files. Checkouts must be
isolated disposable mirrors: this command changes their checked-out tag and
fetches public tags. It refuses dirty source and an existing output directory.
`--discovery-cache` and `--offline` reproduce an already reviewed snapshot; the
report explicitly marks remote verification absent in offline mode.

The output is a review package:

- `code_evidence.jsonl`: curated facts with exact commit, file, line range, file
  hash, repository and release applicability. Multi-file facts check every
  source reference against the same commit.
- `release_notes.jsonl`: official release text with repository, tag, source commit,
  publication date, exact official release URL and body SHA256. Runtime validates
  these fields and retrieves bounded relevant excerpts.
- `coverage.json`: artifact hashes, included releases and optional coverage gaps.
- `official-release-responses.json`: public discovery responses for audit.

Claims are reused only while their complete reviewed source excerpt still
matches. Required-family changes stop preparation before output; optional changed
spans are reported and omitted. Changed source requires review of the recipe,
claim and regression. Historical snapshots from the previous package are
preserved; changed commits for existing tags are rejected. Release notes remain
attributed release statements, not confirmation of a fix on a user's installation.
There is no request-time GitHub fetch or whole-codebase embedding.

The initial coverage is deliberately limited:

| Product | Curated families | Initial recent releases |
| --- | --- | --- |
| Bisq 1 | Trade phases; deposit-state predicate; offer states; wallet/SPV replay trigger; mediation acceptance versus payout; exact mediated-payout address validation chain | 1.10.8, 1.10.7, 1.10.6 |
| Bisq 2 | Payment states; reputation amount and offer limits; market-price dependency; mediation request/history/authorization/pending response; take-offer errors; Tor bootstrap; reputation authorization specifications where unchanged | 2.1.13, 2.1.12, 2.1.11 |

Bisq 2 2.1.11 lacks the two later reviewed reputation-authorization spans; they
are omitted. Bisq 1 DAO recovery, refund/arbitration internals and wallet repair
procedures are not covered. These facts do not provide complete codebase coverage.

The `Prepare upstream release evidence` GitHub Actions workflow checks official
releases every six hours and supports manual dispatch. Its schedule takes effect
once this workflow is merged into the default branch and Actions is enabled.
Unchanged tag commits, release text and extraction rules reuse the existing
candidate artifact; changed inputs prepare a new candidate with coverage. A tag
change between discovery and preparation prevents artifact publication. The job
uses public sources and has no provider or production credentials.

This automates **preparation**, not approval or installation. Review coverage and
retrieval regressions, then merge any retained older release snapshots and install
**both** runtime JSONL files together through the controlled knowledge-data rollout.
The CI artifact covers the current three releases per product; it does not read or
replace the production corpus. Verify hashes and exact-version queries before
staff generation resumes. A merged workflow, a successful preparation, and an
installed package are distinct states and must be reported separately.
