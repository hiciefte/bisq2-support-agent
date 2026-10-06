# Matrix staff-context review

Matrix **Staff context** mode copies a sanitized support question into the
configured staff room and posts a short, cited AI context note in its native
thread. It also persists the question and exact generated note in Admin
Escalations. This is a staff-review stage; it has no public publication action.

| Control | Staff-context behavior |
| --- | --- |
| Generation | Enabled while Staff context is selected |
| Source-room auto-send | Disabled |
| Response kind / audience | `public_context` / `staff_room` |
| AI response mode | `hitl` |
| Immediate acknowledgment | None |
| User escalation notice | None, including errors and timeouts |
| Internal notice target | Staff room |
| Admin approval | Records an internal decision; never delivers to the customer |
| Admin rejection | Closes the internal case; does not remove an already posted staff note |

Web Chat keeps its existing direct-answer workflow. This change does not enable
Bisq 2, Matrix sync, ChatOps, or any existing disabled runtime channel. Existing
policy rows migrate with their previous `answer` / `source_room` behavior. An
operator must explicitly select Staff context to use the new path. Turning it
off preserves the audience of existing cases.

## Intake, generation, and publication

Configure approved group rooms in `MATRIX_CONTEXT_SOURCE_ROOMS` and a distinct
staff destination in `MATRIX_STAFF_ROOM`. This read scope never expands
`MATRIX_RESPONDER_ROOMS`; that allowlist does not gate staff-context delivery.
Select **Off** in the Matrix runtime policy to stop new context notes. Clearing
`MATRIX_CONTEXT_SOURCE_ROOMS` and recreating the API disables intake. An empty
responder allowlist or the legacy autonomous-delivery switch alone does not stop
staff-context notes. The bot must already be joined and able to decrypt the
staff room with its existing identity. Staff membership checks use configured
trusted IDs, never display names or claims in a message.

The existing ingress classifier filters non-questions and routine chatter. Each
accepted source event gets an immediate durable review case before retrieval.
Generation waits for the configured first-response delay. Current source text,
redactions, activity, and source age are checked through Matrix context reads
before generation and again before publication. Recent staff participation
defers a case; it does not establish that the question was answered. Sources
older than one hour or with an incomplete context window remain for Admin review.

Native replies and thread messages join a captured incident only for the same
author, source room and trial. When their referenced incident is unavailable,
eligible questions are saved for Admin with `incident_relation_unresolved` before
retrieval or model reservation. This is deterministic deferral, not model silence.
It also holds self-contained replies to another author's uncaptured incident;
the runtime does not guess whether their missing context matters. The existing
explicit-new-issue rule can still start a separate incident. Follow-ups to a held
case remain there without automatic generation or delivery.

Captured same-author messages already feed both the combined retrieval question
and model context. Unlinked fragments still use the existing bounded continuation
rule; the runtime does not reconstruct a missing relationship from user identity
or nearby room messages alone.

The context generator uses the configured answer model and a staff-only variant
of the public-context prompt. Before drafting, an evidence resolver combines
relevant public wiki passages, verified published harness FAQs, current reviewed
LLM-wiki guidance, release-scoped code facts and bounded live observations.
FAQ text and its public slug must match the authoritative record and public
service. Compiled guidance is reread from current reviewed pages so a withdrawn
page cannot survive through stale retrieval metadata. Internal provenance is
labeled honestly; page-level references do not become claim-level public links.

Code evidence comes from the existing staff grounding service, with source
release labels and installed-version uncertainty. Monitoring is limited to
requested supported areas; enabled Bisq MCP tools supply bounded public market
observations. Their timestamps, scope and unavailable states remain in the input.
This does not expand the code corpus or install an upstream release watcher.
Ordinary public previews still reject internal evidence.

The model input, selected source kinds and provenance, version hashes, exact
rendered output, and staff event IDs remain attached to the case. No model weights
are trained or knowledge stores updated by resolving this evidence.

High-risk classified questions, insufficient evidence, failed generation, and
model silence remain visible as needing human attention. The system does not
interpret model silence as proof of resolution. Duplicate source events reuse
one case; non-questions filtered by ingress do not create review noise.

## Review and uncertain outcomes

Use **Record approval** or **Reject note** in Admin. Approval stores the reviewed
text and reviewer, with delivery marked not required. It does not send a public
reply, create an FAQ, or automatically ingest learning feedback. The public
customer polling/rating endpoints exclude internal cases. Matrix reactions and
ChatOps cannot publish these cases to the original room; use Admin for review.

Each processing attempt is reserved in SQLite. Root and child message intents,
stable transaction IDs, exact content, and accepted event IDs are saved before
the next transport action. A restart, cancellation, timeout, or ambiguous result
does not trigger automatic regeneration or retransmission. Staff must reconcile
these cases in Admin against the linked staff thread. A root accepted before a
later failure may exist without its context child. Deferred cases remain open
for staff handling; this first version does not automatically re-evaluate them.

