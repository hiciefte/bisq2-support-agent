# Matrix Staff-Room Escalation Workflow

This document describes the Matrix-native human review flow for escalations.

## Required Room Configuration

- `MATRIX_SYNC_ROOMS`: Historical support Q/A import rooms; also the legacy live
  ingress scope when `MATRIX_RESPONDER_ROOMS` is unset.
- `MATRIX_RESPONDER_ROOMS`: Optional explicit scope for live support activity and
  delivery, independent from historical imports.
- `MATRIX_STAFF_ROOM`: Staff room for escalation notices and actions.
- `MATRIX_ALERT_ROOM`: Optional fallback room used in local/dev setups.

For an isolated staff-room experiment, set `MATRIX_RESPONDER_ROOMS` to only the
approved room. Leave `MATRIX_SYNC_ROOMS` unchanged so historical support-room
imports continue. Point `MATRIX_STAFF_ROOM` and `MATRIX_CHATOPS_ROOM_IDS` to the
approved room as well; neither can expand the explicit live scope. An empty
responder setting denies all live rooms, while leaving it unset preserves legacy
behavior. All reviewed sends use the same transport boundary as ordinary answers.

Trusted staff messages are treated as staff activity or commands, not user
questions; messages from the bot itself are also ignored. A genuine ingress
drill needs a non-staff test participant. Keep generation off through initial
sync, then submit a new test question after enabling it. Verify encrypted event
decryption, queue creation, and one reviewed delivery separately. Shadow mode
and the global delivery stop suppress automatic queue notices, so use the admin
review surface while those controls remain active. The global stop deliberately
does not prevent an explicit staff-reviewed send.

## Staff Action Modes

When an escalation is routed to `staff_room`, the bot posts a notice with:

- Escalation ID
- User and question summary
- Copy-ready AI draft answer
- Optional codebase-enriched staff context, clearly marked internal-only
- Routing reason and confidence
- Top sources and admin deep link

## Actions From Matrix Staff Room

- React `👍` on the escalation notice: approve and send only the copy-ready draft to the user.
- React `👎` on the escalation notice: dismiss escalation with no reply.
- Reply in thread with `/send`: send only the copy-ready draft unchanged.
- Reply in thread with `/send <edited reply>`: send edited text to user.
- Reply in thread with `/dismiss`: dismiss escalation with no reply.

Reactions provide quick approval or dismissal. Thread commands give more control:
use `/send` to send the draft unchanged, `/send <edited reply>` to send edited
text, and `/dismiss` to close without replying.

When a notice includes codebase-enriched staff context, that context is for
internal investigation only. It is not sent by `👍` or `/send`, and staff should
use it only to decide whether the copy-ready draft needs editing.

Command actions require replying to a staff escalation notice event.

## Threading Behavior

- Escalation notice is the thread root in the staff room.
- Bot action confirmations are posted as threaded `m.notice` messages.
- This keeps each escalation review compact and auditable.
