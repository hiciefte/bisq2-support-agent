# Knowledge learning and review

The learning workflow maintains a reviewed LLM Wiki. It does not train model
weights or make FAQ volume a quality target. Public FAQs remain an optional
publishing destination for useful standalone references.

## One candidate pipeline

Matrix and Bisq history sync feed the same knowledge extractor and candidate
repository. These imports are separate from the live Matrix response listener.
The extractor groups questions and staff answers. Staff replies are evidence to
review, not automatic ground truth.

Intake saves each candidate before any optional answer comparison. New candidates
have no generated answer, confidence or comparison score. They enter full review
as **Not evaluated**, rather than looking like a poor answer or calibrated result.
An operator may generate a comparison using the existing review control.

The existing wiki coverage matcher runs against saved candidates. Its provenance
and product guards are retained: an uncited new candidate cannot be automatically
accepted just because its words resemble a wiki page. Known public sources can be
added in document review or recovered by an explicitly requested comparison.
Missing citations remain visible in the queue but block publication.

Topic grouping and coverage reconciliation reuse the existing services. They do
not require a second candidate store or a parallel conversation grouping system.

## Review and publication

`/admin/knowledge-updates` is the review entrance; `/admin/training` redirects to
it. For an existing page, the draft preserves current canonical guidance and
applicability instead of appending another staff answer. The reviewer edits the
complete document, checks conflicts and product/version scope, and explicitly
saves the review before approval. Existing saved drafts are not discarded on read.
Resetting a draft is a separate explicit action.

FAQ creation stays in the secondary **Optional public FAQ** control. Existing FAQ
records and their public URLs are preserved. The Bisq Wiki, reviewed LLM Wiki and
verified FAQs remain retrieval sources; this change does not replace that mix.

Approval means the markdown was saved. It marks the retrieval index stale; it does
not silently run a paid rebuild. The review UI retains the most recent approval
for the current session and offers **Check index**. This read-only action compares
all expected chunks and metadata for that exact approved revision with the active
Qdrant collection, and detects stale extra chunks and alias/page changes during
readback. It calls no model and creates no embeddings. An unavailable read returns
unknown, not success.

**Indexed is not answer-quality verified.** The UI explicitly keeps the answer
check as not run. Use a separately scoped before/after evaluation of the original
question to measure quality; indexing alone must never count as a passing answer.

## Reliable sync and bounded context

New events may use earlier messages as context, but an already-processed answer
cannot become a new candidate. Bisq normally includes one hour of history and up
to 50 preceding same-channel messages. If a new staff reply lacks its question or
an explicit citation root, one recovery export may look back up to 30 days, capped
by configured retention and 1,000 returned events. Only bounded same-channel
context and at most 10 citation roots reach extraction.

Matrix resolves at most 10 missing reply or boundary anchors with bounded native
room-context reads. Reactions, membership events and empty messages are not
question context. If required context cannot be recovered within these bounds,
the input is deferred without a model call or consumption of its cursor/IDs.
This is not unlimited historical conversation recovery.

Matrix bootstraps from recent history and then advances its saved cursor forward.
Existing tokens and identities are retained. Successfully completed Bisq channels
can checkpoint their processed IDs even if another channel fails.

A metadata-only extraction receipt is written before a provider attempt. Completed
identical input can be reconciled without another call. Extraction errors,
malformed output, invalid message attribution and partial persistence failure are
not treated as successful empty batches. Uncertain attempts hold their source
scope for operator reconciliation; there is no automatic paid retry or cursor
reset. OpenAI extraction uses a separate client with SDK retries disabled;
comparison and ordinary answer clients are unchanged. Extraction currently supports
OpenAI; unsupported providers fail intake before reserving an attempt, without
preventing the API from starting.

Completed receipts follow `DATA_RETENTION_DAYS`. Unresolved digests remain as
retry guards: they contain no conversation bodies or raw event IDs. Reconcile
these explicitly before releasing held work. Existing raw-data retention remains
in force. No migration of historical candidates or cursor reset is required.

## Feedback has distinct meanings

A wiki or FAQ approval records a content-review decision. It does not establish
that the model's earlier answer was good enough to send.

Only explicit answer-quality judgments with a reliable question binding count
for calibration, response routing eligibility and readiness. Multiple ratings of
one answer do not increase the distinct-question denominator; the latest judgment
wins. Staff-answer ratings count only when a nonblank AI draft existed.
Knowledge decisions and unmarked historical records remain audit history;
legacy escalation metadata alone cannot establish AI-answer provenance.
Separate bounded persistence cohorts prevent knowledge reviews from evicting
quality evidence.

Existing saved thresholds are loaded unchanged. Filtering future evidence does
not undo previous threshold adjustments. Any historical recalibration requires
its own reviewed operation; this implementation does not reset thresholds or
rewrite historical judgments.

## Names and compatibility

Active services use knowledge-oriented names:

- `KnowledgeExtractor`, `ExtractedKnowledge`, `KnowledgeExtractionResult`
- `KnowledgePipelineService`
- `KnowledgeCandidate`, `KnowledgeCandidateRepository`

The canonical modules live under `app.services.knowledge`. The web review uses
`KnowledgeCandidate` from `components/admin/knowledge-updates/types.ts`. Thin legacy imports
remain for existing operational scripts. Persisted `unified_training.db` and
`unified_faq_candidates`, existing `/admin/training` API endpoints and serialized
fields remain compatibility contracts. They are not evidence that new candidates
are public FAQs. The actual FAQ service and publishing operations retain FAQ names.
