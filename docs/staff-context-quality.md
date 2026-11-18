# Staff-context review and model budgets

This workflow prepares drafts in the configured Staff room. Reactions and thread
replies record judgments; they cannot send an answer to the source room. A human
must send any public reply. Web chat and direct answers use their existing paths.

## Reviewing a draft

The line below a draft offers four reactions: 👍 would send as is, ✏️ would send
after editing, ❌ wrong, and 🚫 not needed. Only configured trusted Staff IDs count.
The latest active reaction by each reviewer on each note wins. Different
reviewers' judgments remain separate. Removing a reaction restores that person's
previous active judgment, if any.

A trusted Staff member can reply in the native Staff thread with proposed answer
text. The case stores that text, its reviewer/time and its normalized character
edit distance from the proposed reply. This records a proposed answer, not actual
reuse. Neither reactions nor proposed answers feed learning, FAQ creation or
auto-send threshold calibration.

To count an authorized local database copy without starting the application:

```bash
cd api
python -m app.scripts.summarize_staff_context --database /path/to/escalations.db
```

The report separates posted notes, uncertain deliveries, reviewed-note coverage,
per-reviewer verdicts and routing reasons. Transport receipts do not establish
semantic correctness, independent delivery verification, public reuse or time
saved.

## New trial admission

New trials require explicit model budgets. No amount is enabled by default:

- `MATRIX_CONTEXT_TRIAL_BUDGET_USD`: total model spend ceiling.
- `MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD`: UTC-day model spend ceiling.
- `MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION`: conservative input price ceiling,
  including any cache-write premium.
- `MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION`: output price ceiling.
- Existing ID, source-room, Staff-room and timezone-qualified start/end settings.
  The fixed window may be at most 30 days.

The descriptor pins the model, maximum output tokens, prices, budgets and window.
Changing a bound descriptor is refused. Old count-bound descriptors remain
byte-compatible for reconciliation; they cannot be used to bind a new trial.
The legacy maximum-case setting does not cap a new spend-bound trial.

Admission uses an atomic database transaction immediately before a provider
invocation. It reserves a conservative input bound plus maximum output cost.
Gate, first-draft and update calls have separate durable records. Deterministic
filtering and retrieval do not consume a note generation. A timeout, crash or
missing usage retains the reservation; only valid measured usage releases the
unused difference. No automatic retry replenishes an uncertain attempt. UTC-day
rollover and the hard cutoff are checked again at the invocation boundary.

The supported adapter makes one tool-free provider request with retries disabled.
Unknown adapters, changed models/output bounds, or prices above the approved
ceilings fail closed. The conservative ledger is not a provider invoice.

**Scope limitation:** these budgets account for gate and draft model calls.
Existing shared retrieval embeddings, external data services and operator costs
are not included. An all-provider monetary cap needs separately scoped retrieval
accounting. Do not describe this model budget as a total operating-cost cap.

No deployment, activation, frozen-controller amendment or policy enablement is
implied by these application changes. Existing pilot histories and limits remain
unchanged.

## Staff reply contract

Staff drafts use an independent prompt. The model returns `reply`, `staff_note`,
`source_ids`, `action` (`reply`, `question` or `silence`) and `reason`. The reply
aims for fewer than 40 words: a supported cause and action, or one question when
a missing fact decides the procedure. Supporting evidence and uncertainty belong
in the separate Staff note. Source IDs must refer to evidence actually supplied.

Documented remedies and menu paths are allowed in Staff drafts. Risk-word matches
label a draft “Money at risk” rather than preventing generation. The safeguards
against requesting seed words/private keys, promising outcomes or claiming that
Staff have acted remain. Scam concerns retain the existing safety warning.

Evidence applicability is separate from relevance. Requester product facts can
scope retrieval; a nearby helper's product mention cannot choose that scope.
Unknown requester scope stays broad rather than falling back to keyword product
selection. Staff retrieval keeps the full candidate set when ColBERT is disabled,
unavailable or returns invalid/ambiguous results; it does not label an unranked
prefix as successfully reranked. Other callers retain their existing defaults.
Explicit product conflicts are excluded before the evidence limit, with the
original text and declarations retained for Admin. Unknown or contradictory
source labels are not silently corrected. The draft receives product/scope and
public-link availability, plus missing-parent, omitted-event and attachment
coverage. Retrieved procedures do not establish the requester's asset, role or
trade stage; a missing fact that decides the remedy requires a question.

