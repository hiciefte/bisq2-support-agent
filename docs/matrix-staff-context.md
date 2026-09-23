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
`MATRIX_RESPONDER_ROOMS`. The bot must already be joined and able to decrypt the
staff room with its existing identity. Staff membership checks use configured
trusted IDs, never display names or claims in a message.

The existing ingress classifier filters non-questions and routine chatter. Each
accepted source event gets an immediate durable review case before retrieval.
Generation waits for the configured first-response delay. Current source text,
redactions, activity, and source age are checked through Matrix context reads
before generation and again before publication. Recent staff participation
defers a case; it does not establish that the question was answered. Sources
older than one hour or with an incomplete context window remain for Admin review.

The context generator uses the configured answer model with the existing
public-context prompt. This first runtime path includes public wiki evidence
only. Private FAQs, compiled knowledge, code facts, and unsupported source types
are excluded. The model input, selected evidence, version hashes, exact rendered
output, and staff event IDs remain attached to the case. This does not train
weights or change the model or prompt.

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

The runtime caps concurrently pending context tasks at 100; overflow creates an
Admin case without model calls or a public fallback. SQLite availability is
required before generation. If persistence fails, processing stops and logs the
failure; it cannot create a durable review case while the database is unavailable.

## Rollout boundary

Local tests simulate Matrix transport and model results. A real staff-only
server trial is still required to verify continuous sync, encrypted delivery,
latency, and staff usefulness. The completed operator-supervised pilot is separate
evidence; installing this code does not reproduce its 48-hour/ten-note limit or
resume it. Keep runtime generation off until a separately controlled trial is ready.
Public-room posting remains a separate feature and rollout decision.
