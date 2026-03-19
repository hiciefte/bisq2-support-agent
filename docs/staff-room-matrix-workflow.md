# Matrix Staff-Room Escalation Workflow

This document describes the Matrix-native human review flow for escalations.

## Required Room Configuration

- `MATRIX_SYNC_ROOMS`: User-facing rooms where inbound questions are processed.
- `MATRIX_STAFF_ROOM`: Staff room for escalation notices and actions.
- `MATRIX_ALERT_ROOM`: Optional fallback room used in local/dev setups.

## Staff Action Modes

When an escalation is routed to `staff_room`, the bot posts a notice with:

- Escalation ID
- User and question summary
- AI draft answer
- Routing reason and confidence
- Top sources and admin deep link

## Actions From Matrix Staff Room

- React `👍` on the escalation notice: approve and send the AI draft to user.
- React `👎` on the escalation notice: dismiss escalation with no reply.
- Reply in thread with `/send`: send AI draft unchanged.
- Reply in thread with `/send <edited reply>`: send edited text to user.
- Reply in thread with `/dismiss`: dismiss escalation with no reply.

Reactions provide quick approval or dismissal. Thread commands give more control:
use `/send` to send the draft unchanged, `/send <edited reply>` to send edited
text, and `/dismiss` to close without replying.

Command actions require replying to a staff escalation notice event.

## Threading Behavior

- Escalation notice is the thread root in the staff room.
- Bot action confirmations are posted as threaded `m.notice` messages.
- This keeps each escalation review compact and auditable.
