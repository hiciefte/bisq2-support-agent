# Public-context support experiment

The first experiment compares brief AI context notes with the ordinary direct
answer in ten representative, sanitized support scenarios. It runs explicitly
under staff review in an approved operations room. It does not enable a new
automatic room behavior or change web-chat answers.

A useful note contributes a public source, a relevant fact, one necessary
clarification, or a fresh, narrowly scoped infrastructure observation. Silence is
the intended result when the conversation needs no additional contribution.
Review usefulness, duplication, factual support, and conversational fit separately.
An AI reviewer can simulate staff assessment; this does not measure real staff
time savings or human acceptance.

## Preview contract

`PublicContextService` accepts the question, recent messages, public evidence and
trusted participation signals. It suppresses generation when staff are active,
the issue is resolved, the bot recently replied, or a risky action involving
funds is under discussion. These signals must be supplied by the trusted trial
operator. They are not inferred from untrusted claims in a user's message.

The configured answer model chooses a note, one clarification, or silence.
Notes have at most 80 words and two source citations. Every nonempty preview has
an AI label and requires review. Unknown citations, malformed output and model
errors produce silence, with an internal reason. Schema checks do not establish
factual correctness: inspect the complete sources before approving a note.

Use public Wiki or documentation evidence. Raw staff code records are rejected;
the separate staff grounding brief remains internal. Monitoring evidence must
retain its observation time, freshness and coverage. An unavailable probe is not
proof of a working service or a network outage.

From `api/`, validate a private batch without a provider call:

```sh
python -m app.scripts.preview_public_context --input /private/path/cases.json
```

The input shape is `{"cases": [{"id": "case-01", "request": {...}}]}`.
The request fields are defined by `PublicContextRequest`. There are at most ten
cases per batch. To execute an authorized evaluation, add `--execute --output
/private/path/results.jsonl`. The output must not already exist. Execution uses
the configured answer model, one attempt per case, and a conservative observed
generation-cost stop with a next-call reserve. This is not a provider invoice
ceiling. No room messages, ratings, learning updates, or source promotions are
performed by this command.

## Operations-room trial

Freeze cases and review criteria before evaluating outputs. Mark constructed room
context and monitoring fixtures explicitly. Do not present fixtures as live
incidents. Compare against the matching direct-answer evidence when available;
contextual variants are not controlled before/after production comparisons.

After review, a trial operator may publish the approved sanitized examples to
the exact authorized operations room. Use native Matrix replies to the relevant
example message and retain delivery receipts. Recheck the room's current context
before each publication. An uncertain transmission must be inspected before a
retry. Keep the batch finite; do not enable room-wide automation for this trial.

The stopping condition is ten assessed cases, no unsupported public claims or
staff-only leakage, documented usefulness/noise outcomes, and verified delivery
of the approved subset. A later automatic integration needs reliable case-level
participation signals; the preview service alone does not establish them.