New publication attempts retain separate `staff_root_delivery` and `staff_note_delivery`
diagnostics in their existing metadata. Each contains a fixed reason category,
whether the client send operation was invoked, whether it returned a response,
and a bounded response event ID when acknowledged. `operation_started` refers to
invoking the Matrix client method, not proof of an HTTP request: encryption and
local protocol checks can fail inside that method before transmission. A null
value preserves uncertainty around an interrupted invocation. Reserved transaction
IDs alone never prove that either message was sent. An acknowledged ID is still a
transport claim until an independently scoped readback verifies the actual event
and native thread relation.

These phase diagnostics begin when delivery is reserved. Earlier processing
interruptions retain their existing review status without a transport diagnostic;
in particular, cancellation does not prove that background provider work stopped.

Known policy refusals remain deferred. If the client definitely lacks the staff
room in its local room cache, publication is deferred with
`staff_context_room_state_unavailable` before calling the send method. The send path
does not sync, join, reset the saved cursor, or retry to recover that room. Other outcomes
distinguish response errors, missing event IDs, timeouts, local protocol/encryption
exceptions, and cancellation without storing exception messages. They remain
subject to the same reconciliation and no-retry rules.

At listener startup and reconnection, the first Matrix sync requests full room
state while retaining the existing saved cursor. This restores room objects and
encryption state without requesting an initial historical timeline. Since nio
processes rooms in response order, the handler temporarily buffers in-scope
messages until the complete successful response has been processed. It then
dispatches those messages once, in order, under the current room policy.

This buffer holds at most 1,024 callbacks and is not crash-durable. A buffer
overflow, interrupted dispatch, or failed initialization after cursor advancement
stops intake as unhealthy and requires operator reconciliation. The runtime does
not reset the cursor or automatically replay the buffered messages. A failed sync
that has not advanced the cursor can reconnect and request full state again.
Authenticated connection health alone does not establish active listener readiness.

Rejected model output keeps `context_reason=invalid_model_output` and now includes
an optional `validation_diagnostic` with a fixed code for JSON/schema, source-ID,
silence, note-text/citation, or rendering failures. It does not include rejected
text or exception details, and it does not relax validation. Older cases without
these diagnostics remain unclassified; absence is not evidence of success or a
specific failure cause.

The runtime caps concurrently pending context tasks at 100; overflow creates an
Admin case without model calls or a public fallback. SQLite availability is
required before generation. If persistence fails, processing stops and logs the
failure; it cannot create a durable review case while the database is unavailable.

## Rollout boundary

Local tests simulate Matrix transport and model results. A real staff-only
server trial is still required to verify continuous sync, encrypted delivery,
latency, and staff usefulness. The completed operator-supervised pilot is separate
evidence. Keep runtime generation off until a separately controlled trial is ready.
Public-room posting remains a separate feature and rollout decision.

An opt-in bounded trial uses `MATRIX_CONTEXT_TRIAL_ID`,
`MATRIX_CONTEXT_TRIAL_START_AT`, `MATRIX_CONTEXT_TRIAL_END_AT`, and
`MATRIX_CONTEXT_TRIAL_MAX_CASES`. Dates require an explicit timezone. The window
must be positive and at most 48 hours; the case limit is 1–10 (default 10).
Existing operation is unchanged when the trial ID and dates are empty.

The ID binds an immutable descriptor containing the source rooms, staff room,
start, end, and case limit in the escalation database. Reusing the ID with changed
settings fails closed. Reservations are atomic across workers and survive process
restarts and case retention. A case consumes a slot before paid retrieval, even
if the model later chooses silence, publication is suppressed, or the outcome is
uncertain. This deliberately bounds paid cases and consequently bounds notes;
it does not promise ten published notes. Changing to a new ID starts a distinct
trial and requires a new explicit operational decision.

Source events before the start timestamp remain deferred for Admin review, with
no paid retrieval or generation. Keep generation off during initial sync catch-up,
verify the restored account/device and encrypted room state, and record the saved
cursor before enabling the trial policy. The trial does not reset that cursor.
Trial authentication restores only the established session; it cannot fall back
to creating a new login/device.

Time and reservation checks run before retrieval, model generation, and both
staff sends. A local expiry task turns Matrix generation off and cancels pending
context workers. Already-started network/model
operations may finish after cancellation and remain uncertain until reconciled;
they are never automatically retried. A process that is down at expiration still
rejects expired work after restart. Filling the cap denies further paid admission;
an operator can then reconcile the admitted cases and turn the policy off.

Cases retain whether generation was called, the exact model decision, and reported
token counters. `model_called=null` with a reserved call means interruption left
the call outcome unknown. Missing usage is unknown, not zero cost. This accounting
does not include retrieval embedding charges, ingress language-detection tiebreaks,
or provider-side invoice adjustments. Language detection precedes trial admission:
while generation stays on after the case cap, incoming messages can still incur
that auxiliary cost. Turn generation off once admitted work is reconciled. The
case cap bounds note-generation cases, not every provider call in shared ingress.
