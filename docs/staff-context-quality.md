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