A public-link indicator means an allowed URL was supplied, not that its current
page or the draft's factual claims were independently verified. Internal evidence
remains Staff-only. Multiple participants reporting symptoms are attributed
observations, not proof of a shared network incident.

Length is a style target, not a reason to discard output. Invalid or withheld
output remains on the Admin case as literal text. A silence caused by missing
knowledge records a short topic in `knowledge_gap`; the gap itself is not posted.

Optional writing-style examples are loaded from
`DATA_DIR/staff-context-examples.json`:

```json
[{"reply": "Which application version is installed?"}]
```

Keep real room examples in that private data directory, with no names, handles,
trade identifiers or transaction identifiers. They illustrate style and are never
factual grounding for a new answer. The repository contains only a small synthetic
fallback set. Do not commit private examples, pilot inputs or generated outputs.

## Conversation handling

New spend-bound trials use one open request owned by the requester. Follow-ups,
product clarification, edits and acknowledgements attach to that request. Native
replies preserve who said what; nearby participants' words remain attributed
context. A requester reporting resolution can close the request. Related trusted
Staff assistance holds further drafts for that request without falsely recording
resolution. Unrelated Staff chatter does not suppress another request.

The first-response delay restarts when the requester adds a message. Before
reserving a draft call, a separately accounted model gate classifies the exchange
as an unanswered support request, not a request, already answered, or one
participant helping another. It selects only supplied event IDs for the draft.
Unrelated Staff activity is context rather than a room-wide suppression rule.
Obvious acknowledgements do not create requests or call a model on their own.

After a request is closed, handled by Staff or has had a generation,
an unthreaded later message is held as a boundary candidate on the existing case.
After the quiet delay, a separately budgeted gate compares it with the prior
request. Only a validated distinct request creates a new case, atomically with
the boundary receipt. Time gaps and topic-marker phrases are not proof. Native
follow-ups and acknowledgements stay with their known request; ambiguous or
invalid decisions remain visible for Admin. Restart cannot retry an uncertain
boundary call, and creating a case cannot reset the trial's spend.

After a draft, material new requester facts can produce at most one update in the
same Staff thread. Helper-only additions do not consume that update. A completed,
renderable first draft withheld because the
conversation changed before its note was attempted can use that one remaining
generation after a fresh gate; this does not retry an uncertain delivery.
Knowledge-gap silence or rejected output does not qualify for an unchanged-input
replacement. An acknowledged root is reused rather than sent again. Draft and
delivery claims are durable. A pending or uncertain
attempt requires reconciliation; restart does not retry it. Both notes remain
available for per-note judgments. Closed Admin cases, policy disablement, changed
request snapshots and expired budgets prevent publication.

The new workflow retains subscription turns in the existing escalation case and
uses the existing bounded source check. It does not paginate room history or
create a separate conversation database. Older immutable trials keep their
original workflow and accounting for historical reconciliation.

## Preparing and running a private replay

`python -m app.scripts.replay_staff_context --help` exposes two distinct stages.
`prepare` reads authorized local case/thread exports, a session index, comparison
references and the private style examples. It makes no provider or Matrix calls.
It writes an immutable input/code plan, conservative cost envelopes and a report
whose after-values remain unmeasured.

`execute` requires the owner's explicit paid-call approval and the exact prepared
plan digest. It checks the inputs and implementation against that plan, reserves
model spend through the same ledger as live work, and stops at the agreed dollar,
call or elapsed-time limit. Each attempted run has its own intent and receipts;
an interrupted or uncertain run is not resumed. Keep all input, plan, database and
output files private and outside Git. Do not put credentials in command lines or
reports.

Replay uses the same event conversion, request coordinator, gate and Staff draft
service. A chronological virtual clock exposes only messages observed by each
quiet deadline. Saved Staff messages enter the conversation only when virtual
time reaches them and may affect later gates. Separate comparison references
remain report-only and never enter prompts. Saved document
excerpts from an already-arrived anchor substitute for retrieval; their exact
historical capture times can be unknown. Live observations with unproved or future
timestamps are excluded. Sanitized excerpts without usable URLs are explicitly
marked as saved excerpts, not given invented citations. This mode makes no fresh
retrieval, embedding, Matrix or tool calls and cannot send a message.

Report note/update calls separately from gate calls. Report reference coverage
alongside non-request rates: a gate prediction is not independent ground truth.
Action agreement and limitation-opening counts are descriptive mechanics; they
are not Staff verdicts, actual reuse, measured time saved or public-readiness
claims. Partial source windows and unknown comparison outcomes remain visible.
